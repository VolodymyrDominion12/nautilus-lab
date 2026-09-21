from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from nautilus_lab.domain.ports import JsonHttpClient
from nautilus_lab.infrastructure.binance_funding import (
    FUNDING_RATE_URL,
    INDEX_PRICE_KLINES_URL,
    BinancePublicFunding,
)


class _MockFundingHttpClient(JsonHttpClient):
    """Serves scripted pages per endpoint and records every request."""

    def __init__(self, pages: dict[str, list[object]]) -> None:
        self.pages = {url: list(items) for url, items in pages.items()}
        self.calls: list[tuple[str, Mapping[str, str]]] = []

    def get_json(self, url: str, params: Mapping[str, str]) -> object:
        self.calls.append((url, params))
        queue = self.pages.get(url)
        if not queue:
            return []
        return queue.pop(0)

    def params_for(self, url: str) -> list[Mapping[str, str]]:
        return [params for called_url, params in self.calls if called_url == url]


def _funding_row(ms: int, rate: str, mark: str) -> dict[str, str | int]:
    return {"symbol": "ETHUSDT", "fundingTime": ms, "fundingRate": rate, "markPrice": mark}


def _index_row(open_ms: int, price: str) -> list[object]:
    return [open_ms, price, price, price, price, "0", open_ms + 3_599_999]


# 2024-01-01T00:00Z, 08:00Z and 16:00Z
_T0 = 1_704_067_200_000
_T8 = 1_704_096_000_000
_T16 = 1_704_124_800_000


def test_fetch_history_pairs_settlements_with_a_real_index_price() -> None:
    client = _MockFundingHttpClient(
        {
            FUNDING_RATE_URL: [
                [
                    _funding_row(_T0, "0.00010000", "2280.50000000"),
                    _funding_row(_T8, "-0.00005000", "2270.00000000"),
                ]
            ],
            INDEX_PRICE_KLINES_URL: [[_index_row(_T0, "2280.20000000"), _index_row(_T8, "2271.5")]],
        }
    )
    feed = BinancePublicFunding(client)

    snapshots = feed.fetch_history(
        symbol="ETHUSDT",
        start=datetime(2024, 1, 1, 0, 0, tzinfo=UTC),
        end=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
    )

    assert len(snapshots) == 2
    first = snapshots[0]
    assert first.instrument == "ETHUSDT"
    assert first.funding_rate == Decimal("0.00010000")
    assert first.mark_price == Decimal("2280.50000000")
    assert first.index_price == Decimal("2280.20000000")
    assert first.ts_utc == datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    # The basis is genuinely non-zero. The previous adapter defaulted index to mark,
    # which made it identically zero and left the basis_max gate unable to fire.
    assert first.basis() == (Decimal("2280.50000000") - Decimal("2280.20000000")) / Decimal(
        "2280.20000000"
    )
    assert snapshots[1].index_price == Decimal("2271.5")


def test_index_price_is_none_not_mark_when_the_join_misses() -> None:
    # Foundation of the fail-closed rule: an unjoined index must stay unknown so the
    # robot reports "missing index price" instead of reading a flat basis.
    client = _MockFundingHttpClient(
        {
            FUNDING_RATE_URL: [[_funding_row(_T0, "0.00010000", "2280.50000000")]],
            INDEX_PRICE_KLINES_URL: [[]],
        }
    )
    snapshots = BinancePublicFunding(client).fetch_history(
        symbol="ETHUSDT",
        start=datetime(2024, 1, 1, 0, 0, tzinfo=UTC),
        end=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
    )
    assert len(snapshots) == 1
    assert snapshots[0].index_price is None
    assert snapshots[0].basis() is None


def test_index_prices_can_be_skipped_entirely() -> None:
    client = _MockFundingHttpClient({FUNDING_RATE_URL: [[_funding_row(_T0, "0.0001", "2280.5")]]})
    snapshots = BinancePublicFunding(client, with_index_prices=False).fetch_history(
        symbol="ETHUSDT",
        start=datetime(2024, 1, 1, 0, 0, tzinfo=UTC),
        end=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
    )
    assert snapshots[0].index_price is None
    assert client.params_for(INDEX_PRICE_KLINES_URL) == []


def test_history_paginates_past_the_single_page_cap() -> None:
    # Measured on the live endpoint: a 400-day window overflows the 1000-row page cap
    # (~1200 settlements) and the excess used to be dropped without a word.
    first_page = [_funding_row(_T0 + i * 28_800_000, "0.0001", "2280.5") for i in range(3)]
    second_page = [_funding_row(_T0 + (3 + i) * 28_800_000, "0.0001", "2280.5") for i in range(2)]
    client = _MockFundingHttpClient(
        {
            FUNDING_RATE_URL: [first_page, second_page],
            INDEX_PRICE_KLINES_URL: [[]],
        }
    )
    feed = BinancePublicFunding(client, page_limit=3, with_index_prices=False)
    snapshots = feed.fetch_history(
        symbol="ETHUSDT",
        start=datetime(2024, 1, 1, 0, 0, tzinfo=UTC),
        end=datetime(2024, 1, 10, 0, 0, tzinfo=UTC),
    )

    assert len(snapshots) == 5
    pages = client.params_for(FUNDING_RATE_URL)
    assert len(pages) == 2, "a full page must trigger a second request"
    # The second request starts just after the last settlement of the first page.
    assert pages[1]["startTime"] == str(_T0 + 2 * 28_800_000 + 1)


