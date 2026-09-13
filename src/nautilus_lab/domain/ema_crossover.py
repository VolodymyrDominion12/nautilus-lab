from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.ema import ExponentialMovingAverage
from nautilus_lab.domain.signals import Signal, SignalSide


class EmaCrossover:
    """Always-in-market EMA cross on closed bars only."""

    def __init__(self, *, instrument_id: str, fast_period: int, slow_period: int) -> None:
        if fast_period >= slow_period:
            raise ValueError("fast_period must be < slow_period")
        self._instrument_id = instrument_id
        self._fast = ExponentialMovingAverage(fast_period)
        self._slow = ExponentialMovingAverage(slow_period)

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        return self.on_close(close=bar.close, bar_ts_utc=bar.ts_utc)

    def on_close(self, *, close: Decimal, bar_ts_utc: datetime) -> Signal | None:
        """Update on a closed bar. Returns a signal only after both EMAs are warm."""
        self._fast.update(close)
        self._slow.update(close)
        if not (self._fast.initialized and self._slow.initialized):
            return None
        fast = self._fast.value
        slow = self._slow.value
        if fast is None or slow is None:
            return None
        if fast >= slow:
            return Signal(
                instrument_id=self._instrument_id,
                side=SignalSide.BUY,
                bar_ts_utc=bar_ts_utc,
                reason=f"fast_ema {fast} >= slow_ema {slow}",
            )
        return Signal(
            instrument_id=self._instrument_id,
            side=SignalSide.SELL,
            bar_ts_utc=bar_ts_utc,
            reason=f"fast_ema {fast} < slow_ema {slow}",
        )
