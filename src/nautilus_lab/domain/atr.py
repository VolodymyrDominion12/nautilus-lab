from __future__ import annotations

from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.windows import RollingWindow


class AverageTrueRange:
    """Wilder-style ATR on closed bars. No look-ahead."""

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("ATR period must be >= 1")
        self._period = period
        self._previous_close: Decimal | None = None
        self._trs = RollingWindow(period)
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
        self._trs.push(tr)
        if not self._trs.full:
            return None
        self._value = sum(self._trs.values(), Decimal("0")) / Decimal(self._period)
        return self._value
