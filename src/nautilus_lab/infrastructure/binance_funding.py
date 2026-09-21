"""Public Binance USD-M funding history. No API keys, research only.

Two things this adapter has to get right, because the funding robot's whole edge
condition depends on them:

1. **Pagination.** `fapi/v1/fundingRate` caps a page at 1000 settlements. At the
   usual three 8-hour settlements a day that is ~333 days, so a single request
   silently truncates any longer window — measured: a 400-day window returns
   exactly 1000 rows starting at the window edge, and the remaining 200 are
   dropped without a word.
2. **A real index price.** The funding response carries `markPrice` and *no*
   `indexPrice`. Defaulting index to mark makes `(mark - index) / index` exactly
   zero, so the `basis_max` gate can never fire. The index comes from a separate
   endpoint (`fapi/v1/indexPriceKlines`) and is joined on the settlement hour; when
   the join misses, `index_price` is left as `None` rather than faked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from nautilus_lab.domain.funding import FundingSnapshot
from nautilus_lab.domain.ports import JsonHttpClient

FUNDING_RATE_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
INDEX_PRICE_KLINES_URL = "https://fapi.binance.com/fapi/v1/indexPriceKlines"

_DEFAULT_PAGE_LIMIT = 1000
# 1h index klines align with every funding schedule Binance runs (1h, 4h and 8h),
# so one series serves all symbols instead of assuming an 8-hour cadence.
_INDEX_INTERVAL = "1h"
_MAX_PAGES = 64


class BinancePublicFunding:
    """Paginated funding settlements with an index price joined per settlement."""

    def __init__(
        self,
        client: JsonHttpClient | None = None,
        *,
        page_limit: int = _DEFAULT_PAGE_LIMIT,
        with_index_prices: bool = True,
    ) -> None:
        if page_limit < 1:
            raise ValueError("page_limit must be >= 1")
        if client is None:
            from nautilus_lab.infrastructure.http_resilience import ResilientJsonClient

            client = ResilientJsonClient()
        self._client = client
        self._page_limit = page_limit
        self._with_index_prices = with_index_prices

    def fetch_history(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[FundingSnapshot]:
        if start >= end:
            raise ValueError("start must be before end")
        rows = self._fetch_funding_rows(symbol=symbol, start=start, end=end)
        if not rows:
            return []
        index_by_hour: dict[datetime, Decimal] = {}
        if self._with_index_prices:
            index_by_hour = self._fetch_index_prices(symbol=symbol, start=start, end=end)
        snapshots: list[FundingSnapshot] = []
        for ts, rate, mark in rows:
            index = index_by_hour.get(_floor_to_hour(ts))
            snapshots.append(
                FundingSnapshot(
                    instrument=symbol,
                    funding_rate=rate,
                    mark_price=mark,
                    index_price=index,
                    ts_utc=ts,
                )
            )
        snapshots.sort(key=lambda item: item.ts_utc)
        return snapshots

    def _fetch_funding_rows(
        self, *, symbol: str, start: datetime, end: datetime
    ) -> list[tuple[datetime, Decimal, Decimal]]:
        rows: list[tuple[datetime, Decimal, Decimal]] = []
        seen: set[datetime] = set()
        cursor = start
        for _ in range(_MAX_PAGES):
            payload = self._client.get_json(
                FUNDING_RATE_URL,
                {
                    "symbol": symbol,
                    "startTime": str(_to_ms(cursor)),
                    "endTime": str(_to_ms(end) - 1),
                    "limit": str(self._page_limit),
                },
            )
            page = _as_list(payload)
            if not page:
                break
            last_ms: int | None = None
            for item in page:
                parsed = _parse_funding_row(item, symbol=symbol, start=start, end=end)
                if parsed is None:
                    continue
                ts, rate, mark = parsed
                last_ms = max(last_ms or _to_ms(ts), _to_ms(ts))
                if ts in seen:
                    continue
                seen.add(ts)
                rows.append((ts, rate, mark))
            if last_ms is None or len(page) < self._page_limit:
                break
            # Advance past the last settlement. Without the +1 ms the next page
            # repeats it and the loop never makes progress.
            next_cursor = datetime.fromtimestamp((last_ms + 1) / 1000, tz=UTC)
            if next_cursor <= cursor:
                break
            cursor = next_cursor
        return rows

    def _fetch_index_prices(
        self, *, symbol: str, start: datetime, end: datetime
    ) -> dict[datetime, Decimal]:
        """Index price at each hour, keyed by bar open time.

        The bar that *opens* at the settlement instant carries that instant's index
        price in its open field, which is why the join is on the open hour.
        """
        prices: dict[datetime, Decimal] = {}
        cursor = start
        for _ in range(_MAX_PAGES):
            payload = self._client.get_json(
                INDEX_PRICE_KLINES_URL,
                {
                    "pair": symbol,
                    "interval": _INDEX_INTERVAL,
                    "startTime": str(_to_ms(cursor)),
                    "endTime": str(_to_ms(end) - 1),
                    "limit": str(self._page_limit),
                },
            )
            page = _as_list(payload)
            if not page:
                break
            last_open_ms: int | None = None
            for item in page:
                if not isinstance(item, list) or len(item) < 2:
                    continue
                open_ms = int(str(item[0]))
                last_open_ms = open_ms
                opened_at = datetime.fromtimestamp(open_ms / 1000, tz=UTC)
                if opened_at < start or opened_at >= end:
                    continue
                try:
                    prices[opened_at] = Decimal(str(item[1]))
                except InvalidOperation:
                    continue
            if last_open_ms is None or len(page) < self._page_limit:
                break
            next_cursor = datetime.fromtimestamp((last_open_ms + 1000) / 1000, tz=UTC)
            if next_cursor <= cursor:
                break
            cursor = next_cursor
        return prices


def _parse_funding_row(
    item: object, *, symbol: str, start: datetime, end: datetime
) -> tuple[datetime, Decimal, Decimal] | None:
    """Parse one settlement. Returns None for anything malformed or out of window.

    `mark_price` is required: without it there is no basis at all, and inventing one
    from `fundingRate` (as the previous fallback chain did) would be a fabricated
    price rather than a missing one.
    """
    if not isinstance(item, dict):
        return None
    raw_ts = item.get("fundingTime")
    raw_rate = item.get("fundingRate")
    raw_mark = item.get("markPrice")
    if raw_ts is None or raw_rate is None or raw_mark is None:
        return None
    ts = datetime.fromtimestamp(int(str(raw_ts)) / 1000, tz=UTC)
    if ts < start or ts >= end:
        return None
    try:
        return ts, Decimal(str(raw_rate)), Decimal(str(raw_mark))
    except InvalidOperation:
        return None


def _as_list(payload: object) -> list[Any]:
    return list(payload) if isinstance(payload, list) else []


def _to_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _floor_to_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


__all__ = [
    "FUNDING_RATE_URL",
    "INDEX_PRICE_KLINES_URL",
    "BinancePublicFunding",
]
