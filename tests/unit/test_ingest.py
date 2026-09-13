from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from nautilus_lab.application.dtos import IngestRequest
from nautilus_lab.application.ingest_historical_bars import IngestHistoricalBars
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import CatalogEmptyError
from nautilus_lab.domain.trading_mode import TradingMode


def test_ingest_writes_validated_public_bars() -> None:
    bars = [
        OhlcvBar(
            instrument_id="ETH/USDT.SIM",
            ts_utc=datetime(2024, 1, 1, 1, 0, tzinfo=UTC),
            open=Decimal("2200"),
            high=Decimal("2210"),
            low=Decimal("2190"),
            close=Decimal("2205"),
            volume=Decimal("100"),
        )
    ]

    class FakeFeed:
        def fetch(self, **kwargs: object) -> list[OhlcvBar]:
            assert kwargs["symbol"] == "ETHUSDT"
            return bars

    class FakeCatalog:
        def __init__(self) -> None:
            self.written: list[OhlcvBar] = []
            self.bar_type: str | None = None

        def write(self, payload: Sequence[OhlcvBar], *, bar_type: str) -> int:
            self.written = list(payload)
            self.bar_type = bar_type
            return len(payload)

        def load(self, **kwargs: object) -> list[OhlcvBar]:
            raise AssertionError("ingest does not load")

    store = FakeCatalog()
    report = IngestHistoricalBars(FakeFeed(), store, catalog_path="/tmp/catalog").execute(
        IngestRequest(
            mode=TradingMode.RESEARCH,
            symbol="ETHUSDT",
            interval="1h",
            instrument_id="ETH/USDT.SIM",
            bar_type="ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
        )
    )

    assert report.bars_written == 1
    assert store.bar_type == "ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL"
    assert report.source.startswith("binance")


def test_ingest_rejects_empty_feed() -> None:
    class EmptyFeed:
        def fetch(self, **kwargs: object) -> list[OhlcvBar]:
            return []

    class UnusedCatalog:
        def write(self, bars: Sequence[OhlcvBar], *, bar_type: str) -> int:
            raise AssertionError("must not write")

        def load(self, **kwargs: object) -> list[OhlcvBar]:
            raise AssertionError("must not load")

    use_case = IngestHistoricalBars(EmptyFeed(), UnusedCatalog(), catalog_path="catalog")
    with pytest.raises(CatalogEmptyError, match="no public klines"):
        use_case.execute(
            IngestRequest(
                mode=TradingMode.RESEARCH,
                symbol="ETHUSDT",
                interval="1h",
                instrument_id="ETH/USDT.SIM",
                bar_type="ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL",
                start=datetime(2024, 1, 1, tzinfo=UTC),
                end=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )
