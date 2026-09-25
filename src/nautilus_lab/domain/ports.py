from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from nautilus_lab.domain.decision_log import DecisionRecord

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.funding import FundingSnapshot
from nautilus_lab.domain.order_book import OrderBookSnapshot
from nautilus_lab.domain.ticks import AggTrade


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


@dataclass(frozen=True, slots=True)
class JsonResponse:
    """A raw HTTP outcome, including the headers a rate-limit policy needs.

    Status is carried as data rather than raised, so a retry policy can decide what
    to do with 429/418 instead of the transport deciding for it.
    """

    status: int
    headers: Mapping[str, str]
    payload: object


class JsonTransport(Protocol):
    """One HTTP GET, no retries. The layer that owns the socket, nothing more."""

    def get(self, url: str, params: Mapping[str, str]) -> JsonResponse: ...


class FundingRateFeed(Protocol):
    def fetch_history(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[FundingSnapshot]: ...


class FundingCatalog(Protocol):
    """Time series of funding settlements, stored beside the bar series.

    Not a `BarCatalog`: funding is an event series, not OHLCV, so it gets its own
    storage contract keyed by settlement timestamp.
    """

    def write(self, snapshots: Sequence[FundingSnapshot], *, symbol: str) -> int: ...

    def load(
        self,
        *,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[FundingSnapshot]: ...


class TakerFlowCatalog(Protocol):
    """Per-bar taker-buy volume, stored beside the bar series.

    Not a `BarCatalog` and not part of `OhlcvBar`'s storage: Nautilus `Bar` has no
    field for it, so it is kept as its own series keyed by `(symbol, interval)` and the
    bar close timestamp, then joined back by the research feed. The interval is part of
    the key because an hourly and a daily bar share a close at 23:59:59.999; without it
    the two series would overwrite each other. Reading a symbol with no such series
    returns an empty mapping — an unknown split, not a zero one.
    """

    def write(self, bars: Sequence[OhlcvBar], *, symbol: str, interval: str) -> int: ...

    def load(
        self,
        *,
        symbol: str,
        interval: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Mapping[datetime, Decimal]: ...


class OrderBookSnapshotFeed(Protocol):
    def fetch_snapshot(self, *, symbol: str) -> OrderBookSnapshot: ...


class AggTradesFeed(Protocol):
    """Public aggregated-trade history. No credentials, research only.

    One call returns a contiguous slice of the aggTrades series for one symbol.
    The implementation must paginate transparently so that callers see a single
    flat list, ordered by ``agg_id`` (Binance's guarantee).
    """

    def fetch(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        instrument_id: str,
    ) -> list[AggTrade]: ...


class AggTradesCatalog(Protocol):
    """Parquet storage for aggregated trades beside the bar series."""

    def write(self, trades: Sequence[AggTrade], *, symbol: str) -> int: ...

    def load(
        self,
        *,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[AggTrade]: ...


class ChatCompleter(Protocol):
    """Text completion from a language model.

    OFFLINE RESEARCH ONLY. This port exists so the alpha-proposal loop can be tested
    without a network, and so no strategy can reach a model by accident: nothing in
    the backtest or execution path may depend on it (docs/14-llm-model-u-torhivli.md).
    """

    def complete(self, *, system: str, user: str) -> str: ...


class DecisionLogPort(Protocol):
    """Writes detailed decision records for offline analysis and frontend visualization."""

    def log(self, record: DecisionRecord) -> None: ...
