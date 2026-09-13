from __future__ import annotations

from decimal import Decimal

from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Currency, Price, Quantity


def eth_usdt_sim() -> CurrencyPair:
    """Spot-like ETH/USDT on a simulated venue. No leverage on the instrument itself."""
    eth = Currency.from_str("ETH")
    usdt = Currency.from_str("USDT")
    return CurrencyPair(
        instrument_id=InstrumentId.from_str("ETH/USDT.SIM"),
        raw_symbol=Symbol("ETH/USDT"),
        base_currency=eth,
        quote_currency=usdt,
        price_precision=2,
        size_precision=3,
        price_increment=Price.from_str("0.01"),
        size_increment=Quantity.from_str("0.001"),
        ts_event=0,
        ts_init=0,
        lot_size=Quantity.from_str("0.001"),
        min_quantity=Quantity.from_str("0.001"),
        maker_fee=Decimal("0.0002"),
        taker_fee=Decimal("0.0005"),
    )
