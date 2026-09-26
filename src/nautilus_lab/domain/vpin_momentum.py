from __future__ import annotations

from decimal import Decimal

from nautilus_lab.domain.atr import AverageTrueRange
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
from nautilus_lab.domain.vpin import VpinModel, VpinState


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
        self._last_vpin_state: VpinState | None = None
        self._last_atr: Decimal | None = None
        self._last_ema_value: Decimal | None = None
        self._ema_period = ema_period
        self._atr_period = atr_period
        self._seen = 0
        self._trace: tuple[TraceStep, ...] = ()

    @property
    def last_trace(self) -> tuple[TraceStep, ...]:
        return self._trace

    @property
    def last_vpin_state(self) -> VpinState | None:
        return self._last_vpin_state

    @property
    def last_atr(self) -> Decimal | None:
        return self._last_atr

    @property
    def last_ema_value(self) -> Decimal | None:
        return self._last_ema_value

    def on_trade_tick(self, *, is_buy: bool, volume: Decimal, dt_seconds: Decimal) -> None:
        if self._vpin is not None and hasattr(self._vpin, "update_from_trade"):
            self._vpin.update_from_trade(is_buy=is_buy, volume=volume)

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        self._seen += 1
        self._last_vpin_state = self._vpin.update(bar)
        self._ema.update(bar.close)
        self._atr.update(bar)
        ema = self._ema.value
        atr = self._atr.value
        self._last_ema_value = ema
        self._last_atr = atr
        if ema is None or atr is None:
            self._trace = (
                warmup_step(
                    "VpinMomentum",
                    seen=self._seen,
                    required=max(self._ema_period, self._atr_period + 1),
                ),
            )
            return None
        vpin = self._vpin_step()

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
            values = {
                "close": bar.close,
                "ema": ema,
                "atr": atr,
                "trail_stop": stop,
                "extreme": self._extreme,
                "direction": "long" if self._direction > 0 else "short",
                "bars_in_position": self._bars_in_position,
                "dist_to_stop_pct": pct_distance(bar.close, stop),
            }
            thresholds: dict[str, TraceValue] = {
                "atr_multiple": self._atr_multiple,
                "min_hold_bars": self._min_hold_bars,
            }
            if can_exit and (hit_stop or lost_momentum):
                self._trace = (
                    vpin,
                    step(
                        Stage.STRATEGY,
                        "VpinMomentum",
                        Verdict.EMIT,
                        result="flat",
                        values=values,
                        thresholds=thresholds,
                        note=(
                            "close crossed the EMA: momentum lost"
                            if lost_momentum
                            else "close hit the ATR trailing stop"
                        ),
                    ),
                )
                self._reset()
                return self._signal(
                    bar,
                    SignalSide.FLAT,
                    "vpin momentum exit" if lost_momentum else "vpin atr stop",
                )
            self._trace = (
                vpin,
                step(
                    Stage.STRATEGY,
                    "VpinMomentum",
                    Verdict.INFO,
                    values=values,
                    thresholds=thresholds,
                    note=(
                        "exit condition met but minimum hold not reached"
                        if (hit_stop or lost_momentum)
                        else "trend intact: hold"
                    ),
                ),
            )
            return None

        entry_values = {
            "close": bar.close,
            "ema": ema,
            "atr": atr,
            "dist_to_ema_pct": pct_distance(bar.close, ema),
        }
        if self._last_vpin_state is None or not self._last_vpin_state.toxic:
            self._trace = (
                vpin,
                step(
                    Stage.STRATEGY,
                    "VpinMomentum",
                    Verdict.INFO,
                    values=entry_values,
                    note="flow is not toxic: no informed-flow entry",
                ),
            )
            return None
        if bar.close > ema:
            self._trace = (
                vpin,
                step(
                    Stage.STRATEGY,
                    "VpinMomentum",
                    Verdict.EMIT,
                    result="buy",
                    values=entry_values,
                    note="toxic flow with close above EMA",
                ),
            )
            self._enter(direction=1, bar=bar)
            reason = f"toxic flow up vpin={self._last_vpin_state.value}"
            return self._signal(bar, SignalSide.BUY, reason)
        if bar.close < ema:
            self._trace = (
                vpin,
                step(
                    Stage.STRATEGY,
                    "VpinMomentum",
                    Verdict.EMIT,
                    result="sell",
                    values=entry_values,
                    note="toxic flow with close below EMA",
                ),
            )
            self._enter(direction=-1, bar=bar)
            reason = f"toxic flow down vpin={self._last_vpin_state.value}"
            return self._signal(bar, SignalSide.SELL, reason)
        self._trace = (
            vpin,
            step(
                Stage.STRATEGY,
                "VpinMomentum",
                Verdict.INFO,
                values=entry_values,
                note="toxic flow but close equals EMA: no direction",
            ),
        )
        return None

    def _vpin_step(self) -> TraceStep:
        state = self._last_vpin_state
        if state is None:
            return step(Stage.FILTER, "vpin", Verdict.SKIP, note="bucket not filled yet")
        return step(
            Stage.FILTER,
            "vpin",
            Verdict.PASS if state.toxic else Verdict.INFO,
            result="toxic" if state.toxic else "normal",
            values={"vpin": state.value, "bucket_filled": state.bucket_filled},
        )

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