def test_pagination_stops_on_a_short_page() -> None:
    client = _MockFundingHttpClient(
        {
            FUNDING_RATE_URL: [[_funding_row(_T0, "0.0001", "2280.5")]],
            INDEX_PRICE_KLINES_URL: [[]],
        }
    )
    feed = BinancePublicFunding(client, page_limit=1000, with_index_prices=False)
    feed.fetch_history(
        symbol="ETHUSDT",
        start=datetime(2024, 1, 1, 0, 0, tzinfo=UTC),
        end=datetime(2024, 1, 10, 0, 0, tzinfo=UTC),
    )
    assert len(client.params_for(FUNDING_RATE_URL)) == 1


def test_index_price_klines_paginate_too() -> None:
    client = _MockFundingHttpClient(
        {
            FUNDING_RATE_URL: [
                [
                    _funding_row(_T0, "0.0001", "2280.5"),
                    _funding_row(_T8, "0.0001", "2281.5"),
                ]
            ],
            INDEX_PRICE_KLINES_URL: [
                [_index_row(_T0, "2280.2"), _index_row(_T0 + 3_600_000, "2280.3")],
                [_index_row(_T8, "2271.5")],
            ],
        }
    )
    feed = BinancePublicFunding(client, page_limit=2)
    snapshots = feed.fetch_history(
        symbol="ETHUSDT",
        start=datetime(2024, 1, 1, 0, 0, tzinfo=UTC),
        end=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
    )
    assert [item.index_price for item in snapshots] == [Decimal("2280.2"), Decimal("2271.5")]
    assert len(client.params_for(INDEX_PRICE_KLINES_URL)) == 2


def test_malformed_rows_are_skipped_not_fabricated() -> None:
    client = _MockFundingHttpClient(
        {
            FUNDING_RATE_URL: [
                [
                    "invalid_item",
                    {"symbol": "ETHUSDT", "fundingTime": _T0},  # no rate, no mark
                    _funding_row(_T8, "not-a-number", "2280.5"),
                    _funding_row(_T16, "0.0002", "2290.0"),
                ]
            ],
            INDEX_PRICE_KLINES_URL: [[]],
        }
    )
    snapshots = BinancePublicFunding(client).fetch_history(
        symbol="ETHUSDT",
        start=datetime(2024, 1, 1, 0, 0, tzinfo=UTC),
        end=datetime(2024, 1, 2, 0, 0, tzinfo=UTC),
    )
    assert len(snapshots) == 1
    assert snapshots[0].mark_price == Decimal("2290.0")


def test_rows_outside_the_window_are_dropped() -> None:
    client = _MockFundingHttpClient(
        {
            FUNDING_RATE_URL: [[_funding_row(_T16, "0.0002", "2290.0")]],
            INDEX_PRICE_KLINES_URL: [[]],
        }
    )
    snapshots = BinancePublicFunding(client).fetch_history(
        symbol="ETHUSDT",
        start=datetime(2024, 1, 1, 0, 0, tzinfo=UTC),
        end=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
    )
    assert snapshots == []


def test_non_list_payload_is_an_empty_series() -> None:
    client = _MockFundingHttpClient({FUNDING_RATE_URL: [{"error": "rate limit"}]})
    snapshots = BinancePublicFunding(client).fetch_history(
        symbol="BTCUSDT",
        start=datetime(2024, 1, 1, 0, 0, tzinfo=UTC),
        end=datetime(2024, 1, 1, 1, 0, tzinfo=UTC),
    )
    assert snapshots == []


def test_inverted_window_is_rejected() -> None:
    feed = BinancePublicFunding(_MockFundingHttpClient({}))
    with pytest.raises(ValueError, match="start must be before end"):
        feed.fetch_history(
            symbol="ETHUSDT",
            start=datetime(2024, 1, 2, tzinfo=UTC),
            end=datetime(2024, 1, 1, tzinfo=UTC),
        )


def test_page_limit_must_be_positive() -> None:
    with pytest.raises(ValueError, match="page_limit"):
        BinancePublicFunding(_MockFundingHttpClient({}), page_limit=0)


def test_default_client_is_the_resilient_one() -> None:
    # Guards the D7 failure mode in reverse: the adapter must not be constructible
    # with a bare client that ignores 429/418.
    from nautilus_lab.infrastructure.http_resilience import ResilientJsonClient

    assert isinstance(BinancePublicFunding()._client, ResilientJsonClient)
