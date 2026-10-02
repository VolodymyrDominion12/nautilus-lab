"""Gates on *new exposure* that sit between a robot's signal and the risk layer.

Source: the trade-level analysis of batch `20261001_182028_batch` (docs/32). On both
BTC and ETH, 1h:

* entries against the slope of a slow EMA (200 bars, slope over 24 bars) carried
  most of the loss; aligned entries were flat-to-positive;
* breakouts taken while volatility was compressed (mean bar range over 24 bars
  below its 300-bar mean) were the worst tercile;
* an opposite signal that closed a position *and* opened the reverse one lost on
  every reversal in the sample.

These were found on the very OOS data they are judged on, so every gate here is
**off by default** and must be tested as a pre-registered hypothesis (docs/27 R-2),
not switched on because it "looked better".

The filter never blocks an exit: it only decides whether the *entry* half of a plan
may go ahead. Exits stay outside every gate (see `domain/position_plan.py`).

Pure domain: closed bars only, `Decimal` throughout, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.decision_trace import Stage, TraceStep, Verdict, step
from nautilus_lab.domain.ema import ExponentialMovingAverage
from nautilus_lab.domain.errors import InvalidRiskError
from nautilus_lab.domain.signals import SignalSide
from nautilus_lab.domain.windows import RollingWindow


@dataclass(frozen=True, slots=True)
class EntryFilterParams:
    """Switches and windows of the entry gates. Every gate defaults to off."""

    #: Enter only in the direction of the slow EMA's slope.
    htf_trend: bool = False
    htf_ema_period: int = 200
    htf_slope_lookback: int = 24
    #: Enter only while short-term bar ranges are at least `min_vol_ratio` x long-term.
    vol_expansion: bool = False
    vol_fast_period: int = 24
    vol_slow_period: int = 300
    min_vol_ratio: Decimal = Decimal("1")
    #: An opposite signal only closes the position; the reverse entry is dropped.
    no_instant_reverse: bool = False

    def __post_init__(self) -> None:
        if self.htf_ema_period < 2:
            raise InvalidRiskError("htf_ema_period must be >= 2")
        if self.htf_slope_lookback < 1:
            raise InvalidRiskError("htf_slope_lookback must be >= 1")
        if self.vol_fast_period < 1:
            raise InvalidRiskError("vol_fast_period must be >= 1")
        if self.vol_slow_period <= self.vol_fast_period:
            raise InvalidRiskError("vol_slow_period must be > vol_fast_period")
        if self.min_vol_ratio <= 0:
            raise InvalidRiskError("min_vol_ratio must be > 0")

    @property
    def any_gate(self) -> bool:
        """True when at least one entry gate (not the reversal rule) is on."""
        return self.htf_trend or self.vol_expansion

    def warmup_bars(self) -> int:
        """Closed bars the enabled gates need before their first verdict."""
        need = 0
        if self.htf_trend:
            need = max(need, self.htf_ema_period + self.htf_slope_lookback)
        if self.vol_expansion:
            need = max(need, self.vol_slow_period)
        return need


@dataclass(frozen=True, slots=True)
class EntryVerdict:
    allowed: bool
    steps: tuple[TraceStep, ...]
    #: Short token of the first gate that refused, for `blocked_by` ("filter.<code>").
    code: str | None = None


class EntryFilter:
    """Feed every closed bar with `update`; ask `evaluate(side)` before an entry."""

    def __init__(self, params: EntryFilterParams) -> None:
        self._params = params
        self._ema = ExponentialMovingAverage(params.htf_ema_period)
        self._ema_history = RollingWindow(params.htf_slope_lookback + 1)
        self._ranges = RollingWindow(params.vol_slow_period)
        self._seen = 0

    @property
    def params(self) -> EntryFilterParams:
        return self._params

    def update(self, bar: OhlcvBar) -> None:
        self._seen += 1
        self._ema.update(bar.close)
        value = self._ema.value
        if value is not None:
            self._ema_history.push(value)
        if bar.close > 0:
            self._ranges.push((bar.high - bar.low) / bar.close)

    def htf_slope(self) -> Decimal | None:
        """EMA now minus EMA `htf_slope_lookback` bars ago; None while warming up."""
        if not self._ema_history.full:
            return None
        history = self._ema_history.values()
        return history[-1] - history[0]

    def vol_ratio(self) -> Decimal | None:
        """Mean relative bar range over the fast window / over the slow window."""
        if not self._ranges.full:
            return None
        values = self._ranges.values()
        fast = values[-self._params.vol_fast_period :]
        slow_mean = sum(values, Decimal("0")) / Decimal(len(values))
        if slow_mean <= 0:
            return None
        fast_mean = sum(fast, Decimal("0")) / Decimal(len(fast))
        return fast_mean / slow_mean

    def evaluate(self, side: SignalSide) -> EntryVerdict:
        """May a new `side` position open on the bar just fed? FLAT is always allowed."""
        params = self._params
        if side is SignalSide.FLAT or not params.any_gate:
            return EntryVerdict(allowed=True, steps=())
        steps: list[TraceStep] = []
        refused: str | None = None
        if params.htf_trend:
            slope = self.htf_slope()
            thresholds = {
                "htf_ema_period": params.htf_ema_period,
                "htf_slope_lookback": params.htf_slope_lookback,
            }
            if slope is None:
                steps.append(
                    step(
                        Stage.FILTER,
                        "htf_trend",
                        Verdict.BLOCK,
                        result="warming up",
                        values={"bars_seen": self._seen},
                        thresholds=thresholds,
                        note="slow EMA not ready: no entry until the trend is known",
                    )
                )
                refused = refused or "htf_trend"
            else:
                aligned = slope > 0 if side is SignalSide.BUY else slope < 0
                steps.append(
                    step(
                        Stage.FILTER,
                        "htf_trend",
                        Verdict.PASS if aligned else Verdict.BLOCK,
                        result="aligned" if aligned else "against trend",
                        values={"slope": slope, "side": side.value},
                        thresholds=thresholds,
                    )
                )
                if not aligned:
                    refused = refused or "htf_trend"
        if params.vol_expansion:
            ratio = self.vol_ratio()
            thresholds_v: dict[str, Decimal | int] = {
                "min_vol_ratio": params.min_vol_ratio,
                "vol_fast_period": params.vol_fast_period,
                "vol_slow_period": params.vol_slow_period,
            }
            if ratio is None:
                steps.append(
                    step(
                        Stage.FILTER,
                        "vol_expansion",
                        Verdict.BLOCK,
                        result="warming up",
                        values={"bars_seen": self._seen},
                        thresholds=thresholds_v,
                        note="range history not full: no entry until volatility is known",
                    )
                )
                refused = refused or "vol_expansion"
            else:
                expanding = ratio >= params.min_vol_ratio
                steps.append(
                    step(
                        Stage.FILTER,
                        "vol_expansion",
                        Verdict.PASS if expanding else Verdict.BLOCK,
                        result="expanding" if expanding else "compressed",
                        values={"vol_ratio": ratio},
                        thresholds=thresholds_v,
                    )
                )
                if not expanding:
                    refused = refused or "vol_expansion"
        return EntryVerdict(allowed=refused is None, steps=tuple(steps), code=refused)
