"""Regime-filtered Asian-range session breakout strategy for gold (`gold_session_orb`).

Built strictly from `specs/strategies/gold_session_orb.yaml` (Phase G2 of
`docs/38-gold-trading-spec-2026.md`):
- Forms the overnight Asian range (`00:00-07:00 Europe/London`, DST-aware via
  `domain/sessions.py`) on closed bars only.
- Filters out dead (`box_width / ATR < min_box_atr`) and exhausted
  (`box_width / ATR > max_box_atr`) overnight sessions.
- Requires breakout direction to agree with the slow trend EMA (default 200) and
  clears an ATR breakout buffer (`buffer_atr * ATR`).
- Allows at most one entry per London trading day to avoid the ~19% two-sided
  liquidity sweep days documented on gold.
- Flattens open positions on `max_hold_bars` (time-stop) or on entering
  `GoldSession.WEEKEND` (thin weekend liquidity / EWMA mark cap protection).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from nautilus_lab.domain.atr import AverageTrueRange
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.decision_trace import (
    Stage,
    TraceStep,
    TraceValue,
    Verdict,
    step,
    warmup_step,
)
from nautilus_lab.domain.ema import ExponentialMovingAverage
from nautilus_lab.domain.errors import InvalidRiskError
from nautilus_lab.domain.sessions import (
    GoldSession,
    classify_gold_session,
    is_gold_entry_session,
    london_trading_date,
)
from nautilus_lab.domain.signals import Signal, SignalSide


@dataclass(frozen=True, slots=True)
class GoldSessionOrbParams:
    """Parameters for `GoldSessionOrb`. All numbers are `Decimal` or `int`."""

    atr_period: int = 14
    trend_ema_period: int = 200
    min_box_atr: Decimal = Decimal("0.5")
    max_box_atr: Decimal = Decimal("3.5")
    buffer_atr: Decimal = Decimal("0.15")
    max_hold_bars: int = 24
    allow_short: bool = False
    min_asia_bars: int = 3

    def __post_init__(self) -> None:
        if self.atr_period < 2:
            raise InvalidRiskError("atr_period must be >= 2")
        if self.trend_ema_period < 2:
            raise InvalidRiskError("trend_ema_period must be >= 2")
        if self.min_box_atr < 0:
            raise InvalidRiskError("min_box_atr must be >= 0")
        if self.max_box_atr <= 0 or self.max_box_atr < self.min_box_atr:
            raise InvalidRiskError("max_box_atr must be > 0 and >= min_box_atr")
        if self.buffer_atr < 0:
            raise InvalidRiskError("buffer_atr must be >= 0")
        if self.max_hold_bars < 1:
            raise InvalidRiskError("max_hold_bars must be >= 1")
        if self.min_asia_bars < 1:
            raise InvalidRiskError("min_asia_bars must be >= 1")


class GoldSessionOrb:
    """Closed-bar Asian-range breakout strategy for gold with EMA trend and ATR box filters."""

    def __init__(
        self,
        *,
        instrument_id: str,
        params: GoldSessionOrbParams | None = None,
    ) -> None:
        self._instrument_id = instrument_id
        self._params = params or GoldSessionOrbParams()
        self._atr = AverageTrueRange(self._params.atr_period)
        self._trend_ema = ExponentialMovingAverage(self._params.trend_ema_period)
        self._seen = 0
        self._current_day: date | None = None
        self._box_high: Decimal | None = None
        self._box_low: Decimal | None = None
        self._asia_bars = 0
        self._traded_today = False
        self._position: SignalSide = SignalSide.FLAT
        self._bars_held = 0
        self._trace: tuple[TraceStep, ...] = ()

    @property
    def last_trace(self) -> tuple[TraceStep, ...]:
        return self._trace

    @property
    def box_high(self) -> Decimal | None:
        return self._box_high

    @property
    def box_low(self) -> Decimal | None:
        return self._box_low

    def sync_holding(self, holding: SignalSide) -> None:
        """Keep internal position state aligned with broker/engine stops."""
        if holding is SignalSide.FLAT:
            if self._position is not SignalSide.FLAT:
                self._position = SignalSide.FLAT
                self._bars_held = 0
        elif holding is not self._position:
            self._position = holding
            self._bars_held = 0

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        self._seen += 1
        atr = self._atr.update(bar)
        self._trend_ema.update(bar.close)
        ema = self._trend_ema.value
        session = classify_gold_session(bar.ts_utc)
        trading_day = london_trading_date(bar.ts_utc)

        if self._current_day is None or trading_day != self._current_day:
            self._current_day = trading_day
            self._box_high = None
            self._box_low = None
            self._asia_bars = 0
            self._traded_today = False

        if session is GoldSession.ASIA:
            self._box_high = bar.high if self._box_high is None else max(self._box_high, bar.high)
            self._box_low = bar.low if self._box_low is None else min(self._box_low, bar.low)
            self._asia_bars += 1

        required = max(self._params.trend_ema_period, self._params.atr_period)
        if atr is None or ema is None:
            self._trace = (warmup_step("GoldSessionOrb", seen=self._seen, required=required),)
            return None

        session_step = step(
            Stage.REGIME,
            "GoldSession",
            Verdict.INFO,
            result=session.value,
            values={
                "session": session.value,
                "asia_bars": self._asia_bars,
                "box_high": self._box_high,
                "box_low": self._box_low,
            },
        )

        # Active position management: exit on weekend blackout or max_hold_bars time-stop.
        if self._position is not SignalSide.FLAT:
            self._bars_held += 1
            if session is GoldSession.WEEKEND:
                self._trace = (
                    session_step,
                    step(
                        Stage.STRATEGY,
                        "GoldSessionOrb",
                        Verdict.EMIT,
                        result="flat",
                        values={"bars_held": self._bars_held, "close": bar.close},
                        note="weekend blackout flatten",
                    ),
                )
                self._position = SignalSide.FLAT
                self._bars_held = 0
                return self._signal(bar, SignalSide.FLAT, "gold orb weekend flatten")
            if self._bars_held >= self._params.max_hold_bars:
                self._trace = (
                    session_step,
                    step(
                        Stage.STRATEGY,
                        "GoldSessionOrb",
                        Verdict.EMIT,
                        result="flat",
                        values={"bars_held": self._bars_held, "close": bar.close},
                        thresholds={"max_hold_bars": self._params.max_hold_bars},
                        note="time-stop exit reached",
                    ),
                )
                self._position = SignalSide.FLAT
                self._bars_held = 0
                return self._signal(bar, SignalSide.FLAT, "gold orb time stop")
            self._trace = (
                session_step,
                step(
                    Stage.STRATEGY,
                    "GoldSessionOrb",
                    Verdict.INFO,
                    result="hold",
                    values={"bars_held": self._bars_held, "position": self._position.value},
                    thresholds={"max_hold_bars": self._params.max_hold_bars},
                ),
            )
            return None

        # Flat: only consider entries during London open and London-NY overlap.
        if not is_gold_entry_session(session):
            self._trace = (
                session_step,
                step(
                    Stage.STRATEGY,
                    "GoldSessionOrb",
                    Verdict.INFO,
                    result="outside_entry_session",
                    values={"session": session.value},
                ),
            )
            return None

        if self._traded_today:
            self._trace = (
                session_step,
                step(
                    Stage.STRATEGY,
                    "GoldSessionOrb",
                    Verdict.BLOCK,
                    result="daily_limit_reached",
                    note="max 1 entry per London trading day",
                ),
            )
            return None

        if (
            self._asia_bars < self._params.min_asia_bars
            or self._box_high is None
            or self._box_low is None
            or atr <= 0
        ):
            self._trace = (
                session_step,
                step(
                    Stage.STRATEGY,
                    "GoldSessionOrb",
                    Verdict.INFO,
                    result="incomplete_asia_box",
                    values={"asia_bars": self._asia_bars, "atr": atr},
                    thresholds={"min_asia_bars": self._params.min_asia_bars},
                ),
            )
            return None

        box_width = self._box_high - self._box_low
        box_atr_ratio = box_width / atr
        thresholds: dict[str, TraceValue] = {
            "min_box_atr": self._params.min_box_atr,
            "max_box_atr": self._params.max_box_atr,
            "buffer_atr": self._params.buffer_atr,
        }
        if box_atr_ratio < self._params.min_box_atr or box_atr_ratio > self._params.max_box_atr:
            self._trace = (
                session_step,
                step(
                    Stage.STRATEGY,
                    "GoldSessionOrb",
                    Verdict.BLOCK,
                    result="box_width_out_of_range",
                    values={"box_width": box_width, "atr": atr, "box_atr_ratio": box_atr_ratio},
                    thresholds=thresholds,
                ),
            )
            return None

        buffer = self._params.buffer_atr * atr
        long_trigger = self._box_high + buffer
        short_trigger = self._box_low - buffer
        values: dict[str, TraceValue] = {
            "close": bar.close,
            "ema": ema,
            "atr": atr,
            "box_high": self._box_high,
            "box_low": self._box_low,
            "box_atr_ratio": box_atr_ratio,
            "long_trigger": long_trigger,
            "short_trigger": short_trigger,
        }

        if bar.close > long_trigger and bar.close > ema:
            self._traded_today = True
            self._position = SignalSide.BUY
            self._bars_held = 0
            self._trace = (
                session_step,
                step(
                    Stage.STRATEGY,
                    "GoldSessionOrb",
                    Verdict.EMIT,
                    result="buy",
                    values=values,
                    thresholds=thresholds,
                    note="closed breakout above Asia box aligned with trend EMA",
                ),
            )
            return self._signal(bar, SignalSide.BUY, "gold asia breakout long")

        if self._params.allow_short and bar.close < short_trigger and bar.close < ema:
            self._traded_today = True
            self._position = SignalSide.SELL
            self._bars_held = 0
            self._trace = (
                session_step,
                step(
                    Stage.STRATEGY,
                    "GoldSessionOrb",
                    Verdict.EMIT,
                    result="sell",
                    values=values,
                    thresholds=thresholds,
                    note="closed breakdown below Asia box aligned with trend EMA",
                ),
            )
            return self._signal(bar, SignalSide.SELL, "gold asia breakout short")

        self._trace = (
            session_step,
            step(
                Stage.STRATEGY,
                "GoldSessionOrb",
                Verdict.INFO,
                result="no_breakout",
                values=values,
                thresholds=thresholds,
            ),
        )
        return None

    def _signal(self, bar: OhlcvBar, side: SignalSide, reason: str) -> Signal:
        return Signal(
            instrument_id=self._instrument_id,
            side=side,
            bar_ts_utc=bar.ts_utc,
            reason=reason,
        )
