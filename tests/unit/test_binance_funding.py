from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal

from nautilus_lab.domain.ports import JsonHttpClient
from nautilus_lab.infrastructure.binance_funding import BinancePublicFunding


class _MockFundingHttpClient(JsonHttpClient):
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.last_url: str | None = None
        self.last_params: Mapping[str, str] | None = None

    def get_json(self, url: str, params: Mapping[str, str]) -> object:
        self.last_url = url
        self.last_params = params
        return self.payload


def test_binance_funding_fetch_history_parses_snapshots() -> None:
    payload = [
        {
            "symbol": "ETHUSDT",
            "fundingRate": "0.00010000",
            "fundingTime": 1704067200000,
            "markPrice": "2280.50000000",
            "indexPrice": "2280.20000000",
        },
        {
            "symbol": "ETHUSDT",
            "fundingRate": "-0.00005000",
            "fundingTime": 1704096000000,
        },
        "invalid_item_skipped",
    ]
    client = _MockFundingHttpClient(payload)
    funding_feed = BinancePublicFunding(client)

    start = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    end = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)

    snapshots = funding_feed.fetch_history(symbol="ETHUSDT", start=start, end=end)

    assert len(snapshots) == 2
    assert snapshots[0].instrument == "ETHUSDT"
    assert snapshots[0].funding_rate == Decimal("0.00010000")
    assert snapshots[0].mark_price == Decimal("2280.50000000")
    assert snapshots[0].index_price == Decimal("2280.20000000")
    assert snapshots[0].ts_utc == datetime(2024, 1, 1, 0, 0, tzinfo=UTC)

    assert snapshots[1].funding_rate == Decimal("-0.00005000")
    assert snapshots[1].mark_price == Decimal("-0.00005000")  # fallback to fundingRate
    assert snapshots[1].index_price == Decimal("1")  # fallback to default "1"

    assert client.last_url == "https://fapi.binance.com/fapi/v1/fundingRate"
    assert client.last_params is not None
    assert client.last_params["symbol"] == "ETHUSDT"
    assert client.last_params["limit"] == "1000"


def test_binance_funding_non_list_payload_returns_empty() -> None:
    client = _MockFundingHttpClient({"error": "rate limit"})
    funding_feed = BinancePublicFunding(client)

    start = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    end = datetime(2024, 1, 1, 1, 0, tzinfo=UTC)
    snapshots = funding_feed.fetch_history(symbol="BTCUSDT", start=start, end=end)
    assert snapshots == []


def test_binance_funding_default_client() -> None:
    funding_feed = BinancePublicFunding()
    assert funding_feed._client is not None
