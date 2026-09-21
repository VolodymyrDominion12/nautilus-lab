from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from nautilus_lab.domain.order_book import BookLevel, OrderBookSnapshot
from nautilus_lab.infrastructure.orderbook_catalog import ParquetOrderBookCatalog


def test_parquet_orderbook_catalog_roundtrip(tmp_path: Path) -> None:
    catalog = ParquetOrderBookCatalog(tmp_path)

    snap = OrderBookSnapshot(
        instrument_id="ETHUSDT",
        ts_utc=datetime(2026, 9, 21, 10, 0, 0, tzinfo=UTC),
        bids=(
            BookLevel(Decimal("3000.50"), Decimal("1.5")),
            BookLevel(Decimal("3000.40"), Decimal("2.0")),
        ),
        asks=(
            BookLevel(Decimal("3000.60"), Decimal("0.5")),
            BookLevel(Decimal("3000.70"), Decimal("3.0")),
        ),
    )

    written = catalog.write([snap], symbol="ETHUSDT")
    assert written == 1

    loaded = catalog.load(symbol="ETHUSDT")
    assert len(loaded) == 1

    res = loaded[0]
    assert res.instrument_id == "ETHUSDT"
    assert res.ts_utc == snap.ts_utc
    assert len(res.bids) == 2
    assert res.bids[0].price == Decimal("3000.50")
    assert res.bids[0].size == Decimal("1.5")
    assert len(res.asks) == 2
    assert res.asks[0].price == Decimal("3000.60")
    assert res.asks[0].size == Decimal("0.5")
