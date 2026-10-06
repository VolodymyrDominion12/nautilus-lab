from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.decision_trace import (
    Stage,
    TraceStep,
    TraceValue,
    Verdict,
    pct_distance,
    step,
    warmup_step,
)
from nautilus_lab.domain.ema import ExponentialMovingAverage
from nautilus_lab.domain.signals import Signal, SignalSide


class EmaCrossover:
    """Always-in-market EMA cross on closed bars only."""

    def __init__(
        self,
        *,
        instrument_id: str,
        fast_period: int,
        slow_period: int,
        min_spread_pct: Decimal = Decimal("0"),
    ) -> None:
        if fast_period >= slow_period:
            raise ValueError("fast_period must be < slow_period")
        if min_spread_pct < 0:
            raise ValueError("min_spread_pct must be >= 0")
        self._instrument_id = instrument_id
        self._fast = ExponentialMovingAverage(fast_period)
        self._slow = ExponentialMovingAverage(slow_period)
        self._fast_period = fast_period
        self._slow_period = slow_period
        self._min_spread_pct = min_spread_pct
        self._current_side: SignalSide | None = None
        self._seen = 0
        self._trace: tuple[TraceStep, ...] = ()

    @property
    def last_trace(self) -> tuple[TraceStep, ...]:
        return self._trace

    @property
    def fast_value(self) -> Decimal | None:
        return self._fast.value

    @property
    def slow_value(self) -> Decimal | None:
        return self._slow.value

    @property
    def min_spread_pct(self) -> Decimal:
        return self._min_spread_pct

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        return self.on_close(close=bar.close, bar_ts_utc=bar.ts_utc)

    def on_close(self, *, close: Decimal, bar_ts_utc: datetime) -> Signal | None:
        """Update on a closed bar. Returns a signal only after both EMAs are warm."""
        self._seen += 1
        self._fast.update(close)
        self._slow.update(close)
        if not (self._fast.initialized and self._slow.initialized):
            self._trace = (
                warmup_step("EmaCrossover", seen=self._seen, required=self._slow_period),
            )
            return None
        fast = self._fast.value
        slow = self._slow.value
        if fast is None or slow is None:
            self._trace = (warmup_step("EmaCrossover", seen=self._seen),)
            return None

        diff = fast - slow
        spread_threshold = self._min_spread_pct * slow
        spread_pct = pct_distance(fast, slow)
        thresholds: dict[str, TraceValue] = {
            "fast_period": self._fast_period,
            "slow_period": self._slow_period,
            "min_spread_pct": self._min_spread_pct,
        }
        values: dict[str, TraceValue] = {
            "close": close,
            "fast_ema": fast,
            "slow_ema": slow,
            "spread_pct": spread_pct,
        }

        if diff >= spread_threshold:
            self._current_side = SignalSide.BUY
            self._trace = (
                step(
                    Stage.STRATEGY,
                    "EmaCrossover",
                    Verdict.EMIT,
                    result="buy",
                    values=values,
                    thresholds=thresholds,
                    note="fast EMA above slow with spread confirmation: target long",
                ),
            )
            return Signal(
                instrument_id=self._instrument_id,
                side=SignalSide.BUY,
                bar_ts_utc=bar_ts_utc,
                reason=f"fast_ema {fast} >= slow_ema {slow}",
            )
        elif -diff >= spread_threshold:
            self._current_side = SignalSide.SELL
            self._trace = (
                step(
                    Stage.STRATEGY,
                    "EmaCrossover",
                    Verdict.EMIT,
                    result="sell",
                    values=values,
                    thresholds=thresholds,
                    note="fast EMA below slow with spread confirmation: target short",
                ),
            )
            return Signal(
                instrument_id=self._instrument_id,
                side=SignalSide.SELL,
                bar_ts_utc=bar_ts_utc,
                reason=f"fast_ema {fast} < slow_ema {slow}",
            )
        else:
            held_str = self._current_side.value if self._current_side is not None else "neutral"
            self._trace = (
                step(
                    Stage.STRATEGY,
                    "EmaCrossover",
                    Verdict.INFO,
                    result=held_str,
                    values=values,
                    thresholds=thresholds,
                    note=f"spread within deadband (< {self._min_spread_pct}): holding {held_str}",
                ),
            )
            if self._current_side is not None:
                return Signal(
                    instrument_id=self._instrument_id,
                    side=self._current_side,
                    bar_ts_utc=bar_ts_utc,
                    reason=f"spread within deadband: holding {self._current_side.value}",
                )
            return None
