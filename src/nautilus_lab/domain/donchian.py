from __future__ import annotations

from datetime import datetime

from nautilus_lab.domain.bars import OhlcvBar
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

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        self._ema.update(bar.close)
        self._highs.push(bar.high)
        if not self._highs.full or not self._ema.initialized:
            return None
        prior_high = max(self._highs.prior())
        ema = self._ema.value
        if ema is None:
            return None
        if bar.close > prior_high:
            return _signal(
                self._instrument_id,
                SignalSide.BUY,
                bar.ts_utc,
                MarketRegime.UPTREND,
                "donchian breakout long",
            )
        if bar.close < ema:
            return _signal(
                self._instrument_id,
                SignalSide.FLAT,
                bar.ts_utc,
                MarketRegime.UPTREND,
                "uptrend EMA exit",
            )
        return None


class DowntrendBreakout:
    """Donchian breakdown short with EMA trailing cover. For confirmed downtrends."""

    def __init__(self, *, instrument_id: str, channel_period: int, ema_period: int) -> None:
        self._instrument_id = instrument_id
        self._lows = RollingWindow(channel_period + 1)
        self._ema = ExponentialMovingAverage(ema_period)

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        self._ema.update(bar.close)
        self._lows.push(bar.low)
        if not self._lows.full or not self._ema.initialized:
            return None
        prior_low = min(self._lows.prior())
        ema = self._ema.value
        if ema is None:
            return None
        if bar.close < prior_low:
            return _signal(
                self._instrument_id,
                SignalSide.SELL,
                bar.ts_utc,
                MarketRegime.DOWNTREND,
                "donchian breakout short",
            )
        if bar.close > ema:
            return _signal(
                self._instrument_id,
                SignalSide.FLAT,
                bar.ts_utc,
                MarketRegime.DOWNTREND,
                "downtrend EMA exit",
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
