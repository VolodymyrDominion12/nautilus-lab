from __future__ import annotations

from datetime import UTC, datetime

from nautilus_lab.domain.ports import JsonHttpClient
from nautilus_lab.domain.ticks import AggTrade

BINANCE_AGG_TRADES_URL = "https://api.binance.com/api/v3/aggTrades"
_PAGE_LIMIT = 1000
_HTTP_TIMEOUT_SECONDS = 30


class BinancePublicAggTrades:
    """Spot aggregated trades. Public REST, no API keys, research only.

    Binance ``/api/v3/aggTrades`` returns up to 1000 records per call and supports
    pagination via ``fromId`` (the first agg_id to return). This class transparently
    pages the whole requested window and returns a flat, sorted list.

    The same ``ResilientJsonClient`` used for klines is accepted here so that the
    caller can share one rate-limit-aware transport for both feeds.

    Rate limit note: each call costs 2 request weight. Binance's default bucket is
    1200 weight/minute on spot, so a large ingest (millions of trades) should use the
    resilient client's back-off to stay below the limit automatically.
    """

    def __init__(
        self,
        http: JsonHttpClient | None = None,
        *,
        now: datetime | None = None,
        page_limit: int = _PAGE_LIMIT,
    ) -> None:
        from nautilus_lab.infrastructure.binance_klines import UrllibJsonClient

        self._http = http or UrllibJsonClient()
        self._now = now
        self._page_limit = page_limit

    def fetch(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        instrument_id: str,
    ) -> list[AggTrade]:
        """Return all aggregated trades in [start, end).

        Pagination is transparent: the caller always sees one flat list sorted by
        ``agg_id``. Trades exactly at ``end`` are excluded (half-open interval), which
        matches the klines convention so that adjacent windows compose without gaps.
        """
        if start >= end:
            raise ValueError("start must be before end")

        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)  # exclusive upper bound

        trades: list[AggTrade] = []
        cursor_from_id: int | None = None

        while True:
            params: dict[str, str] = {
                "symbol": symbol,
                "limit": str(self._page_limit),
                "startTime": str(start_ms),
                "endTime": str(end_ms - 1),
            }
            if cursor_from_id is not None:
                # fromId takes precedence over startTime/endTime on Binance, so we
                # remove the time filters once we have an ID cursor - otherwise the
                # response could be empty when the cursor has moved past endTime but
                # there are still trades with that agg_id inside the window.
                del params["startTime"]
                del params["endTime"]
                params["fromId"] = str(cursor_from_id)

            payload = self._http.get_json(BINANCE_AGG_TRADES_URL, params)
            rows = _as_rows(payload)
            if not rows:
                break

            last_id: int | None = None
            for row in rows:
                trade = _parse_agg_trade_row(row, instrument_id=instrument_id)
                last_id = trade.agg_id
                # Honour the time window even when paginating via fromId.
                trade_ms = int(trade.ts_utc.timestamp() * 1000)
                if trade_ms < start_ms or trade_ms >= end_ms:
                    continue
                trades.append(trade)

            # Stop when we got a short page (last page) or when the last trade's
            # timestamp has gone past our window.
            if last_id is None or len(rows) < self._page_limit:
                break
            last_ts_ms = int(trades[-1].ts_utc.timestamp() * 1000) if trades else 0
            if last_ts_ms >= end_ms:
                break
            # Advance the cursor past the last received id.
            cursor_from_id = last_id + 1

        return trades


def _parse_agg_trade_row(row: object, *, instrument_id: str) -> AggTrade:
    """Parse one Binance aggTrades row into an ``AggTrade``.

    Binance JSON schema (array of objects, not arrays like klines)::

        {
          "a": 26129,         # Aggregate tradeId
          "p": "0.01633102",  # Price
          "q": "4.70443515",  # Quantity
          "f": 27781,         # First tradeId
          "l": 27781,         # Last tradeId
          "T": 1498793709153, # Timestamp (ms)
          "m": true,          # Was the buyer the maker?
          "M": true           # Was the trade the best price match?
        }
    """
    if not isinstance(row, dict):
        raise ValueError(f"aggTrade row must be a dict, got {type(row).__name__}")
    try:
        ts_ms = int(row["T"])
        ts_utc = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
        return AggTrade(
            instrument_id=instrument_id,
            ts_utc=ts_utc,
            agg_id=int(row["a"]),
            price=str(row["p"]),
            qty=str(row["q"]),
            is_buyer_maker=bool(row["m"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"cannot parse aggTrade row {row!r}: {exc}") from exc


def _as_rows(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, dict) and "code" in payload:
        raise ValueError(f"binance aggTrades error: {payload}")
    if not isinstance(payload, list):
        raise ValueError("binance aggTrades response must be a list")
    rows: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("binance aggTrade row must be a dict")
        rows.append(item)
    return rows


# Re-export for convenience: callers that import just this module can get the URL.
__all__ = ["BINANCE_AGG_TRADES_URL", "BinancePublicAggTrades"]
