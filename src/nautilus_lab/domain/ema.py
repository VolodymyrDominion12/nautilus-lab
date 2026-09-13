from __future__ import annotations

from decimal import Decimal


class ExponentialMovingAverage:
    """EMA seeded by SMA of the first `period` closed prices. No look-ahead."""

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self._period = period
        self._alpha = Decimal(2) / (Decimal(period) + Decimal(1))
        self._seed_sum = Decimal("0")
        self._count = 0
        self._value: Decimal | None = None

    @property
    def initialized(self) -> bool:
        return self._value is not None

    @property
    def value(self) -> Decimal | None:
        return self._value

    def update(self, price: Decimal) -> None:
        if price <= 0:
            raise ValueError("price must be > 0")
        if self._value is None:
            self._seed_sum += price
            self._count += 1
            if self._count == self._period:
                self._value = self._seed_sum / Decimal(self._period)
            return
        one = Decimal("1")
        self._value = (price * self._alpha) + (self._value * (one - self._alpha))
        self._count += 1
