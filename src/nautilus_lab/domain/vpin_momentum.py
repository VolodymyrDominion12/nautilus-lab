from __future__ import annotations

from decimal import Decimal

from nautilus_lab.domain.atr import AverageTrueRange
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.ema import ExponentialMovingAverage
from nautilus_lab.domain.signals import Signal, SignalSide
from nautilus_lab.domain.vpin import VpinModel


class VpinMomentum:
    """Momentum in the direction of informed (toxic) order flow, ATR trailing stop."""

    def __init__(
        self,
        *,
        instrument_id: str,
        vpin: VpinModel,
        ema_period: int = 50,
        atr_period: int = 14,
        atr_multiple: Decimal = Decimal("2"),
        min_hold_bars: int = 3,
    ) -> None:
        if ema_period < 2:
            raise ValueError("ema_period must be >= 2")
        if atr_period < 1:
            raise ValueError("atr_period must be >= 1")
        if atr_multiple <= 0:
            raise ValueError("atr_multiple must be > 0")
        if min_hold_bars < 0:
            raise ValueError("min_hold_bars must be >= 0")
        self._instrument_id = instrument_id
        self._vpin = vpin
        self._ema = ExponentialMovingAverage(ema_period)
        self._atr = AverageTrueRange(atr_period)
        self._atr_multiple = atr_multiple
        self._min_hold_bars = min_hold_bars
        self._direction = 0
        self._bars_in_position = 0
        self._extreme = Decimal("0")

    def on_trade_tick(self, *, is_buy: bool, volume: Decimal, dt_seconds: Decimal) -> None:
        if self._vpin is not None and hasattr(self._vpin, "update_from_trade"):
            self._vpin.update_from_trade(is_buy=is_buy, volume=volume)

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        state = self._vpin.update(bar)
        self._ema.update(bar.close)
        self._atr.update(bar)
        ema = self._ema.value
        atr = self._atr.value
        if ema is None or atr is None:
            return None

        if self._direction != 0:
            self._bars_in_position += 1
            self._extreme = (
                max(self._extreme, bar.high) if self._direction > 0 else min(self._extreme, bar.low)
            )
            stop = (
                self._extreme - self._atr_multiple * atr
                if self._direction > 0
                else self._extreme + self._atr_multiple * atr
            )
            hit_stop = bar.close <= stop if self._direction > 0 else bar.close >= stop
            lost_momentum = bar.close < ema if self._direction > 0 else bar.close > ema
            can_exit = self._bars_in_position >= self._min_hold_bars
            if can_exit and (hit_stop or lost_momentum):
                self._reset()
                return self._signal(
                    bar,
                    SignalSide.FLAT,
                    "vpin momentum exit" if lost_momentum else "vpin atr stop",
                )
            return None

        if state is None or not state.toxic:
            return None
        if bar.close > ema:
            self._enter(direction=1, bar=bar)
            return self._signal(bar, SignalSide.BUY, f"toxic flow up vpin={state.value}")
        if bar.close < ema:
            self._enter(direction=-1, bar=bar)
            return self._signal(bar, SignalSide.SELL, f"toxic flow down vpin={state.value}")
        return None

    @property
    def regimes_ready(self) -> bool:
        return self._ema.initialized and self._atr.initialized

    def _enter(self, *, direction: int, bar: OhlcvBar) -> None:
        self._direction = direction
        self._bars_in_position = 0
        self._extreme = bar.high if direction > 0 else bar.low

    def _reset(self) -> None:
        self._direction = 0
        self._bars_in_position = 0
        self._extreme = Decimal("0")

    def _signal(self, bar: OhlcvBar, side: SignalSide, reason: str) -> Signal:
        return Signal(
            instrument_id=self._instrument_id,
            side=side,
            bar_ts_utc=bar.ts_utc,
            reason=reason,
        )
