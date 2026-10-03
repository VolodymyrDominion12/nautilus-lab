"""Public Binance USD-M premium index klines. No API keys, research only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from nautilus_lab.domain.errors import HistoryTruncatedError
from nautilus_lab.domain.ports import JsonHttpClient
from nautilus_lab.domain.premium_index import PremiumIndexBar

PREMIUM_INDEX_KLINES_URL = "https://fapi.binance.com/fapi/v1/premiumIndexKlines"
_DEFAULT_PAGE_LIMIT = 1000
_MAX_PAGES = 500


class BinancePublicPremiumIndex:
    """Fetch paginated premium index candles from Binance USD-M futures."""

    def __init__(
        self,
        client: JsonHttpClient | None = None,
        *,
        page_limit: int = _DEFAULT_PAGE_LIMIT,
        now: datetime | None = None,
    ) -> None:
        if page_limit < 1:
            raise ValueError("page_limit must be >= 1")
        if client is None:
            from nautilus_lab.infrastructure.http_resilience import ResilientJsonClient

            client = ResilientJsonClient()
        self._client = client
        self._page_limit = page_limit
        self._now = now

    def fetch(
        self,
        *,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> list[PremiumIndexBar]:
        if start >= end:
            raise ValueError("start must be before end")
        clock = self._now or datetime.now(UTC)
        query_symbol = symbol.removesuffix("-PERP").upper()
        bars: list[PremiumIndexBar] = []
        cursor = start

        for _ in range(_MAX_PAGES):
            if cursor >= end:
                break
            payload = self._client.get_json(
                PREMIUM_INDEX_KLINES_URL,
                {
                    "symbol": query_symbol,
                    "interval": interval,
                    "startTime": str(int(cursor.timestamp() * 1000)),
                    "endTime": str(int(end.timestamp() * 1000) - 1),
                    "limit": str(self._page_limit),
                },
            )
            rows = _as_rows(payload)
            if not rows:
                break
            last_open_ms: int | None = None
            for row in rows:
                if len(row) < 7:
                    continue
                last_open_ms = int(str(row[0]))
                close_ms = int(str(row[6]))
                bar_ts = datetime.fromtimestamp(close_ms / 1000, tz=UTC)
                if bar_ts < start or bar_ts >= end:
                    continue
                if bar_ts > clock:
                    continue  # skip candle in progress
                bars.append(
                    PremiumIndexBar(
                        symbol=query_symbol,
                        interval=interval,
                        ts_utc=bar_ts,
                        open=Decimal(str(row[1])),
                        high=Decimal(str(row[2])),
                        low=Decimal(str(row[3])),
                        close=Decimal(str(row[4])),
                    )
                )
            if last_open_ms is None or len(rows) < self._page_limit:
                break
            cursor = datetime.fromtimestamp((last_open_ms + 1) / 1000, tz=UTC)
            if cursor <= start:
                cursor = start + timedelta(milliseconds=1)
        else:
            # The budget ran out on a full page: the exchange still has candles. A
            # short series stored as if complete is worse than a failed ingest.
            if cursor < end:
                raise HistoryTruncatedError(
                    f"premiumIndexKlines for {query_symbol} {interval} still had rows "
                    f"after {_MAX_PAGES} pages (stopped at {cursor.isoformat()})"
                )

        # Deduplicate and sort defensively
        unique: dict[datetime, PremiumIndexBar] = {bar.ts_utc: bar for bar in bars}
        return [unique[key] for key in sorted(unique)]


def _as_rows(payload: object) -> list[list[Any]]:
    if isinstance(payload, dict):
        raise ValueError(f"binance premiumIndexKlines error: {payload}")
    if not isinstance(payload, list):
        raise ValueError("binance premiumIndexKlines response must be a list")
    return [item for item in payload if isinstance(item, list)]
