from __future__ import annotations

from datetime import datetime

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.decision_trace import (
    Stage,
    TraceStep,
    Verdict,
    pct_distance,
    step,
    warmup_step,
)
from nautilus_lab.domain.ema import ExponentialMovingAverage
from nautilus_lab.domain.regime import MarketRegime
from nautilus_lab.domain.signals import Signal, SignalSide
from nautilus_lab.domain.windows import RollingWindow


class UptrendBreakout:
    """Donchian breakout long with EMA trailing exit. For confirmed uptrends."""

    def __init__(self, *, instrument_id: str, channel_period: int, ema_period: int) -> None:
        self._instrument_id = instrument_id
        self._highs = RollingWindow(channel_period + 1)
        self._ema = ExponentialMovingAverage(ema_period)
        self._channel_period = channel_period
        self._ema_period = ema_period
        self._seen = 0
        self._trace: tuple[TraceStep, ...] = ()

    @property
    def last_trace(self) -> tuple[TraceStep, ...]:
        return self._trace

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        self._seen += 1
        self._ema.update(bar.close)
        self._highs.push(bar.high)
        if not self._highs.full or not self._ema.initialized:
            self._trace = (
                warmup_step(
                    "UptrendBreakout",
                    seen=self._seen,
                    required=max(self._channel_period + 1, self._ema_period),
                ),
            )
            return None
        prior_high = max(self._highs.prior())
        ema = self._ema.value
        if ema is None:
            self._trace = (warmup_step("UptrendBreakout", seen=self._seen),)
            return None
        values = {
            "close": bar.close,
            "prior_high": prior_high,
            "ema": ema,
            "dist_to_breakout_pct": pct_distance(bar.close, prior_high),
            "dist_to_ema_pct": pct_distance(bar.close, ema),
        }
        periods = {"channel_period": self._channel_period, "ema_period": self._ema_period}
        if bar.close > prior_high:
            self._trace = (
                step(
                    Stage.STRATEGY,
                    "UptrendBreakout",
                    Verdict.EMIT,
                    result="buy",
                    values=values,
                    thresholds=periods,
                    note="close above the prior channel high",
                ),
            )
            return _signal(
                self._instrument_id,
                SignalSide.BUY,
                bar.ts_utc,
                MarketRegime.UPTREND,
                "donchian breakout long",
            )
        if bar.close < ema:
            self._trace = (
                step(
                    Stage.STRATEGY,
                    "UptrendBreakout",
                    Verdict.EMIT,
                    result="flat",
                    values=values,
                    thresholds=periods,
                    note="close below the trailing EMA",
                ),
            )
            return _signal(
                self._instrument_id,
                SignalSide.FLAT,
                bar.ts_utc,
                MarketRegime.UPTREND,
                "uptrend EMA exit",
            )
        self._trace = (
            step(
                Stage.STRATEGY,
                "UptrendBreakout",
                Verdict.INFO,
                values=values,
                thresholds=periods,
                note="close inside the channel and above the EMA: hold",
            ),
        )
        return None


class DowntrendBreakout:
    """Donchian breakdown short with EMA trailing cover. For confirmed downtrends."""

    def __init__(self, *, instrument_id: str, channel_period: int, ema_period: int) -> None:
        self._instrument_id = instrument_id
        self._lows = RollingWindow(channel_period + 1)
        self._ema = ExponentialMovingAverage(ema_period)
        self._channel_period = channel_period
        self._ema_period = ema_period
        self._seen = 0
        self._trace: tuple[TraceStep, ...] = ()

    @property
    def last_trace(self) -> tuple[TraceStep, ...]:
        return self._trace

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        self._seen += 1
        self._ema.update(bar.close)
        self._lows.push(bar.low)
        if not self._lows.full or not self._ema.initialized:
            self._trace = (
                warmup_step(
                    "DowntrendBreakout",
                    seen=self._seen,
                    required=max(self._channel_period + 1, self._ema_period),
                ),
            )
            return None
        prior_low = min(self._lows.prior())
        ema = self._ema.value
        if ema is None:
            self._trace = (warmup_step("DowntrendBreakout", seen=self._seen),)
            return None
        values = {
            "close": bar.close,
            "prior_low": prior_low,
            "ema": ema,
            "dist_to_breakout_pct": pct_distance(bar.close, prior_low),
            "dist_to_ema_pct": pct_distance(bar.close, ema),
        }
        periods = {"channel_period": self._channel_period, "ema_period": self._ema_period}
        if bar.close < prior_low:
            self._trace = (
                step(
                    Stage.STRATEGY,
                    "DowntrendBreakout",
                    Verdict.EMIT,
                    result="sell",
                    values=values,
                    thresholds=periods,
                    note="close below the prior channel low",
                ),
            )
            return _signal(
                self._instrument_id,
                SignalSide.SELL,
                bar.ts_utc,
                MarketRegime.DOWNTREND,
                "donchian breakout short",
            )
        if bar.close > ema:
            self._trace = (
                step(
                    Stage.STRATEGY,
                    "DowntrendBreakout",
                    Verdict.EMIT,
                    result="flat",
                    values=values,
                    thresholds=periods,
                    note="close above the trailing EMA",
                ),
            )
            return _signal(
                self._instrument_id,
                SignalSide.FLAT,
                bar.ts_utc,
                MarketRegime.DOWNTREND,
                "downtrend EMA exit",
            )
        self._trace = (
            step(
                Stage.STRATEGY,
                "DowntrendBreakout",
                Verdict.INFO,
                values=values,
                thresholds=periods,
                note="close inside the channel and below the EMA: hold",
            ),
        )
        return None


def _signal(
    instrument_id: str,
    side: SignalSide,
    ts_utc: datetime,
    regime: MarketRegime,
    reason: str,
) -> Signal:
    return Signal(
        instrument_id=instrument_id,
        side=side,
        bar_ts_utc=ts_utc,
        reason=reason,
        regime=regime,
    )
