"""Global-trend gate: no new entry against the trend of a much higher timeframe.

Why (2026-10-09): in a bull market a multi-week pullback turns the regime router's own
trend reading bearish, so it opens shorts (and range-leg shorts) against the big trend,
and those trades lose. `entry_filters.htf_trend` does not fix this: its EMA200 x 1h is
~8 days, a pullback flips it too. This gate looks at a moving average of *completed*
higher-timeframe closes (default: SMA 200 of daily closes, the classic bull/bear line)
and only vetoes the entry half of a plan that points against it:

* close above `MA * (1 + band)`  -> BULL: a new SELL is refused;
* close below `MA * (1 - band)`  -> BEAR: a new BUY is refused;
* inside the band the previous state is kept (hysteresis), so a price chopping around
  the line does not flip the gate on every bar. Before the first exit from the band the
  state is NEUTRAL and both sides may enter.

Exits, stops, regime switching and sizing are untouched: the gate sits beside
`EntryFilter` in the robot adapter and only removes `wants_entry`.

Higher-timeframe bars are built from the robot's own bars, which carry their CLOSE
time: a bar belongs to the bucket that contains `ts_utc - 1µs`, so the 1h bar that
closes at 00:00 is the last bar of the previous day. A bucket's close is used only once
the next bucket has started — the MA never sees an unfinished day. The current bar's
close (already known) is what is compared with that MA, so there is no look-ahead.

Weekly buckets start on Monday 00:00 UTC.

Off by default; found on data that has been looked at, so it is tested as a
pre-registered hypothesis like every other gate (docs/27 R-2).
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.decision_trace import Stage, Verdict, step
from nautilus_lab.domain.ema import ExponentialMovingAverage
from nautilus_lab.domain.entry_filters import EntryVerdict
from nautilus_lab.domain.errors import InvalidRiskError
from nautilus_lab.domain.signals import SignalSide

_TIMEFRAME = re.compile(r"^(\d+)([hdw])$")
_UNIT_HOURS = {"h": 1, "d": 24, "w": 168}
#: Monday. Daily and intraday buckets are aligned to midnight UTC either way.
_ANCHOR = datetime(1970, 1, 5, tzinfo=UTC)
_EPSILON = timedelta(microseconds=1)


def timeframe_hours(timeframe: str) -> int:
    """'4h' -> 4, '1d' -> 24, '1w' -> 168. Raises on anything else."""
    match = _TIMEFRAME.match(timeframe.strip().lower())
    if match is None or int(match.group(1)) < 1:
        raise InvalidRiskError(f"global trend timeframe must look like 4h, 1d or 1w: {timeframe!r}")
    return int(match.group(1)) * _UNIT_HOURS[match.group(2)]


class MaKind(StrEnum):
    SMA = "sma"
    EMA = "ema"


class WarmupPolicy(StrEnum):
    #: While the MA is not ready the gate lets entries through (behaves as if off).
    ALLOW = "allow"
    #: While the MA is not ready no entry opens (fail closed, like `htf_trend`).
    BLOCK = "block"


class TrendState(StrEnum):
    BULL = "bull"
    BEAR = "bear"
    NEUTRAL = "neutral"


@dataclass(frozen=True, slots=True)
class GlobalTrendParams:
    """Switch and shape of the global-trend gate. Off by default."""

    enabled: bool = False
    timeframe: str = "1d"
    period: int = 200
    ma: MaKind = MaKind.SMA
    #: Half-width of the no-flip zone around the MA, as a fraction (0.02 = +/-2%).
    band_pct: Decimal = Decimal("0.02")
    warmup: WarmupPolicy = WarmupPolicy.ALLOW

    def __post_init__(self) -> None:
        timeframe_hours(self.timeframe)
        if self.period < 2:
            raise InvalidRiskError("global trend period must be >= 2")
        if not Decimal("0") <= self.band_pct < Decimal("1"):
            raise InvalidRiskError("global trend band_pct must be in [0, 1)")
        # Accept plain strings from settings; keep the enum in the frozen value.
        object.__setattr__(self, "ma", MaKind(self.ma))
        object.__setattr__(self, "warmup", WarmupPolicy(self.warmup))

    @property
    def bucket(self) -> timedelta:
        return timedelta(hours=timeframe_hours(self.timeframe))

    def warmup_span(self) -> timedelta:
        """Calendar time of history the MA needs (+1 bucket for the unfinished one)."""
        if not self.enabled:
            return timedelta(0)
        return self.bucket * (self.period + 1)

    def warmup_bars(self, bar_step: timedelta) -> int:
        """`warmup_span` in bars of `bar_step`; 0 when off."""
        span = self.warmup_span()
        if span <= timedelta(0) or bar_step <= timedelta(0):
            return 0
        return -(-span // bar_step)  # ceil

    def label(self) -> str:
        """Short id for trial ids / registrations, e.g. `1d/sma200/band0.02/allow`."""
        ma = f"{self.ma.value}{self.period}"
        return f"{self.timeframe}/{ma}/band{self.band_pct}/{self.warmup.value}"


class GlobalTrendGate:
    """Feed every closed bar with `update`; ask `evaluate(side)` before an entry."""

    def __init__(self, params: GlobalTrendParams) -> None:
        self._params = params
        self._bucket = params.bucket
        self._current_key: int | None = None
        self._current_close: Decimal | None = None
        self._closes: deque[Decimal] = deque(maxlen=params.period)
        self._ema = ExponentialMovingAverage(params.period)
        self._last_close: Decimal | None = None
        self._state: TrendState | None = None
        self._completed = 0

    @property
    def params(self) -> GlobalTrendParams:
        return self._params

    @property
    def state(self) -> TrendState | None:
        """BULL / BEAR / NEUTRAL, or None while the MA is warming up."""
        return self._state

    @property
    def completed_buckets(self) -> int:
        return self._completed

    def ma(self) -> Decimal | None:
        if self._params.ma is MaKind.EMA:
            return self._ema.value
        if len(self._closes) < self._params.period:
            return None
        return sum(self._closes, Decimal("0")) / Decimal(len(self._closes))

    def _key(self, ts: datetime) -> int:
        return (ts - _EPSILON - _ANCHOR) // self._bucket

    def update(self, bar: OhlcvBar) -> None:
        if not self._params.enabled:
            return
        key = self._key(bar.ts_utc)
        if self._current_key is not None and key != self._current_key:
            # The previous bucket is complete: its last close is the HTF close.
            if self._current_close is not None and self._current_close > 0:
                self._closes.append(self._current_close)
                self._ema.update(self._current_close)
                self._completed += 1
        self._current_key = key
        self._current_close = bar.close
        self._last_close = bar.close
        self._refresh_state(bar.close)

    def _refresh_state(self, price: Decimal) -> None:
        ma = self.ma()
        if ma is None:
            self._state = None
            return
        band = self._params.band_pct
        if price > ma * (1 + band):
            self._state = TrendState.BULL
        elif price < ma * (1 - band):
            self._state = TrendState.BEAR
        elif self._state is None:
            self._state = TrendState.NEUTRAL
        # else: inside the band -> keep the previous state (hysteresis)

    def evaluate(self, side: SignalSide) -> EntryVerdict:
        """May a new `side` position open on the bar just fed? FLAT is always allowed."""
        params = self._params
        if side is SignalSide.FLAT or not params.enabled:
            return EntryVerdict(allowed=True, steps=())
        thresholds: dict[str, Decimal | int | str] = {
            "timeframe": params.timeframe,
            "period": params.period,
            "ma": params.ma.value,
            "band_pct": params.band_pct,
        }
        ma = self.ma()
        if ma is None or self._state is None:
            allowed = params.warmup is WarmupPolicy.ALLOW
            return EntryVerdict(
                allowed=allowed,
                steps=(
                    step(
                        Stage.FILTER,
                        "global_trend",
                        Verdict.PASS if allowed else Verdict.BLOCK,
                        result="warming up",
                        values={"completed_buckets": self._completed},
                        thresholds=thresholds,
                        note=(
                            "global MA not ready: entries allowed (warmup=allow)"
                            if allowed
                            else "global MA not ready: no entry until the trend is known"
                        ),
                    ),
                ),
                code=None if allowed else "global_trend",
            )
        state = self._state
        against = (state is TrendState.BULL and side is SignalSide.SELL) or (
            state is TrendState.BEAR and side is SignalSide.BUY
        )
        return EntryVerdict(
            allowed=not against,
            steps=(
                step(
                    Stage.FILTER,
                    "global_trend",
                    Verdict.BLOCK if against else Verdict.PASS,
                    result="against global trend" if against else "aligned",
                    values={
                        "state": state.value,
                        "close": self._last_close,
                        "ma": ma,
                        "side": side.value,
                    },
                    thresholds=thresholds,
                ),
            ),
            code="global_trend" if against else None,
        )
