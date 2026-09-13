from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from nautilus_lab.domain.funding import FundingSnapshot
from nautilus_lab.domain.ports import JsonHttpClient

_BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"


class BinancePublicFunding:
    """Public Binance USD-M funding history. No API keys."""

    def __init__(self, client: JsonHttpClient | None = None) -> None:
        from nautilus_lab.infrastructure.binance_klines import UrllibJsonClient

        self._client = client or UrllibJsonClient()

    def fetch_history(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[FundingSnapshot]:
        params = {
            "symbol": symbol,
            "startTime": str(int(start.timestamp() * 1000)),
            "endTime": str(int(end.timestamp() * 1000)),
            "limit": "1000",
        }
        payload = self._client.get_json(_BINANCE_FUNDING_URL, params)
        if not isinstance(payload, list):
            return []
        snapshots: list[FundingSnapshot] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            ts = datetime.fromtimestamp(int(item["fundingTime"]) / 1000, tz=UTC)
            snapshots.append(
                FundingSnapshot(
                    instrument=symbol,
                    funding_rate=Decimal(str(item["fundingRate"])),
                    mark_price=Decimal(str(item.get("markPrice", item.get("fundingRate", "0")))),
                    index_price=Decimal(str(item.get("indexPrice", item.get("markPrice", "1")))),
                    ts_utc=ts,
                )
            )
        return snapshots
