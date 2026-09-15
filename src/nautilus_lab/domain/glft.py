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
    """Simplified Avellaneda-Stoikov / GLFT quotes with inventory skew.

    Units: `mid`, `volatility` and the returned prices are all in quote currency
    (USDT), and `inventory` is in base units. `volatility` is the per-bar price
    standard deviation, **not** a relative return — passing a return (0.02) makes
    the variance term vanish against a mid of thousands.

    The full GLFT half-spread also carries a `(1/gamma)*ln(1 + gamma/kappa)`
    liquidity term; `base_half_spread_bps` stands in for it here.
    """

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
        variance = volatility * volatility
        half_spread = mid * self._params.base_half_spread_bps / Decimal("10000")
        half_spread += self._params.gamma * variance
        # Reservation price r = mid - q*gamma*sigma^2. Shape risk scales with the
        # *variance* of the mid, exactly like the spread term; an un-scaled
        # `gamma*inventory` skew would move with a parameter that the spread ignores.
        reservation = mid - self._params.gamma * variance * inventory
        bid = reservation - half_spread
        ask = reservation + half_spread
        return QuoteIntent(
            instrument_id=self._instrument_id,
            bar_ts_utc=ts_utc,
            bid_price=bid,
            ask_price=ask,
            reason="glft",
        )
