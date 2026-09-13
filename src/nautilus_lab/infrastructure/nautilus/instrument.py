from __future__ import annotations

from decimal import Decimal

from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.instruments import CryptoPerpetual, CurrencyPair
from nautilus_trader.model.objects import Currency, Price, Quantity

from nautilus_lab.domain.fees import FeeSchedule

_SPOT_SPECS: dict[str, tuple[str, str, int, str, str]] = {
    "ETH/USDT.SIM": ("ETH", "USDT", 2, "0.01", "0.001"),
    "BTC/USDT.SIM": ("BTC", "USDT", 2, "0.01", "0.00001"),
}

_PERP_SPECS: dict[str, tuple[str, str, int, str, str]] = {
    "ETHUSDT-PERP.SIM": ("ETH", "USDT", 2, "0.01", "0.001"),
}


def resolve_instrument(
    instrument_id: str, *, fees: FeeSchedule | None = None
) -> CurrencyPair | CryptoPerpetual:
    schedule = fees or FeeSchedule.binance_spot_vip0()
    if instrument_id in _PERP_SPECS:
        return _crypto_perpetual(instrument_id, fees=schedule)
    if instrument_id in _SPOT_SPECS:
        return _currency_pair(instrument_id, fees=schedule)
    raise ValueError(f"unsupported instrument_id: {instrument_id}")


def eth_usdt_sim(*, fees: FeeSchedule | None = None) -> CurrencyPair:
    return _currency_pair("ETH/USDT.SIM", fees=fees or FeeSchedule.binance_spot_vip0())


def btc_usdt_sim(*, fees: FeeSchedule | None = None) -> CurrencyPair:
    return _currency_pair("BTC/USDT.SIM", fees=fees or FeeSchedule.binance_spot_vip0())


def eth_usdt_perp_sim(*, fees: FeeSchedule | None = None) -> CryptoPerpetual:
    return _crypto_perpetual(
        "ETHUSDT-PERP.SIM",
        fees=fees or FeeSchedule.binance_usdm_vip0(),
    )


def binance_symbol_to_instrument_id(symbol: str) -> str:
    if symbol.endswith("USDT"):
        base = symbol.removesuffix("USDT")
        return f"{base}/USDT.SIM"
    raise ValueError(f"unsupported binance symbol: {symbol}")


def _currency_pair(instrument_id: str, *, fees: FeeSchedule) -> CurrencyPair:
    base_code, quote_code, price_precision, price_inc, size_inc = _SPOT_SPECS[instrument_id]
    base = Currency.from_str(base_code)
    quote = Currency.from_str(quote_code)
    return CurrencyPair(
        instrument_id=InstrumentId.from_str(instrument_id),
        raw_symbol=Symbol(f"{base_code}/{quote_code}"),
        base_currency=base,
        quote_currency=quote,
        price_precision=price_precision,
        size_precision=len(size_inc.split(".")[-1]) if "." in size_inc else 0,
        price_increment=Price.from_str(price_inc),
        size_increment=Quantity.from_str(size_inc),
        ts_event=0,
        ts_init=0,
        lot_size=Quantity.from_str(size_inc),
        min_quantity=Quantity.from_str(size_inc),
        maker_fee=fees.maker,
        taker_fee=fees.taker,
    )


def _crypto_perpetual(instrument_id: str, *, fees: FeeSchedule) -> CryptoPerpetual:
    base_code, quote_code, price_precision, price_inc, size_inc = _PERP_SPECS[instrument_id]
    base = Currency.from_str(base_code)
    quote = Currency.from_str(quote_code)
    return CryptoPerpetual(
        instrument_id=InstrumentId.from_str(instrument_id),
        raw_symbol=Symbol(f"{base_code}{quote_code}-PERP"),
        base_currency=base,
        quote_currency=quote,
        settlement_currency=quote,
        is_inverse=False,
        price_precision=price_precision,
        size_precision=len(size_inc.split(".")[-1]) if "." in size_inc else 0,
        price_increment=Price.from_str(price_inc),
        size_increment=Quantity.from_str(size_inc),
        multiplier=Quantity.from_str("1"),
        lot_size=Quantity.from_str(size_inc),
        max_quantity=Quantity.from_str("1000000"),
        min_quantity=Quantity.from_str(size_inc),
        max_price=Price.from_str("1000000"),
        min_price=Price.from_str("0.01"),
        margin_init=Decimal("0.01"),
        margin_maint=Decimal("0.005"),
        maker_fee=fees.maker,
        taker_fee=fees.taker,
        ts_event=0,
        ts_init=0,
    )
