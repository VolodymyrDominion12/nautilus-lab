from __future__ import annotations

from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.windows import RollingWindow

MIN_HISTORY = 21


class FormulaicAlphaEngine:
    """WorldQuant-style formulaic features on closed OHLCV bars (no look-ahead)."""

    def __init__(self, *, history: int = 30) -> None:
        if history < MIN_HISTORY:
            raise ValueError(f"history must be >= {MIN_HISTORY}")
        self._history = history
        self._closes = RollingWindow(history + 1)
        self._highs = RollingWindow(history)
        self._lows = RollingWindow(history)
        self._volumes = RollingWindow(history)
        # Only the most recent `history` returns are ever read (`vol_10`, `vol_20`,
        # `vol_of_vol`), so the list is trimmed instead of growing for the whole run.
        self._returns: list[Decimal] = []

    @property
    def ready(self) -> bool:
        return self._closes.full and self._volumes.full

    def update(self, bar: OhlcvBar) -> tuple[Decimal, ...] | None:
        closes = self._closes.values()
        if closes:
            prev = closes[-1]
            if prev > 0:
                self._returns.append((bar.close - prev) / prev)
                if len(self._returns) > self._history:
                    del self._returns[0]
        self._closes.push(bar.close)
        self._highs.push(bar.high)
        self._lows.push(bar.low)
        self._volumes.push(bar.volume)
        if not self.ready:
            return None
        return self.features()

    def features(self) -> tuple[Decimal, ...]:
        closes = self._closes.values()
        volumes = self._volumes.values()
        highs = self._highs.values()
        lows = self._lows.values()
        ret = self._returns[-1] if self._returns else Decimal("0")
        ret_5 = _lagged_return(closes, 5)
        ret_10 = _lagged_return(closes, 10)
        vol_10 = _std(self._returns[-10:])
        vol_20 = _std(self._returns[-20:])
        mean_vol = sum(volumes, Decimal("0")) / Decimal(len(volumes))
        volume_ratio = volumes[-1] / mean_vol if mean_vol > 0 else Decimal("1")
        range_span = highs[-1] - lows[-1]
        close_loc = (closes[-1] - lows[-1]) / range_span if range_span > 0 else Decimal("0.5")
        momentum_10 = ret_10
        reversal_3 = -_lagged_return(closes, 3)
        vol_of_vol = _std([abs(item) for item in self._returns[-20:]])
        trend_er = _efficiency_ratio(closes[-21:])
        range_pct = range_span / closes[-1] if closes[-1] > 0 else Decimal("0")
        high_low_spread = (highs[-1] - lows[-1]) / closes[-1] if closes[-1] > 0 else Decimal("0")
        return (
            ret,
            ret_5,
            vol_10,
            volume_ratio,
            close_loc,
            momentum_10,
            reversal_3,
            vol_of_vol,
            trend_er,
            range_pct,
            high_low_spread,
            vol_20,
        )


def _lagged_return(closes: tuple[Decimal, ...], lag: int) -> Decimal:
    if len(closes) <= lag:
        return Decimal("0")
    base = closes[-lag - 1]
    if base <= 0:
        return Decimal("0")
    return (closes[-1] - base) / base


def _efficiency_ratio(closes: tuple[Decimal, ...]) -> Decimal:
    if len(closes) < 2:
        return Decimal("0")
    net = abs(closes[-1] - closes[0])
    path = sum(
        (abs(closes[index] - closes[index - 1]) for index in range(1, len(closes))),
        Decimal("0"),
    )
    if path == 0:
        return Decimal("0")
    return net / path


def _std(values: list[Decimal]) -> Decimal:
    if len(values) < 2:
        return Decimal("0")
    mean = sum(values, Decimal("0")) / Decimal(len(values))
    variance = sum((item - mean) ** 2 for item in values) / Decimal(len(values) - 1)
    return variance.sqrt()
