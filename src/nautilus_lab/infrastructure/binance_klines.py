from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from nautilus_lab.domain.bars import OhlcvBar, validate_bar
from nautilus_lab.domain.ports import JsonHttpClient

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
_PAGE_LIMIT = 1000
_HTTP_TIMEOUT_SECONDS = 30


class UrllibJsonClient:
    def get_json(self, url: str, params: Mapping[str, str]) -> object:
        request = Request(
            f"{url}?{urlencode(params)}",
            headers={"User-Agent": "nautilus-lab/research"},
        )
        with urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
            payload = response.read()
        return json.loads(payload.decode())


class BinancePublicKlines:
    """Spot klines. Public REST, no API keys, research only."""

    def __init__(
        self,
        http: JsonHttpClient | None = None,
        *,
        now: datetime | None = None,
        page_limit: int = _PAGE_LIMIT,
    ) -> None:
        self._http = http or UrllibJsonClient()
        self._now = now
        self._page_limit = page_limit

    def fetch(
        self,
        *,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        instrument_id: str,
    ) -> list[OhlcvBar]:
        if start >= end:
            raise ValueError("start must be before end")
        clock = self._now or datetime.now(UTC)
        bars: list[OhlcvBar] = []
        previous_ts: datetime | None = None
        cursor = start
        while cursor < end:
            payload = self._http.get_json(
                BINANCE_KLINES_URL,
                {
                    "symbol": symbol,
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
                bar = parse_binance_kline(row, instrument_id=instrument_id)
                last_open_ms = int(str(row[0]))
                if bar.ts_utc < start or bar.ts_utc >= end:
                    continue
                validate_bar(bar, previous_ts=previous_ts, now=clock)
                bars.append(bar)
                previous_ts = bar.ts_utc
            if last_open_ms is None or len(rows) < self._page_limit:
                break
            cursor = datetime.fromtimestamp((last_open_ms + 1) / 1000, tz=UTC)
            if cursor <= start:
                cursor = start + timedelta(milliseconds=1)
        return bars


def parse_binance_kline(row: object, *, instrument_id: str) -> OhlcvBar:
    if not isinstance(row, list) or len(row) < 7:
        raise ValueError("binance kline row must be a list with at least 7 fields")
    close_ms = int(row[6])
    # Field 9 is `takerBuyBaseAssetVolume`: the base volume aggressive buyers took in
    # this bar. It is the only real maker/taker split a kline carries, and dropping it
    # forces every order-flow feature onto the tick-rule proxy (defect D4 in
    # docs/23-infrastruktura-danyh-plan.md). Rows shorter than 10 fields cannot answer
    # the question, so the field stays None — unknown, rather than assumed zero.
    taker_buy = Decimal(str(row[9])) if len(row) > 9 else None
    return OhlcvBar(
        instrument_id=instrument_id,
        ts_utc=datetime.fromtimestamp(close_ms / 1000, tz=UTC),
        open=Decimal(str(row[1])),
        high=Decimal(str(row[2])),
        low=Decimal(str(row[3])),
        close=Decimal(str(row[4])),
        volume=Decimal(str(row[5])),
        taker_buy_base_volume=taker_buy,
    )


def _as_rows(payload: object) -> list[list[object]]:
    if isinstance(payload, dict):
        raise ValueError(f"binance klines error: {payload}")
    if not isinstance(payload, list):
        raise ValueError("binance klines response must be a list")
    rows: list[list[object]] = []
    for item in payload:
        if not isinstance(item, list):
            raise ValueError("binance kline row must be a list")
        rows.append(item)
    return rows
