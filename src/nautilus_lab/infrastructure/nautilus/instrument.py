from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

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
    "AVAX/USDT.SIM": ("AVAX", "USDT", 3, "0.001", "0.01"),
    "DOT/USDT.SIM": ("DOT", "USDT", 3, "0.001", "0.01"),
    "MATIC/USDT.SIM": ("MATIC", "USDT", 4, "0.0001", "0.1"),
    "LINK/USDT.SIM": ("LINK", "USDT", 3, "0.001", "0.01"),
}

_PERP_SPECS: dict[str, tuple[str, str, int, str, str]] = {
    "BTCUSDT-PERP.SIM": ("BTC", "USDT", 1, "0.1", "0.001"),
    "ETHUSDT-PERP.SIM": ("ETH", "USDT", 2, "0.01", "0.001"),
    "SOLUSDT-PERP.SIM": ("SOL", "USDT", 2, "0.01", "0.01"),
    "BNBUSDT-PERP.SIM": ("BNB", "USDT", 2, "0.01", "0.01"),
    "XRPUSDT-PERP.SIM": ("XRP", "USDT", 4, "0.0001", "0.1"),
    "ADAUSDT-PERP.SIM": ("ADA", "USDT", 4, "0.0001", "1"),
    "DOGEUSDT-PERP.SIM": ("DOGE", "USDT", 5, "0.00001", "1"),
    "AVAXUSDT-PERP.SIM": ("AVAX", "USDT", 3, "0.001", "1"),
    "DOTUSDT-PERP.SIM": ("DOT", "USDT", 3, "0.001", "0.1"),
    "MATICUSDT-PERP.SIM": ("MATIC", "USDT", 4, "0.0001", "1"),
    "LINKUSDT-PERP.SIM": ("LINK", "USDT", 3, "0.001", "0.01"),
}


# --- instrument registry -----------------------------------------------------------
#
# The two tables above are hand-checked against Binance filters and always win. Every
# other coin (the archive universe: hundreds of symbols, delisted ones included, for
# which `exchangeInfo` no longer answers) gets a spec *derived from its own data*: the
# finest price and size decimals that actually occur in its history. That precision
# can only be finer than or equal to the venue tick, so `to_engine_bars` never rounds
# a stored price — the failure the DOGE comment above describes.
#
# Specs persist in `data/instruments.json` (override with NAUTILUS_LAB_INSTRUMENTS), so
# a backtest process resolves the same instrument the ingest wrote.

_REGISTRY_ENV = "NAUTILUS_LAB_INSTRUMENTS"
_MAX_PRECISION = 8
_REPO_ROOT = Path(__file__).resolve().parents[4]
_registry_lock = threading.Lock()
_registry_cache: dict[str, dict[str, dict[str, object]]] = {}


def registry_path() -> Path:
    override = os.environ.get(_REGISTRY_ENV)
    if override:
        return Path(override).expanduser().resolve()
    root = _REPO_ROOT if (_REPO_ROOT / "pyproject.toml").exists() else Path.cwd()
    return root / "data" / "instruments.json"


def _load_registry(path: Path) -> dict[str, dict[str, object]]:
    key = str(path)
    cached = _registry_cache.get(key)
    if cached is not None:
        return cached
    loaded: dict[str, dict[str, object]] = {}
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            loaded = {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}
    _registry_cache[key] = loaded
    return loaded


def clear_registry_cache() -> None:
    """Forget loaded registries (tests; a long-lived API after an ingest)."""
    with _registry_lock:
        _registry_cache.clear()


def decimal_places(value: Decimal) -> int:
    """Significant decimals of a value: `Decimal("7195.24000000")` -> 2."""
    if not value.is_finite() or value == 0:
        return 0
    exponent = value.normalize().as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def infer_precision(values: Iterable[Decimal]) -> int:
    """The finest decimals any value needs, capped at the engine's 8."""
    return min(_MAX_PRECISION, max((decimal_places(value) for value in values), default=0))


