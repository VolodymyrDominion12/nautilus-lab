from __future__ import annotations

from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.windows import RollingWindow


class AverageTrueRange:
    """Wilder's ATR on closed bars. No look-ahead.

    Seeded with the simple mean of the first `period` true ranges, then smoothed
    recursively as ``ATR_t = (ATR_{t-1} * (period - 1) + TR_t) / period``. That is
    Wilder's definition, and it is what the stop distance and the VPIN-momentum
    trailing stop assume: a smoothing that keeps the memory of a shock instead of a
    plain rolling mean, which drops the shock entirely after exactly `period` bars.
    """

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("ATR period must be >= 1")
        self._period = period
        self._previous_close: Decimal | None = None
        self._seed = RollingWindow(period)
        self._value: Decimal | None = None

    @property
    def initialized(self) -> bool:
        return self._value is not None

    @property
    def value(self) -> Decimal | None:
        return self._value

    def update(self, bar: OhlcvBar) -> Decimal | None:
        tr = bar.high - bar.low
        if self._previous_close is not None:
            tr = max(tr, abs(bar.high - self._previous_close), abs(bar.low - self._previous_close))
        self._previous_close = bar.close
        if self._value is None:
            self._seed.push(tr)
            if not self._seed.full:
                return None
            self._value = sum(self._seed.values(), Decimal("0")) / Decimal(self._period)
            return self._value
        previous_weight = Decimal(self._period - 1)
        self._value = (self._value * previous_weight + tr) / Decimal(self._period)
        return self._value
