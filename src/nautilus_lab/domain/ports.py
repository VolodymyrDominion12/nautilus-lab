from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.funding import FundingSnapshot
from nautilus_lab.domain.order_book import OrderBookSnapshot


class PublicBarFeed(Protocol):
    """Public historical OHLCV. No credentials, no orders."""

    def fetch(
        self,
        *,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        instrument_id: str,
    ) -> list[OhlcvBar]: ...


class BarCatalog(Protocol):
    """Nautilus Parquet catalog of closed bars."""

    def write(self, bars: Sequence[OhlcvBar], *, bar_type: str, instrument_id: str) -> int: ...

    def load(
        self,
        *,
        bar_type: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[OhlcvBar]: ...


class JsonHttpClient(Protocol):
    """GET JSON. Used by public market-data adapters."""

    def get_json(self, url: str, params: Mapping[str, str]) -> object: ...


class FundingRateFeed(Protocol):
    def fetch_history(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[FundingSnapshot]: ...


class OrderBookSnapshotFeed(Protocol):
    def fetch_snapshot(self, *, symbol: str) -> OrderBookSnapshot: ...
