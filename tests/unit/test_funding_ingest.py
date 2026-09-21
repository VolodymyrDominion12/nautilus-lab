from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from nautilus_lab.application.dtos import FundingIngestRequest
from nautilus_lab.application.ingest_funding_history import IngestFundingHistory
from nautilus_lab.domain.errors import CatalogEmptyError, LiveTradingDisabledError
from nautilus_lab.domain.funding import FundingSnapshot
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.funding_catalog import ParquetFundingCatalog

_START = datetime(2025, 1, 1, tzinfo=UTC)


def _snapshot(
    hours: int, *, rate: str = "0.0001", mark: str = "2280.5", index: str | None = "2280.2"
) -> FundingSnapshot:
    return FundingSnapshot(
        instrument="ETHUSDT",
        funding_rate=Decimal(rate),
        mark_price=Decimal(mark),
        index_price=None if index is None else Decimal(index),
        ts_utc=_START + timedelta(hours=hours),
    )


class _StubFeed:
    def __init__(self, snapshots: list[FundingSnapshot]) -> None:
        self._snapshots = snapshots
        self.calls: list[tuple[str, datetime, datetime]] = []

    def fetch_history(
        self, *, symbol: str, start: datetime, end: datetime
    ) -> list[FundingSnapshot]:
        self.calls.append((symbol, start, end))
        return self._snapshots


# --- catalog ----------------------------------------------------------------


def test_catalog_round_trips_a_series(tmp_path: Path) -> None:
    catalog = ParquetFundingCatalog(tmp_path)
    written = catalog.write([_snapshot(0), _snapshot(8)], symbol="ETHUSDT")

    assert written == 2
    loaded = catalog.load(symbol="ETHUSDT")
    assert [item.ts_utc for item in loaded] == [_START, _START + timedelta(hours=8)]
    assert loaded[0].funding_rate == Decimal("0.0001")
    assert loaded[0].mark_price == Decimal("2280.5")
    assert loaded[0].index_price == Decimal("2280.2")


def test_catalog_preserves_decimal_exactly(tmp_path: Path) -> None:
    # Parquet floats would round-trip this through binary floating point; the series
    # is stored as strings precisely so the domain's Decimal arithmetic stays exact.
    exact = "0.00003705000001"
    catalog = ParquetFundingCatalog(tmp_path)
    catalog.write([_snapshot(0, rate=exact)], symbol="ETHUSDT")
    assert catalog.load(symbol="ETHUSDT")[0].funding_rate == Decimal(exact)


def test_missing_index_price_survives_the_round_trip_as_missing(tmp_path: Path) -> None:
    catalog = ParquetFundingCatalog(tmp_path)
    catalog.write([_snapshot(0, index=None)], symbol="ETHUSDT")
    loaded = catalog.load(symbol="ETHUSDT")
    assert loaded[0].index_price is None
    assert loaded[0].basis() is None


def test_rewriting_an_overlapping_window_does_not_duplicate(tmp_path: Path) -> None:
    catalog = ParquetFundingCatalog(tmp_path)
    catalog.write([_snapshot(0), _snapshot(8)], symbol="ETHUSDT")
    catalog.write([_snapshot(8, rate="0.0009"), _snapshot(16)], symbol="ETHUSDT")

    loaded = catalog.load(symbol="ETHUSDT")
    assert len(loaded) == 3, "overlapping settlements must be replaced, not appended"
    assert loaded[1].funding_rate == Decimal("0.0009"), "the newest ingest wins"


def test_catalog_load_filters_by_window(tmp_path: Path) -> None:
    catalog = ParquetFundingCatalog(tmp_path)
    catalog.write([_snapshot(0), _snapshot(8), _snapshot(16)], symbol="ETHUSDT")
    loaded = catalog.load(
        symbol="ETHUSDT", start=_START + timedelta(hours=8), end=_START + timedelta(hours=16)
    )
    assert [item.ts_utc for item in loaded] == [_START + timedelta(hours=8)]


