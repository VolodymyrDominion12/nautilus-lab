from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class BookLevel:
    price: Decimal
    size: Decimal


@dataclass(frozen=True, slots=True)
class OrderBookSnapshot:
    instrument_id: str
    ts_utc: datetime
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]

    def validate(self) -> None:
        if not self.bids or not self.asks:
            raise ValueError("book must have bids and asks")
        if self.bids[0].price >= self.asks[0].price:
            raise ValueError("crossed book")
        for index in range(1, len(self.bids)):
            if self.bids[index].price > self.bids[index - 1].price:
                raise ValueError("bids must be descending")
        for index in range(1, len(self.asks)):
            if self.asks[index].price < self.asks[index - 1].price:
                raise ValueError("asks must be ascending")
