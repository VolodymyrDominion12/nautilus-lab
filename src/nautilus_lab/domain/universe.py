"""Point-in-time trading universe: which coins a strategy may hold on a given day.

A fixed list of today's large coins is a survivorship-biased universe: it contains
only the winners and never the coins that were large in 2021 and are gone now
(docs/34, B2). The universe here is rebuilt from the data itself on every date:
the top-N by trailing dollar volume among the coins that *existed and traded* then.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar

#: Bases that are not a directional bet on a crypto asset: stablecoins and fiat.
STABLE_OR_FIAT_BASES = frozenset(
    {
        "USDC",
        "BUSD",
        "TUSD",
        "USDP",
        "PAX",
        "DAI",
        "FDUSD",
        "USDS",
        "USDSB",
        "SUSD",
        "UST",
        "USTC",
        "USDD",
        "USDE",
        "PYUSD",
        "AEUR",
        "EUR",
        "EURI",
        "GBP",
        "AUD",
        "BIDR",
        "IDRT",
        "TRY",
        "BRL",
        "RUB",
        "UAH",
        "NGN",
        "ZAR",
        "BKRW",
    }
)
#: Binance leveraged tokens: rebalancing products, not the underlying.
_LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")
#: Real coins whose ticker happens to end like a leveraged token.
_LEVERAGED_FALSE_POSITIVES = frozenset({"JUP", "SUP", "PUP", "CUP"})


def base_of(symbol: str, quote: str = "USDT") -> str | None:
    """`BTCUSDT` -> `BTC`; None when the symbol is not quoted in `quote`."""
    clean = symbol.upper().removesuffix("-PERP")
    if not clean.endswith(quote) or clean == quote:
        return None
    return clean[: -len(quote)]


def is_tradeable_base(base: str) -> bool:
    """True for a crypto asset; False for stablecoins, fiat and leveraged tokens."""
    upper = base.upper()
    if upper in STABLE_OR_FIAT_BASES:
        return False
    if upper in _LEVERAGED_FALSE_POSITIVES:
        return True
    return not any(
        upper.endswith(suffix) and len(upper) > len(suffix) for suffix in _LEVERAGED_SUFFIXES
    )


def candidate_symbols(symbols: Sequence[str], quote: str = "USDT") -> list[str]:
    """Archive symbols worth ingesting: `*USDT`, crypto bases only, sorted."""
    out: list[str] = []
    for symbol in symbols:
        base = base_of(symbol, quote)
        if base is not None and is_tradeable_base(base):
            out.append(symbol.upper())
    return sorted(set(out))


def top_by_dollar_volume(
    series: Mapping[str, Sequence[OhlcvBar]],
    *,
    as_of: datetime,
    lookback: timedelta = timedelta(days=30),
    n: int = 30,
    min_bars: int = 20,
) -> list[str]:
    """Top-`n` symbols by trailing dollar volume over `(as_of - lookback, as_of]`.

    Point in time: only bars that closed at or before `as_of` count, so the answer for
    2021-05-01 never knows which coins survived to 2026. A symbol needs `min_bars`
    bars in the lookback (a listing two days ago is not yet a liquid market).
    Dollar volume is `close * volume` per bar — an approximation of quote volume that
    needs nothing beyond the bars the catalog already stores.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    start = as_of - lookback
    scored: list[tuple[Decimal, str]] = []
    for symbol, bars in series.items():
        window = [bar for bar in bars if start < bar.ts_utc <= as_of]
        if len(window) < min_bars:
            continue
        total = sum((bar.close * bar.volume for bar in window), Decimal("0"))
        if total > 0:
            scored.append((total, symbol))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [symbol for _total, symbol in scored[:n]]
