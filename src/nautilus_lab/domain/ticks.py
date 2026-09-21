from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AggTrade:
    """One Binance aggregated trade (aggTrades endpoint).

    Binance aggregates consecutive fills from the same taker order into a single
    row so that the series is compact without losing the direction of aggression.
    The `is_buyer_maker` flag identifies who is the passive side:

    - ``is_buyer_maker=True``  → the buyer is the maker → a sell taker hit the bid
      (aggressive sell / down-tick).
    - ``is_buyer_maker=False`` → the seller is the maker → a buy taker lifted the ask
      (aggressive buy / up-tick).

    Timestamps are UTC. Prices and quantities are ``Decimal`` so that arithmetic on
    them matches the precision Binance transmits, not a floating-point approximation.

    ``agg_id`` is Binance's monotonically-increasing aggregated trade ID. It is kept
    for deduplication and gap detection: if two consecutive fetches return the same
    ``agg_id``, the trade was already recorded. A gap in the sequence means the REST
    window returned trades out of order, which should not happen in practice but can
    be detected defensively.
    """

    instrument_id: str
    ts_utc: datetime
    agg_id: int
    price: str          # stored as str to preserve Binance's exact decimal representation
    qty: str            # same: lossy float → Decimal(str(row["q"])) at the call site
    is_buyer_maker: bool

    @property
    def is_aggressive_buy(self) -> bool:
        """True when a taker lifted the ask (price-positive flow)."""
        return not self.is_buyer_maker

    @property
    def is_aggressive_sell(self) -> bool:
        """True when a taker hit the bid (price-negative flow)."""
        return self.is_buyer_maker
