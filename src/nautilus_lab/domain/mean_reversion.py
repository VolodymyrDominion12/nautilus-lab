from __future__ import annotations

from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.regime import MarketRegime
from nautilus_lab.domain.signals import Signal, SignalSide
from nautilus_lab.domain.windows import RollingWindow


class RangeMeanReversion:
    """Bollinger mean reversion for ranging markets. Closed bars only."""

    def __init__(self, *, instrument_id: str, period: int, band_k: Decimal) -> None:
        self._instrument_id = instrument_id
        self._closes = RollingWindow(period)
        self._band_k = band_k

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        self._closes.push(bar.close)
        if not self._closes.full:
            return None
        mean, stdev = _mean_stdev(self._closes.values())
        if stdev == 0:
            return Signal(
                instrument_id=self._instrument_id,
                side=SignalSide.FLAT,
                bar_ts_utc=bar.ts_utc,
                reason="range stdev is 0",
                regime=MarketRegime.RANGE,
            )
        upper = mean + self._band_k * stdev
        lower = mean - self._band_k * stdev
        inner = Decimal("0.5") * self._band_k * stdev
        if bar.close <= lower:
            return Signal(
                instrument_id=self._instrument_id,
                side=SignalSide.BUY,
                bar_ts_utc=bar.ts_utc,
                reason="range lower band",
                regime=MarketRegime.RANGE,
            )
        if bar.close >= upper:
            return Signal(
                instrument_id=self._instrument_id,
                side=SignalSide.SELL,
                bar_ts_utc=bar.ts_utc,
                reason="range upper band",
                regime=MarketRegime.RANGE,
            )
        if abs(bar.close - mean) <= inner:
            return Signal(
                instrument_id=self._instrument_id,
                side=SignalSide.FLAT,
                bar_ts_utc=bar.ts_utc,
                reason="range mean revert complete",
                regime=MarketRegime.RANGE,
            )
        return None


def _mean_stdev(values: tuple[Decimal, ...]) -> tuple[Decimal, Decimal]:
    count = Decimal(len(values))
    mean = sum(values, Decimal("0")) / count
    if len(values) < 2:
        return mean, Decimal("0")
    variance = sum(((item - mean) ** 2 for item in values), Decimal("0")) / (count - 1)
    return mean, variance.sqrt()
