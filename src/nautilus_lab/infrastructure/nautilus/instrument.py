from __future__ import annotations

from decimal import Decimal

from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.instruments import CryptoPerpetual, CurrencyPair
from nautilus_trader.model.objects import Currency, Price, Quantity

from nautilus_lab.domain.fees import FeeSchedule

# (base, quote, price_precision, price_increment, size_increment).
#
# `price_precision` is not cosmetic: `to_engine_bars` builds every OHLC value as
# `Price(value, precision=instrument.price_precision)`, so a tick coarser than the
# venue's silently rewrites the series the backtest reads (DOGE at precision 2
# turns 0.12345 into 0.12). The five entries below ETH/BTC therefore carry the real
# Binance spot filters (`api/v3/exchangeInfo`: PRICE_FILTER.tickSize and
# LOT_SIZE.stepSize), not a house default.
#
# ETH/BTC keep the increments this lab has always simulated with. ETH's 0.001 is
# coarser than Binance's real 0.0001, i.e. conservative, but making it "accurate"
# would change `size_precision` and with it the stored volume of every already
# ingested ETH/BTC bar — a different series for results that were already reported.
# That is a deliberate trade, not an oversight: change it only together with a
# re-ingest and a re-run.
_SPOT_SPECS: dict[str, tuple[str, str, int, str, str]] = {
    "ETH/USDT.SIM": ("ETH", "USDT", 2, "0.01", "0.001"),
    "BTC/USDT.SIM": ("BTC", "USDT", 2, "0.01", "0.00001"),
    "SOL/USDT.SIM": ("SOL", "USDT", 2, "0.01", "0.001"),
    "BNB/USDT.SIM": ("BNB", "USDT", 2, "0.01", "0.001"),
    "XRP/USDT.SIM": ("XRP", "USDT", 4, "0.0001", "0.1"),
    "ADA/USDT.SIM": ("ADA", "USDT", 4, "0.0001", "0.1"),
    "DOGE/USDT.SIM": ("DOGE", "USDT", 5, "0.00001", "1"),
}

_PERP_SPECS: dict[str, tuple[str, str, int, str, str]] = {
    "ETHUSDT-PERP.SIM": ("ETH", "USDT", 2, "0.01", "0.001"),
}


def supported_instrument_ids() -> tuple[str, ...]:
    """Every instrument id `resolve_instrument` accepts, sorted.

    Public on purpose: the error message and the invariant test both need the list,
    and a second copy of it would be the thing that goes stale.
    """
    return tuple(sorted((*_SPOT_SPECS, *_PERP_SPECS)))


def resolve_instrument(
    instrument_id: str, *, fees: FeeSchedule | None = None
) -> CurrencyPair | CryptoPerpetual:
    schedule = fees or FeeSchedule.binance_spot_vip0()
    if instrument_id in _PERP_SPECS:
        return _crypto_perpetual(instrument_id, fees=schedule)
    if instrument_id in _SPOT_SPECS:
        return _currency_pair(instrument_id, fees=schedule)
    # Fail closed, but name the open doors: the symbol->instrument_id step accepts
    # any `*USDT` ticker, so without this list the message arrives one layer away
    # from the cause ("unsupported instrument_id: SOL/USDT.SIM" while the user asked
    # for SOLUSDT). Supported ids are spelled out for the same reason docs/11 keeps
    # the table: adding one is a code change, never a silent default.
    supported = ", ".join(supported_instrument_ids())
    raise ValueError(f"unsupported instrument_id: {instrument_id}; supported: {supported}")


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


def binance_symbol_for_instrument(instrument_id: str) -> str | None:
    """Inverse of `binance_symbol_to_instrument_id` for the spot ids in the table.

    Returns None when the instrument has no spot symbol to look data up under (the
    perpetual ids carry no `/`, so they are not derivable this way). None is the honest
    answer: the caller then has no taker-flow series to join and falls back, instead of
    inventing a symbol and silently reading the wrong instrument's flow.
    """
    base, separator, quote = instrument_id.partition("/")
    if not separator or not quote.startswith("USDT"):
        return None
    return f"{base}USDT"


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