def test_unknown_symbol_is_an_empty_series_not_an_error(tmp_path: Path) -> None:
    catalog = ParquetFundingCatalog(tmp_path)
    assert catalog.load(symbol="BTCUSDT") == []
    assert catalog.series_exists(symbol="BTCUSDT") is False


def test_writing_an_empty_series_is_refused(tmp_path: Path) -> None:
    catalog = ParquetFundingCatalog(tmp_path)
    with pytest.raises(CatalogEmptyError):
        catalog.write([], symbol="ETHUSDT")


def test_series_path_is_separate_from_the_bar_series(tmp_path: Path) -> None:
    catalog = ParquetFundingCatalog(tmp_path)
    assert (
        catalog.series_path("ethusdt").as_posix().endswith("data/funding/ETHUSDT/funding.parquet")
    )


# --- use case ---------------------------------------------------------------


def test_use_case_writes_and_reports(tmp_path: Path) -> None:
    feed = _StubFeed([_snapshot(0), _snapshot(8), _snapshot(16, index=None)])
    catalog = ParquetFundingCatalog(tmp_path)
    use_case = IngestFundingHistory(feed, catalog, catalog_path=str(tmp_path))

    report = use_case.execute(
        FundingIngestRequest(
            mode=TradingMode.RESEARCH,
            symbol="ETHUSDT",
            start=_START,
            end=_START + timedelta(days=1),
        )
    )

    assert report.snapshots_written == 3
    assert report.symbol == "ETHUSDT"
    assert report.first_ts == _START
    assert report.last_ts == _START + timedelta(hours=16)
    # The unjoined row is counted and reported, not silently given a fake index.
    assert report.missing_index_price == 1
    assert len(catalog.load(symbol="ETHUSDT")) == 3


def test_use_case_reports_zero_missing_when_every_index_joined(tmp_path: Path) -> None:
    feed = _StubFeed([_snapshot(0), _snapshot(8)])
    use_case = IngestFundingHistory(feed, ParquetFundingCatalog(tmp_path), catalog_path="x")
    report = use_case.execute(
        FundingIngestRequest(
            mode=TradingMode.RESEARCH,
            symbol="ETHUSDT",
            start=_START,
            end=_START + timedelta(days=1),
        )
    )
    assert report.missing_index_price == 0


def test_use_case_fails_when_nothing_is_available(tmp_path: Path) -> None:
    use_case = IngestFundingHistory(
        _StubFeed([]), ParquetFundingCatalog(tmp_path), catalog_path=str(tmp_path)
    )
    with pytest.raises(CatalogEmptyError, match="no public funding settlements"):
        use_case.execute(
            FundingIngestRequest(
                mode=TradingMode.RESEARCH,
                symbol="ETHUSDT",
                start=_START,
                end=_START + timedelta(days=1),
            )
        )


def test_use_case_rejects_an_inverted_window(tmp_path: Path) -> None:
    use_case = IngestFundingHistory(
        _StubFeed([]), ParquetFundingCatalog(tmp_path), catalog_path=str(tmp_path)
    )
    with pytest.raises(ValueError, match="start must be before end"):
        use_case.execute(
            FundingIngestRequest(
                mode=TradingMode.RESEARCH,
                symbol="ETHUSDT",
                start=_START + timedelta(days=1),
                end=_START,
            )
        )


def test_use_case_refuses_a_non_research_mode(tmp_path: Path) -> None:
    use_case = IngestFundingHistory(
        _StubFeed([]), ParquetFundingCatalog(tmp_path), catalog_path=str(tmp_path)
    )
    with pytest.raises(LiveTradingDisabledError, match="Live trading is disabled"):
        use_case.execute(
            FundingIngestRequest(
                mode=TradingMode.LIVE,
                symbol="ETHUSDT",
                start=_START,
                end=_START + timedelta(days=1),
            )
        )
