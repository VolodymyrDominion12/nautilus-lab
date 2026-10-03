from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PremiumIndexBar:
    """One closed candle of the Binance USD-M premium index.

    The premium index measures the basis between the perpetual futures mark price
    and the underlying spot/index price: `(mark - index) / index`.
    """

    symbol: str
    interval: str
    ts_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
