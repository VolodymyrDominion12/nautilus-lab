"""Tests for BinancePublicAggTrades and ParquetAggTradesCatalog.

All tests use fake HTTP clients and a tmp_path fixture — no network, no external state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nautilus_lab.application.dtos import IngestAggTradesRequest
from nautilus_lab.application.ingest_agg_trades import IngestAggTrades
from nautilus_lab.domain.errors import CatalogEmptyError
from nautilus_lab.domain.ticks import AggTrade
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.agg_trades_catalog import ParquetAggTradesCatalog
from nautilus_lab.infrastructure.binance_agg_trades import (
    BinancePublicAggTrades,
    _parse_agg_trade_row,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(
    agg_id: int,
    ts_ms: int,
    price: str = "2200.00",
    qty: str = "1.0",
    is_buyer_maker: bool = False,
) -> dict[str, object]:
    """Minimal Binance aggTrade JSON row."""
    return {
        "a": agg_id,
        "T": ts_ms,
        "p": price,
        "q": qty,
        "f": agg_id,
        "l": agg_id,
        "m": is_buyer_maker,
        "M": True,
    }


# ---------------------------------------------------------------------------
# _parse_agg_trade_row
# ---------------------------------------------------------------------------


def test_parse_row_basic() -> None:
    ts_ms = 1_704_067_200_000  # 2024-01-01 00:00:00 UTC
    row = _make_row(agg_id=42, ts_ms=ts_ms, price="2205.50", qty="3.5")
    trade = _parse_agg_trade_row(row, instrument_id="ETH/USDT.SIM")

    assert trade.agg_id == 42
    assert trade.price == "2205.50"
    assert trade.qty == "3.5"
    assert trade.is_buyer_maker is False
    assert trade.ts_utc == datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert trade.instrument_id == "ETH/USDT.SIM"


def test_parse_row_buyer_maker_flag() -> None:
    row = _make_row(agg_id=1, ts_ms=1_704_067_200_000, is_buyer_maker=True)
    trade = _parse_agg_trade_row(row, instrument_id="ETH/USDT.SIM")

    assert trade.is_buyer_maker is True
    assert trade.is_aggressive_sell is True
    assert trade.is_aggressive_buy is False


def test_parse_row_not_buyer_maker() -> None:
    row = _make_row(agg_id=1, ts_ms=1_704_067_200_000, is_buyer_maker=False)
    trade = _parse_agg_trade_row(row, instrument_id="ETH/USDT.SIM")

    assert trade.is_aggressive_buy is True
    assert trade.is_aggressive_sell is False


def test_parse_row_rejects_non_dict() -> None:
    with pytest.raises(ValueError, match="must be a dict"):
        _parse_agg_trade_row([1, 2, 3], instrument_id="ETH/USDT.SIM")


def test_parse_row_rejects_missing_field() -> None:
    row: dict[str, object] = {"a": 1, "T": 1_704_067_200_000}  # missing p, q, m
    with pytest.raises(ValueError, match="cannot parse"):
        _parse_agg_trade_row(row, instrument_id="ETH/USDT.SIM")


# ---------------------------------------------------------------------------
# BinancePublicAggTrades.fetch — paginator
# ---------------------------------------------------------------------------


class FakeHttp:
    """Fake HTTP client that returns pre-configured pages in order."""

    def __init__(self, pages: Sequence[Sequence[object]]) -> None:
        self.calls: list[Mapping[str, str]] = []
        self._pages = list(pages)

    def get_json(self, url: str, params: Mapping[str, str]) -> object:
        self.calls.append(params)
        assert "api.binance.com" in url
        return self._pages.pop(0)


def test_fetch_single_page() -> None:
    ts_ms = 1_704_067_200_000  # 2024-01-01T00:00:00Z
    rows = [_make_row(agg_id=i, ts_ms=ts_ms + i * 1000) for i in range(3)]
    fake = FakeHttp(pages=[rows, []])

    feed = BinancePublicAggTrades(
        fake,
        now=datetime(2024, 1, 2, tzinfo=UTC),
        page_limit=1000,
    )
    trades = feed.fetch(
        symbol="ETHUSDT",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 2, tzinfo=UTC),
        instrument_id="ETH/USDT.SIM",
    )

    assert len(trades) == 3
    assert trades[0].agg_id == 0
    assert trades[2].agg_id == 2


def test_fetch_paginates_via_from_id() -> None:
    """When a page is full (len == page_limit), fetch advances via fromId."""
    ts_ms_base = 1_704_067_200_000  # 2024-01-01T00:00:00Z

    page1 = [_make_row(agg_id=i, ts_ms=ts_ms_base + i * 500) for i in range(2)]
    page2 = [_make_row(agg_id=i, ts_ms=ts_ms_base + i * 500) for i in range(2, 4)]

    fake = FakeHttp(pages=[page1, page2, []])
    feed = BinancePublicAggTrades(
        fake,
        now=datetime(2024, 1, 2, tzinfo=UTC),
        page_limit=2,  # trigger pagination at 2 rows
    )
    trades = feed.fetch(
        symbol="ETHUSDT",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 2, tzinfo=UTC),
        instrument_id="ETH/USDT.SIM",
    )
    assert len(trades) == 4
    # Second call must use fromId, not startTime.
    second_call_params = fake.calls[1]
    assert "fromId" in second_call_params
    assert "startTime" not in second_call_params


def test_fetch_rejects_start_after_end() -> None:
    feed = BinancePublicAggTrades(None, now=datetime(2024, 1, 2, tzinfo=UTC))
    with pytest.raises(ValueError, match="start must be before end"):
        feed.fetch(
            symbol="ETHUSDT",
            start=datetime(2024, 1, 2, tzinfo=UTC),
            end=datetime(2024, 1, 1, tzinfo=UTC),
            instrument_id="ETH/USDT.SIM",
        )


def test_fetch_filters_trades_outside_window() -> None:
    """Trades returned by the API but outside the requested [start, end) are dropped."""
    inside_ms = 1_704_067_200_000  # 2024-01-01T00:00:00Z — inside
    outside_ms = 1_704_153_600_000  # 2024-01-02T00:00:00Z — equals end → excluded

    rows = [
        _make_row(agg_id=1, ts_ms=inside_ms),
        _make_row(agg_id=2, ts_ms=outside_ms),
    ]
    fake = FakeHttp(pages=[rows, []])
    feed = BinancePublicAggTrades(fake, now=datetime(2024, 1, 3, tzinfo=UTC))
    trades = feed.fetch(
        symbol="ETHUSDT",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 2, tzinfo=UTC),
        instrument_id="ETH/USDT.SIM",
    )
    assert len(trades) == 1
    assert trades[0].agg_id == 1


# ---------------------------------------------------------------------------
# ParquetAggTradesCatalog
# ---------------------------------------------------------------------------


def _make_trade(
    agg_id: int,
    ts: datetime,
    instrument_id: str = "ETH/USDT.SIM",
    price: str = "2200.00",
    qty: str = "1.0",
    is_buyer_maker: bool = False,
) -> AggTrade:
    return AggTrade(
        instrument_id=instrument_id,
        ts_utc=ts,
        agg_id=agg_id,
        price=price,
        qty=qty,
        is_buyer_maker=is_buyer_maker,
    )


def test_catalog_write_and_load_roundtrip(tmp_path: Path) -> None:
    cat = ParquetAggTradesCatalog(tmp_path)
    trades = [
        _make_trade(1, datetime(2024, 1, 1, 10, 0, tzinfo=UTC)),
        _make_trade(2, datetime(2024, 1, 1, 11, 0, tzinfo=UTC)),
        _make_trade(3, datetime(2024, 1, 1, 12, 0, tzinfo=UTC)),
    ]
    written = cat.write(trades, symbol="ETHUSDT")
    assert written == 3

    loaded = cat.load(symbol="ETHUSDT")
    assert len(loaded) == 3
    assert loaded[0].agg_id == 1
    assert loaded[2].agg_id == 3
    assert loaded[1].price == "2200.00"
    assert loaded[0].ts_utc.tzinfo is not None


def test_catalog_load_with_time_filter(tmp_path: Path) -> None:
    cat = ParquetAggTradesCatalog(tmp_path)
    trades = [
        _make_trade(1, datetime(2024, 1, 1, 9, 0, tzinfo=UTC)),
        _make_trade(2, datetime(2024, 1, 1, 12, 0, tzinfo=UTC)),
        _make_trade(3, datetime(2024, 1, 1, 23, 0, tzinfo=UTC)),
    ]
    cat.write(trades, symbol="ETHUSDT")

    loaded = cat.load(
        symbol="ETHUSDT",
        start=datetime(2024, 1, 1, 10, 0, tzinfo=UTC),
        end=datetime(2024, 1, 1, 20, 0, tzinfo=UTC),
    )
    assert len(loaded) == 1
    assert loaded[0].agg_id == 2


def test_catalog_load_empty_when_no_data(tmp_path: Path) -> None:
    cat = ParquetAggTradesCatalog(tmp_path)
    loaded = cat.load(symbol="BTCUSDT")
    assert loaded == []


def test_catalog_write_deduplicates_by_agg_id(tmp_path: Path) -> None:
    """Writing the same trades twice must not duplicate them."""
    cat = ParquetAggTradesCatalog(tmp_path)
    trades = [
        _make_trade(1, datetime(2024, 1, 1, 10, 0, tzinfo=UTC)),
        _make_trade(2, datetime(2024, 1, 1, 11, 0, tzinfo=UTC)),
    ]
    cat.write(trades, symbol="ETHUSDT")
    cat.write(trades, symbol="ETHUSDT")  # second write of the same trades

    loaded = cat.load(symbol="ETHUSDT")
    assert len(loaded) == 2, "duplicate trades should be merged away"


def test_catalog_preserves_is_buyer_maker(tmp_path: Path) -> None:
    cat = ParquetAggTradesCatalog(tmp_path)
    trade = _make_trade(1, datetime(2024, 1, 1, 10, 0, tzinfo=UTC), is_buyer_maker=True)
    cat.write([trade], symbol="ETHUSDT")
    loaded = cat.load(symbol="ETHUSDT")
    assert loaded[0].is_buyer_maker is True


def test_catalog_cross_day_write(tmp_path: Path) -> None:
    """Trades spanning two UTC days are stored in separate files."""
    cat = ParquetAggTradesCatalog(tmp_path)
    day1_trade = _make_trade(1, datetime(2024, 1, 1, 23, 30, tzinfo=UTC))
    day2_trade = _make_trade(2, datetime(2024, 1, 2, 0, 30, tzinfo=UTC))
    cat.write([day1_trade, day2_trade], symbol="ETHUSDT")

    symbol_dir = tmp_path / "data" / "agg_trade" / "ETHUSDT"
    parquet_files = list(symbol_dir.glob("*.parquet"))
    assert len(parquet_files) == 2, "each day should produce its own Parquet file"

    loaded = cat.load(symbol="ETHUSDT")
    assert len(loaded) == 2


# ---------------------------------------------------------------------------
# Ingest use case: slice-by-slice persistence
# ---------------------------------------------------------------------------


class _SliceFeed:
    """AggTradesFeed double that returns scripted trades keyed by slice start hour."""

    def __init__(self, per_slice: dict[str, list[AggTrade]]) -> None:
        self._per_slice = per_slice
        self.calls: list[tuple[datetime, datetime]] = []

    def fetch(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        instrument_id: str,
    ) -> list[AggTrade]:
        self.calls.append((start, end))
        return list(self._per_slice.get(start.strftime("%Y-%m-%dT%H"), []))


def _trade(agg_id: int, ts: datetime) -> AggTrade:
    return AggTrade(
        agg_id=agg_id,
        instrument_id="ETH/USDT.SIM",
        ts_utc=ts,
        price="2200",
        qty="1",
        is_buyer_maker=False,
    )


def test_ingest_persists_each_slice_as_it_goes(tmp_path: Path) -> None:
    """Every slice must reach the catalog before the next one is fetched.

    Regression, measured twice. First the use case fetched the whole window into memory
    and wrote only at the end: a four-day ingest wrote nothing in fifty minutes. Then it
    fetched a whole day at a time, and one day is ~720 Binance pages holding ~120 seconds
    of market time each — thirty minutes produced no file at all. Hourly slices bound
    both memory and the loss from a stalled socket.
    """
    hour_zero = datetime(2024, 1, 1, 0, tzinfo=UTC)
    hour_one = datetime(2024, 1, 1, 1, tzinfo=UTC)
    hour_two = datetime(2024, 1, 1, 2, tzinfo=UTC)
    feed = _SliceFeed(
        {
            "2024-01-01T00": [_trade(1, hour_zero), _trade(2, hour_zero)],
            "2024-01-01T01": [_trade(3, hour_one)],
            # 02:00 is deliberately absent: a quiet slice must not stop the ingest.
        }
    )
    observed: list[tuple[str, int]] = []

    def _progress(slice_start: datetime, trades: int) -> None:
        # Whatever the catalog holds now, the earlier slices are already in it.
        present = {item.agg_id for item in ParquetAggTradesCatalog(tmp_path).load(symbol="ETHUSDT")}
        observed.append((slice_start.strftime("%H"), len(present)))
        assert trades >= 0

    use_case = IngestAggTrades(
        feed,
        ParquetAggTradesCatalog(tmp_path),
        catalog_path=str(tmp_path),
        progress=_progress,
    )
    report = use_case.execute(
        IngestAggTradesRequest(
            mode=TradingMode.RESEARCH,
            symbol="ETHUSDT",
            instrument_id="ETH/USDT.SIM",
            start=hour_zero,
            end=hour_two + timedelta(hours=1),
        )
    )

    assert report.trades_written == 3
    # One fetch per hour slice, including the quiet one.
    assert len(feed.calls) == 3
    assert [call[0].hour for call in feed.calls] == [0, 1, 2]
    # By the time the third slice is reported, the first two are already on disk.
    assert observed[2][1] == 3


def test_ingest_skips_empty_slices_but_fails_on_an_empty_window(tmp_path: Path) -> None:
    """A quiet slice is not an error; a window with no trades at all is."""
    start = datetime(2024, 1, 1, 0, tzinfo=UTC)
    feed = _SliceFeed({"2024-01-01T01": [_trade(1, datetime(2024, 1, 1, 1, tzinfo=UTC))]})
    use_case = IngestAggTrades(
        feed,
        ParquetAggTradesCatalog(tmp_path),
        catalog_path=str(tmp_path),
    )

    report = use_case.execute(
        IngestAggTradesRequest(
            mode=TradingMode.RESEARCH,
            symbol="ETHUSDT",
            instrument_id="ETH/USDT.SIM",
            start=start,
            end=start + timedelta(hours=2),
        )
    )
    assert report.trades_written == 1
    assert len(feed.calls) == 2  # the empty slice was still attempted

    empty = IngestAggTrades(
        _SliceFeed({}),
        ParquetAggTradesCatalog(tmp_path),
        catalog_path=str(tmp_path),
    )
    with pytest.raises(CatalogEmptyError):
        empty.execute(
            IngestAggTradesRequest(
                mode=TradingMode.RESEARCH,
                symbol="ETHUSDT",
                instrument_id="ETH/USDT.SIM",
                start=start,
                end=start + timedelta(hours=2),
            )
        )
