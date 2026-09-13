from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from nautilus_lab.domain.signals import QuoteIntent


@dataclass(frozen=True, slots=True)
class GlftParams:
    gamma: Decimal = Decimal("0.1")
    kappa: Decimal = Decimal("1.5")
    base_half_spread_bps: Decimal = Decimal("5")


class GlftMarketMaker:
    """Guéant-Lehalle-Fernandez-Tapia quotes with inventory skew."""

    def __init__(self, *, instrument_id: str, params: GlftParams) -> None:
        self._instrument_id = instrument_id
        self._params = params

    def quote(
        self,
        *,
        mid: Decimal,
        inventory: Decimal,
        volatility: Decimal,
        ts_utc: datetime,
    ) -> QuoteIntent:
        half_spread = mid * self._params.base_half_spread_bps / Decimal("10000")
        half_spread += self._params.gamma * volatility * volatility
        skew = self._params.gamma * inventory
        reservation = mid - skew
        bid = reservation - half_spread
        ask = reservation + half_spread
        return QuoteIntent(
            instrument_id=self._instrument_id,
            bar_ts_utc=ts_utc,
            bid_price=bid,
            ask_price=ask,
            reason="glft",
        )
