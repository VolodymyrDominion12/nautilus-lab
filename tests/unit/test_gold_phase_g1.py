"""Unit tests for Phase G1 gold trading support (Track A: Binance Gold)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import TracebackType

import pytest
from nautilus_trader.model.instruments import CryptoPerpetual, CurrencyPair

from nautilus_lab.api.market_feed import MarketFeed, feed_key
from nautilus_lab.domain.funding import FundingSnapshot
from nautilus_lab.domain.stress_slices import StressSliceName, resolve_stress_slice
from nautilus_lab.domain.universe import (
    METAL_BASES,
    candidate_symbols,
    is_tradeable_base,
    metal_symbols,
)
from nautilus_lab.infrastructure.binance_ws import (
    BINANCE_FAPI_WS_BASE_URL,
    BINANCE_WS_BASE_URL,
    BinanceAggTradeStream,
    BinanceKlineStream,
    SocketLike,
    agg_trade_stream_url,
    binance_stream_url,
)
from nautilus_lab.infrastructure.nautilus.backtest_runner import _infer_funding_interval_minutes
from nautilus_lab.infrastructure.nautilus.instrument import (
    binance_symbol_to_instrument_id,
    resolve_instrument,
)


class _ScriptedSocket:
    """Minimal in-memory socket implementing `SocketLike` without opening a network connection."""

    def __init__(self, frames: list[str], on_empty: object | None = None) -> None:
        self._frames = list(frames)
        self._on_empty = on_empty

    def __enter__(self) -> _ScriptedSocket:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def recv(self) -> str:
        if not self._frames:
            if callable(self._on_empty):
                self._on_empty()
            raise OSError("scripted socket exhausted")
        return self._frames.pop(0)

    def close(self) -> None:
        return None


def test_gold_binance_specs_and_xau_spot_fail_closed() -> None:
    """Verified Binance gold/silver spot and USD-M perp specs resolve; XAU/XAG spot fail closed."""
    for symbol, expected_id in (
        ("PAXGUSDT", "PAXG/USDT.SIM"),
        ("XAUTUSDT", "XAUT/USDT.SIM"),
    ):
        instrument_id = binance_symbol_to_instrument_id(symbol)
        assert instrument_id == expected_id
        instrument = resolve_instrument(instrument_id)
        assert isinstance(instrument, CurrencyPair)
        assert instrument.price_increment.as_decimal() == Decimal("0.01")
        assert instrument.size_increment.as_decimal() == Decimal("0.0001")

    for symbol, expected_id in (
        ("PAXGUSDT-PERP", "PAXGUSDT-PERP.SIM"),
        ("XAUTUSDT-PERP", "XAUTUSDT-PERP.SIM"),
        ("XAUUSDT-PERP", "XAUUSDT-PERP.SIM"),
        ("XAGUSDT-PERP", "XAGUSDT-PERP.SIM"),
    ):
        instrument_id = binance_symbol_to_instrument_id(symbol)
        assert instrument_id == expected_id
        instrument = resolve_instrument(instrument_id)
        assert isinstance(instrument, CryptoPerpetual)
        assert instrument.price_increment.as_decimal() == Decimal("0.01")
        assert instrument.size_increment.as_decimal() == Decimal("0.001")

    # `binance_symbol_to_instrument_id` formats any `*USDT` ticker, while `resolve_instrument`
    # is the fail-closed gate: Binance lists XAUUSDT/XAGUSDT only as USD-M TradFi perps.
    for unsupported_spot in ("XAUUSDT", "XAGUSDT"):
        spot_id = binance_symbol_to_instrument_id(unsupported_spot)
        with pytest.raises(ValueError, match="unsupported instrument_id"):
            resolve_instrument(spot_id)


def test_perp_symbol_routes_to_fstream_ws() -> None:
    """`-PERP` symbols route to Binance USD-M `fstream` WS and keep closed-bar + perp labelling."""
    assert binance_stream_url("XAUUSDT-PERP", "1h") == (
        f"{BINANCE_FAPI_WS_BASE_URL}/xauusdt@kline_1h"
    )
    assert binance_stream_url("PAXGUSDT", "1h") == (f"{BINANCE_WS_BASE_URL}/paxgusdt@kline_1h")
    assert agg_trade_stream_url("XAUUSDT-PERP") == (f"{BINANCE_FAPI_WS_BASE_URL}/xauusdt@aggTrade")
    assert agg_trade_stream_url("PAXGUSDT") == (f"{BINANCE_WS_BASE_URL}/paxgusdt@aggTrade")

    def _unused_connect(url: str) -> object:
        raise AssertionError(f"unexpected connect to {url}")

    assert MarketFeed(feed_key("XAUUSDT-PERP", "1h"), connect=_unused_connect).url == (  # type: ignore[arg-type]
        f"{BINANCE_FAPI_WS_BASE_URL}/xauusdt@kline_1h"
    )
    assert MarketFeed(feed_key("PAXGUSDT", "1h"), connect=_unused_connect).url == (  # type: ignore[arg-type]
        f"{BINANCE_WS_BASE_URL}/paxgusdt@kline_1h"
    )

    open_ms = 1_769_904_000_000
    close_ms = 1_769_907_599_999
    now = datetime(2026, 2, 1, 2, 0, tzinfo=UTC)
    open_frame = json.dumps(
        {
            "e": "kline",
            "E": close_ms - 5_000,
            "s": "XAUUSDT",
            "k": {
                "t": open_ms,
                "T": close_ms,
                "s": "XAUUSDT",
                "i": "1h",
                "o": "4850.10",
                "h": "4860.00",
                "l": "4845.00",
                "c": "4855.50",
                "v": "120.500",
                "V": "70.250",
                "x": False,
            },
        }
    )
    closed_frame = json.dumps(
        {
            "e": "kline",
            "E": close_ms,
            "s": "XAUUSDT",
            "k": {
                "t": open_ms,
                "T": close_ms,
                "s": "XAUUSDT",
                "i": "1h",
                "o": "4850.10",
                "h": "4865.00",
                "l": "4845.00",
                "c": "4862.25",
                "v": "250.500",
                "V": "140.250",
                "x": True,
            },
        }
    )

    seen_urls: list[str] = []
    stream_ref: list[BinanceKlineStream] = []

    def fake_connect(url: str) -> SocketLike:
        seen_urls.append(url)
        return _ScriptedSocket(
            [open_frame, closed_frame],
            on_empty=lambda: stream_ref[0].stop(),
        )

    stream = BinanceKlineStream(
        "XAUUSDT-PERP",
        "1h",
        connect_fn=fake_connect,
        now=lambda: now,
    )
    stream_ref.append(stream)

    bars = list(stream.bars())
    assert seen_urls == [f"{BINANCE_FAPI_WS_BASE_URL}/xauusdt@kline_1h"]
    assert len(bars) == 1
    assert bars[0].instrument_id == "XAUUSDT-PERP.SIM"
    assert bars[0].close == Decimal("4862.25")
    assert bars[0].taker_buy_base_volume == Decimal("140.250")

    agg_frame = json.dumps(
        {
            "e": "aggTrade",
            "E": close_ms,
            "s": "XAUUSDT",
            "a": 42,
            "p": "4862.25",
            "q": "0.150",
            "T": close_ms,
            "m": False,
        }
    )
    seen_trade_urls: list[str] = []
    trade_stream_ref: list[BinanceAggTradeStream] = []

    def fake_trade_connect(url: str) -> SocketLike:
        seen_trade_urls.append(url)
        return _ScriptedSocket([agg_frame], on_empty=lambda: trade_stream_ref[0].stop())

    trade_stream = BinanceAggTradeStream("XAUUSDT-PERP", connect_fn=fake_trade_connect)
    trade_stream_ref.append(trade_stream)
    trades = list(trade_stream.trades())
    assert seen_trade_urls == [f"{BINANCE_FAPI_WS_BASE_URL}/xauusdt@aggTrade"]
    assert len(trades) == 1
    assert trades[0].instrument_id == "XAUUSDT-PERP.SIM"


def test_metal_tokens_excluded_from_crypto_universe() -> None:
    """Metal bases are separated from the default crypto universe unless explicitly requested."""
    assert set(METAL_BASES) == {"PAXG", "XAUT", "XAU", "XAG"}
    for base in ("PAXG", "XAUT", "XAU", "XAG"):
        assert not is_tradeable_base(base)
        assert is_tradeable_base(base, include_metals=True)

    symbols = [
        "BTCUSDT",
        "ETHUSDT",
        "PAXGUSDT",
        "XAUTUSDT",
        "XAUUSDT-PERP",
        "XAGUSDT-PERP",
        "USDCUSDT",
    ]
    assert candidate_symbols(symbols) == ["BTCUSDT", "ETHUSDT"]
    assert candidate_symbols(symbols, include_metals=True) == [
        "BTCUSDT",
        "ETHUSDT",
        "PAXGUSDT",
        "XAGUSDT-PERP",
        "XAUTUSDT",
        "XAUUSDT-PERP",
    ]
    assert metal_symbols(symbols) == [
        "PAXGUSDT",
        "XAGUSDT-PERP",
        "XAUTUSDT",
        "XAUUSDT-PERP",
    ]


def test_gold_stress_slices_resolve_and_have_valid_windows() -> None:
    """Gold historical stress slices resolve with ordered UTC bounds."""
    expected = {
        "gold_efp2020": StressSliceName.GOLD_COVID_EFP_2020,
        "gold_rates2022": StressSliceName.GOLD_RATE_HIKE_2022,
        "gold_blowoff2026": StressSliceName.GOLD_BLOWOFF_2026,
    }
    for raw_name, enum_name in expected.items():
        window = resolve_stress_slice(raw_name)
        assert window.name is enum_name
        assert window.start.tzinfo is UTC
        assert window.end.tzinfo is UTC
        assert window.start < window.end


def test_funding_cadence_infers_4h_and_8h_intervals() -> None:
    """Funding settlement interval is inferred from observed timestamps (4h vs 8h, default 480m)."""
    t0 = datetime(2026, 2, 1, 0, 0, tzinfo=UTC)

    def _snaps(offsets_hours: list[int]) -> list[FundingSnapshot]:
        return [
            FundingSnapshot(
                instrument="PAXGUSDT-PERP.SIM",
                funding_rate=Decimal("0.0001"),
                mark_price=Decimal("4850.00"),
                index_price=None,
                ts_utc=t0 + timedelta(hours=h),
            )
            for h in offsets_hours
        ]

    assert _infer_funding_interval_minutes([]) == 480
    assert _infer_funding_interval_minutes(_snaps([0])) == 480
    assert _infer_funding_interval_minutes(_snaps([0, 4, 8, 12])) == 240
    assert _infer_funding_interval_minutes(_snaps([0, 8, 16, 24])) == 480
    # Missing one 4h settlement still yields 240m via median.
    assert _infer_funding_interval_minutes(_snaps([0, 4, 12, 16, 20])) == 240
