"""Public Binance USD-M funding history. No API keys, research only.

Things this adapter has to get right, because the funding robot's whole edge
condition depends on them:

1. **Pagination.** `fapi/v1/fundingRate` caps a page at 1000 settlements. At the
   usual three 8-hour settlements a day that is ~333 days, so a single request
   silently truncates any longer window — measured: a 400-day window returns
   exactly 1000 rows starting at the window edge, and the remaining 200 are
   dropped without a word. Running out of the page budget while the exchange still
   has rows raises `HistoryTruncatedError` instead of returning a short series.
2. **A real index price.** The funding response carries `markPrice` and *no*
   `indexPrice`. Defaulting index to mark makes `(mark - index) / index` exactly
   zero, so the `basis_max` gate can never fire. The index comes from a separate
   endpoint (`fapi/v1/indexPriceKlines`) and is joined on the settlement hour; when
   the join misses, `index_price` is left as `None` rather than faked.
3. **Old settlements have no mark.** For settlements before late 2023 the endpoint
   returns `markPrice: ""`. The previous parser required a mark and dropped those
   rows silently — every ingested series began on 2023-10-31 although 2020 was
   requested. A settlement is its time and rate; the mark is now optional, filled
   from `fapi/v1/markPriceKlines` on the settlement hour when the response lacks it,
   and left `None` (never invented) when that join misses too.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from nautilus_lab.domain.errors import HistoryTruncatedError
from nautilus_lab.domain.funding import FundingSnapshot
from nautilus_lab.domain.ports import JsonHttpClient

FUNDING_RATE_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
INDEX_PRICE_KLINES_URL = "https://fapi.binance.com/fapi/v1/indexPriceKlines"
MARK_PRICE_KLINES_URL = "https://fapi.binance.com/fapi/v1/markPriceKlines"

_DEFAULT_PAGE_LIMIT = 1000
# 1h klines align with every funding schedule Binance runs (1h, 4h and 8h), so one
# series serves all symbols instead of assuming an 8-hour cadence.
_PRICE_INTERVAL = "1h"
_HOUR = timedelta(hours=1)
# Page budgets. They bound a runaway loop; they are not a data limit. Hitting one
# with a full last page raises. Funding: 64 x 1000 settlements is ~58 years at 8h.
# Hourly prices: 64 pages was ~7.3 years and the 2020-2026 window already needed ~59,
# so the budget is sized for decades, not for today's window.
_MAX_FUNDING_PAGES = 64
_MAX_PRICE_PAGES = 1000


@dataclass(frozen=True, slots=True)
class FundingFetchStats:
    """What the last `fetch_history` call saw and what it could not keep or fill."""

    rows_seen: int = 0
    #: Rows without a usable time or rate. The only rows that are ever dropped.
    dropped_malformed: int = 0
    #: Settlements whose response had no mark price (pre-2023 history).
    mark_from_klines: int = 0
    #: Settlements whose mark stayed unknown after the kline join.
    missing_mark_price: int = 0


class BinancePublicFunding:
    """Paginated funding settlements with mark and index prices joined per settlement."""

    def __init__(
        self,
        client: JsonHttpClient | None = None,
        *,
        page_limit: int = _DEFAULT_PAGE_LIMIT,
        with_index_prices: bool = True,
        with_mark_prices: bool = True,
        max_funding_pages: int = _MAX_FUNDING_PAGES,
        max_price_pages: int = _MAX_PRICE_PAGES,
    ) -> None:
        if page_limit < 1:
            raise ValueError("page_limit must be >= 1")
        if max_funding_pages < 1 or max_price_pages < 1:
            raise ValueError("page budgets must be >= 1")
        if client is None:
            from nautilus_lab.infrastructure.http_resilience import ResilientJsonClient

            client = ResilientJsonClient()
        self._client = client
        self._page_limit = page_limit
        self._with_index_prices = with_index_prices
        self._with_mark_prices = with_mark_prices
        self._max_funding_pages = max_funding_pages
        self._max_price_pages = max_price_pages
        self.last_stats = FundingFetchStats()

    def fetch_history(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[FundingSnapshot]:
        if start >= end:
            raise ValueError("start must be before end")
        clean_symbol = symbol.removesuffix("-PERP")
        rows, seen, dropped = self._fetch_funding_rows(symbol=clean_symbol, start=start, end=end)
        self.last_stats = FundingFetchStats(rows_seen=seen, dropped_malformed=dropped)
        if not rows:
            return []
        index_by_hour: dict[datetime, Decimal] = {}
        if self._with_index_prices:
            index_by_hour = self._fetch_hourly_opens(
                INDEX_PRICE_KLINES_URL, {"pair": clean_symbol}, start=start, end=end
            )
        mark_by_hour: dict[datetime, Decimal] = {}
        unmarked = [ts for ts, _rate, mark in rows if mark is None]
        if self._with_mark_prices and unmarked:
            # Only the span that lacks a mark: for a 2020-2026 window this is the
            # pre-2023 part, not the whole history a second time.
            mark_by_hour = self._fetch_hourly_opens(
                MARK_PRICE_KLINES_URL,
                {"symbol": clean_symbol},
                start=_floor_to_hour(min(unmarked)),
                end=min(end, _floor_to_hour(max(unmarked)) + _HOUR),
            )
        snapshots: list[FundingSnapshot] = []
        from_klines = 0
        for ts, rate, mark in rows:
            hour = _floor_to_hour(ts)
            if mark is None:
                mark = mark_by_hour.get(hour)
                if mark is not None:
                    from_klines += 1
            snapshots.append(
                FundingSnapshot(
                    instrument=clean_symbol,
                    funding_rate=rate,
                    mark_price=mark,
                    index_price=index_by_hour.get(hour),
                    ts_utc=ts,
                )
            )
        snapshots.sort(key=lambda item: item.ts_utc)
        self.last_stats = FundingFetchStats(
            rows_seen=seen,
            dropped_malformed=dropped,
            mark_from_klines=from_klines,
            missing_mark_price=sum(1 for item in snapshots if item.mark_price is None),
        )
        return snapshots

    def _fetch_funding_rows(
        self, *, symbol: str, start: datetime, end: datetime
    ) -> tuple[list[tuple[datetime, Decimal, Decimal | None]], int, int]:
        rows: list[tuple[datetime, Decimal, Decimal | None]] = []
        seen_ts: set[datetime] = set()
        seen = 0
        dropped = 0
        cursor = start
        for _ in range(self._max_funding_pages):
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
                return rows, seen, dropped
            last_ms: int | None = None
            for item in page:
                seen += 1
                if isinstance(item, dict) and "fundingTime" in item:
                    try:
                        item_ts = int(str(item["fundingTime"]))
                    except ValueError:
                        item_ts = None
                    if item_ts is not None:
                        last_ms = item_ts if last_ms is None else max(last_ms, item_ts)
                parsed = _parse_funding_row(item, start=start, end=end)
                if isinstance(parsed, _Malformed):
                    dropped += 1
                    continue
                if parsed is None:
                    continue  # outside the window: not data for this request
                ts, rate, mark = parsed
                if ts in seen_ts:
                    continue
                seen_ts.add(ts)
                rows.append((ts, rate, mark))
            if last_ms is None or len(page) < self._page_limit:
                return rows, seen, dropped
            # Advance past the last settlement. Without the +1 ms the next page
            # repeats it and the loop never makes progress.
            next_cursor = datetime.fromtimestamp((last_ms + 1) / 1000, tz=UTC)
            if next_cursor <= cursor or next_cursor >= end:
                return rows, seen, dropped
            cursor = next_cursor
        raise HistoryTruncatedError(
            f"funding history for {symbol} still had rows after {self._max_funding_pages} "
            f"pages (stopped at {cursor.isoformat()}); narrow the window or raise the budget"
        )

    def _fetch_hourly_opens(
        self,
        url: str,
        symbol_param: dict[str, str],
        *,
        start: datetime,
        end: datetime,
    ) -> dict[datetime, Decimal]:
        """Open price of each 1h bar, keyed by bar open time.

        The bar that *opens* at the settlement instant carries that instant's price in
        its open field, which is why the join is on the open hour.
        """
        prices: dict[datetime, Decimal] = {}
        if start >= end:
            return prices
        cursor = start
        for _ in range(self._max_price_pages):
            payload = self._client.get_json(
                url,
                {
                    **symbol_param,
                    "interval": _PRICE_INTERVAL,
                    "startTime": str(_to_ms(cursor)),
                    "endTime": str(_to_ms(end) - 1),
                    "limit": str(self._page_limit),
                },
            )
            page = _as_list(payload)
            if not page:
                return prices
            last_open_ms: int | None = None
            for item in page:
                if not isinstance(item, list) or len(item) < 2:
                    continue
                open_ms = int(str(item[0]))
                last_open_ms = open_ms
                opened_at = datetime.fromtimestamp(open_ms / 1000, tz=UTC)
                if opened_at < start or opened_at >= end:
                    continue
                price = _positive_decimal(item[1])
                if price is not None:
                    prices[opened_at] = price
            if last_open_ms is None or len(page) < self._page_limit:
                return prices
            next_cursor = datetime.fromtimestamp((last_open_ms + 1000) / 1000, tz=UTC)
            if next_cursor <= cursor or next_cursor >= end:
                return prices
            cursor = next_cursor
        raise HistoryTruncatedError(
            f"{url.rsplit('/', 1)[-1]} for {next(iter(symbol_param.values()))} still had rows "
            f"after {self._max_price_pages} pages (stopped at {cursor.isoformat()})"
        )


class _Malformed:
    """Sentinel: the row is broken (no usable time or rate), as opposed to out of window."""


_MALFORMED = _Malformed()


def _parse_funding_row(
    item: object, *, start: datetime, end: datetime
) -> tuple[datetime, Decimal, Decimal | None] | _Malformed | None:
    """Parse one settlement.

    Returns `_MALFORMED` for a row with no usable time or rate, `None` for a row outside
    the window, and otherwise `(ts, rate, mark)` where `mark` is None when the response
    carries none (empty string on pre-2023 history) or an unusable one. The mark is
    never derived from the rate: a missing price stays missing.
    """
    if not isinstance(item, dict):
        return _MALFORMED
    raw_ts = item.get("fundingTime")
    raw_rate = item.get("fundingRate")
    if raw_ts is None or raw_rate is None:
        return _MALFORMED
    try:
        ts = datetime.fromtimestamp(int(str(raw_ts)) / 1000, tz=UTC)
        rate = Decimal(str(raw_rate))
    except (ValueError, InvalidOperation):
        return _MALFORMED
    if not rate.is_finite():
        return _MALFORMED
    if ts < start or ts >= end:
        return None
    return ts, rate, _positive_decimal(item.get("markPrice"))


def _positive_decimal(raw: object) -> Decimal | None:
    """A strictly positive finite price, or None for empty / malformed / non-positive."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if not value.is_finite() or value <= 0:
        return None
    return value


def _as_list(payload: object) -> list[Any]:
    return list(payload) if isinstance(payload, list) else []


def _to_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _floor_to_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


__all__ = [
    "FUNDING_RATE_URL",
    "INDEX_PRICE_KLINES_URL",
    "MARK_PRICE_KLINES_URL",
    "BinancePublicFunding",
    "FundingFetchStats",
]
