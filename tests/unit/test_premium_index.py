from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from nautilus_lab.domain.errors import CatalogEmptyError
from nautilus_lab.domain.ports import JsonHttpClient
from nautilus_lab.domain.premium_index import PremiumIndexBar
from nautilus_lab.infrastructure.binance_premium_index import (
    BinancePublicPremiumIndex,
)
from nautilus_lab.infrastructure.premium_index_catalog import ParquetPremiumIndexCatalog


class _MockPremiumHttpClient(JsonHttpClient):
    def __init__(self, pages: list[list[object]]) -> None:
        self.pages = list(pages)
        self.calls: list[tuple[str, Mapping[str, str]]] = []

    def get_json(self, url: str, params: Mapping[str, str]) -> object:
        self.calls.append((url, params))
        if not self.pages:
            return []
        return self.pages.pop(0)


def _row(
    open_ms: int, close_ms: int, open_p: str, high_p: str, low_p: str, close_p: str
) -> list[object]:
    return [open_ms, open_p, high_p, low_p, close_p, "0", close_ms, "0", 100, "0", "0", "0"]


def test_premium_index_fetch_and_pagination() -> None:
    t0_open = 1_704_067_200_000
    t0_close = 1_704_153_599_999
    t1_open = 1_704_153_600_000
    t1_close = 1_704_239_999_999

    client = _MockPremiumHttpClient(
        [
            [_row(t0_open, t0_close, "0.0001", "0.0002", "0.0000", "0.00015")],
            [_row(t1_open, t1_close, "0.00015", "0.0003", "0.0001", "0.00025")],
            [],
        ]
    )

    feed = BinancePublicPremiumIndex(client, page_limit=1)
    bars = feed.fetch(
        symbol="BTCUSDT-PERP",
        interval="1d",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 3, tzinfo=UTC),
    )

    assert len(bars) == 2
    assert bars[0].symbol == "BTCUSDT"
    assert bars[0].interval == "1d"
    assert bars[0].close == Decimal("0.00015")
    assert bars[1].close == Decimal("0.00025")
    assert len(client.calls) == 3


def test_premium_index_rejects_invalid_args() -> None:
    with pytest.raises(ValueError, match="page_limit must be >= 1"):
        BinancePublicPremiumIndex(page_limit=0)

    feed = BinancePublicPremiumIndex()
    with pytest.raises(ValueError, match="start must be before end"):
        feed.fetch(
            symbol="BTCUSDT",
            interval="1d",
            start=datetime(2024, 1, 2, tzinfo=UTC),
            end=datetime(2024, 1, 1, tzinfo=UTC),
        )


def test_premium_index_catalog_round_trip_and_idempotence(tmp_path: Path) -> None:
    catalog = ParquetPremiumIndexCatalog(tmp_path)
    t0 = datetime(2024, 1, 1, 23, 59, 59, tzinfo=UTC)
    t1 = datetime(2024, 1, 2, 23, 59, 59, tzinfo=UTC)

    bar1 = PremiumIndexBar(
        symbol="SOLUSDT",
        interval="1d",
        ts_utc=t0,
        open=Decimal("0.0001"),
        high=Decimal("0.0002"),
        low=Decimal("0.0000"),
        close=Decimal("0.00015"),
    )
    bar2 = PremiumIndexBar(
        symbol="SOLUSDT",
        interval="1d",
        ts_utc=t1,
        open=Decimal("0.00015"),
        high=Decimal("0.0003"),
        low=Decimal("0.0001"),
        close=Decimal("0.00025"),
    )

    # Empty write raises error
    with pytest.raises(CatalogEmptyError):
        catalog.write([], symbol="SOLUSDT", interval="1d")

    # Write initial bars
    written = catalog.write([bar1, bar2], symbol="SOLUSDT-PERP", interval="1d")
    assert written == 2

    # Load back
    loaded = catalog.load(symbol="SOLUSDT", interval="1d")
    assert len(loaded) == 2
    assert loaded[0].close == Decimal("0.00015")
    assert loaded[1].close == Decimal("0.00025")

    # Idempotent write / replace
    updated_bar2 = PremiumIndexBar(
        symbol="SOLUSDT",
        interval="1d",
        ts_utc=t1,
        open=Decimal("0.0002"),
        high=Decimal("0.0004"),
        low=Decimal("0.0001"),
        close=Decimal("0.00035"),
    )
    catalog.write([updated_bar2], symbol="SOLUSDT", interval="1d")
    reloaded = catalog.load(symbol="SOLUSDT", interval="1d")
    assert len(reloaded) == 2
    assert reloaded[1].close == Decimal("0.00035")

    # Window slicing
    slice_only_t0 = catalog.load(
        symbol="SOLUSDT",
        interval="1d",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 2, tzinfo=UTC),
    )
    assert len(slice_only_t0) == 1
    assert slice_only_t0[0].ts_utc == t0