def register_instrument(
    instrument_id: str,
    *,
    price_precision: int,
    size_precision: int,
    source: str,
    path: Path | None = None,
) -> bool:
    """Persist a derived spec. No-op for the hand-checked ids. Returns True if written.

    Precision only ever grows: a later ingest that sees a finer tick widens the spec,
    a coarser sample never narrows it (narrowing would round prices already stored).
    """
    if instrument_id in _SPOT_SPECS or instrument_id in _PERP_SPECS:
        return False
    base, quote = _split_instrument_id(instrument_id)
    target = path or registry_path()
    with _registry_lock:
        registry = dict(_load_registry(target))
        current = registry.get(instrument_id, {})
        price = max(price_precision, _as_int(current.get("price_precision")))
        size = max(size_precision, _as_int(current.get("size_precision")))
        entry: dict[str, object] = {
            "base": base,
            "quote": quote,
            "price_precision": min(price, _MAX_PRECISION),
            "size_precision": min(size, _MAX_PRECISION),
            "source": source,
        }
        if current == entry:
            return False
        registry[instrument_id] = entry
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(json.dumps(registry, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, target)
        _registry_cache[str(target)] = registry
        return True


def _as_int(value: object) -> int:
    return int(value) if isinstance(value, int | str) and str(value).isdigit() else 0


def _split_instrument_id(instrument_id: str) -> tuple[str, str]:
    """`SOL/USDT.SIM` -> (SOL, USDT); `SOLUSDT-PERP.SIM` -> (SOL, USDT)."""
    symbol = instrument_id.removesuffix(".SIM")
    if "/" in symbol:
        base, quote = symbol.split("/", 1)
        return base, quote
    clean = symbol.removesuffix("-PERP")
    for quote in ("USDT", "USDC", "BUSD"):
        if clean.endswith(quote) and len(clean) > len(quote):
            return clean[: -len(quote)], quote
    raise ValueError(f"cannot split instrument id into base/quote: {instrument_id}")


def _increment(precision: int) -> str:
    return "1" if precision == 0 else f"0.{'0' * (precision - 1)}1"


def _registered_spec(
    instrument_id: str, path: Path | None = None
) -> tuple[str, str, int, str, str] | None:
    entry = _load_registry(path or registry_path()).get(instrument_id)
    if entry is None:
        return None
    price = _as_int(entry.get("price_precision"))
    size = _as_int(entry.get("size_precision"))
    return (str(entry["base"]), str(entry["quote"]), price, _increment(price), _increment(size))


def supported_instrument_ids() -> tuple[str, ...]:
    """Every instrument id `resolve_instrument` accepts, sorted.

    Public on purpose: the error message and the invariant test both need the list,
    and a second copy of it would be the thing that goes stale. These are the
    hand-checked ids; `registered_instrument_ids` lists the ones derived from data.
    """
    return tuple(sorted((*_SPOT_SPECS, *_PERP_SPECS)))


def registered_instrument_ids(path: Path | None = None) -> tuple[str, ...]:
    """Ids whose spec was derived from their own history by an archive ingest."""
    return tuple(sorted(_load_registry(path or registry_path())))


def resolve_instrument(
    instrument_id: str,
    *,
    spot_fees: FeeSchedule | None = None,
    usdm_fees: FeeSchedule | None = None,
) -> CurrencyPair | CryptoPerpetual:
    if instrument_id in _PERP_SPECS:
        return _crypto_perpetual(instrument_id, fees=usdm_fees or FeeSchedule.binance_usdm_vip0())
    if instrument_id in _SPOT_SPECS:
        return _currency_pair(instrument_id, fees=spot_fees or FeeSchedule.binance_spot_vip0())
    registered = _registered_spec(instrument_id)
    if registered is not None:
        if instrument_id.endswith("-PERP.SIM"):
            return _crypto_perpetual(
                instrument_id,
                fees=usdm_fees or FeeSchedule.binance_usdm_vip0(),
                spec=registered,
            )
        return _currency_pair(
            instrument_id,
            fees=spot_fees or FeeSchedule.binance_spot_vip0(),
            spec=registered,
        )
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
    if symbol.endswith("-PERP"):
        return f"{symbol}.SIM"
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
    if instrument_id.endswith("-PERP.SIM"):
        return instrument_id.removesuffix(".SIM")
    base, separator, quote = instrument_id.partition("/")
    if not separator or not quote.startswith("USDT"):
        return None
    return f"{base}USDT"


def _currency_pair(
    instrument_id: str,
    *,
    fees: FeeSchedule,
    spec: tuple[str, str, int, str, str] | None = None,
) -> CurrencyPair:
    base_code, quote_code, price_precision, price_inc, size_inc = spec or _SPOT_SPECS[instrument_id]
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


def _crypto_perpetual(
    instrument_id: str,
    *,
    fees: FeeSchedule,
    spec: tuple[str, str, int, str, str] | None = None,
) -> CryptoPerpetual:
    base_code, quote_code, price_precision, price_inc, size_inc = spec or _PERP_SPECS[instrument_id]
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
        # Hand-checked ids keep the bound they always had; derived ones include coins
        # priced in fractions of a cent, where a normal position is billions of units.
        max_quantity=Quantity.from_str("1000000" if spec is None else "1000000000000"),
        min_quantity=Quantity.from_str(size_inc),
        max_price=Price.from_str("1000000"),
        min_price=Price.from_str(price_inc),
        margin_init=Decimal("0.01"),
        margin_maint=Decimal("0.005"),
        maker_fee=fees.maker,
        taker_fee=fees.taker,
        ts_event=0,
        ts_init=0,
    )
