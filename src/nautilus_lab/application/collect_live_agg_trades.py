"""Collect live aggregated trades from the public WebSocket into the Parquet catalog.

Why this exists next to the REST ingest: the REST path cannot deliver tick history at
research scale. Measured 2026-09-23 — one page is 1000 trades covering ~120 seconds of
ETHUSDT market time, so a day is ~720 pages, and a substantial share of pages stall and
never answer. Four live REST runs (four days, one day, two hours, thirty minutes) wrote
nothing at all.

The WebSocket has no such problem: it pushes every trade as it prints, needs no keys,
and — unlike history — it accumulates while you wait. This collector therefore trades
latency for feasibility: it cannot give you last year's ticks, but it gives you real
ticks from now on, which is what a live paper session and a microstructure feature
actually need.

Batching is deliberate. Flushing every `batch_size` trades bounds memory and leaves
everything already collected on disk if the process is killed; the catalog deduplicates
by `agg_id`, so a restart continues rather than doubles.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from nautilus_lab.domain.ports import AggTradesCatalog
from nautilus_lab.domain.ticks import AggTrade


class LiveAggTradeSource(Protocol):
    """Anything that yields live trades in increasing `agg_id` order and can be stopped."""

    def trades(self) -> Iterator[AggTrade]: ...

    def stop(self) -> None: ...


# Called after each flush with the running total and the last trade's timestamp.
CollectProgress = Callable[[int, datetime | None], None]


@dataclass(frozen=True, slots=True)
class LiveTickReport:
    symbol: str
    trades_written: int
    batches: int
    first_ts: datetime | None
    last_ts: datetime | None
    catalog_path: str
    stopped_reason: str

    def summary_line(self) -> str:
        window = (
            "n/a"
            if self.first_ts is None or self.last_ts is None
            else f"[{self.first_ts.isoformat()}, {self.last_ts.isoformat()}]"
        )
        return (
            f"live ticks symbol={self.symbol} trades={self.trades_written} "
            f"batches={self.batches} window={window} stop={self.stopped_reason} "
            f"catalog={self.catalog_path}"
        )


class CollectLiveAggTrades:
    """Stream live trades into the catalog until a deadline or a trade cap is reached.

    Both limits are honoured because either one alone can fail: a dead market makes a
    duration limit sit idle, and a busy one makes a trade cap finish in seconds. The
    caller decides which one it cares about and passes both.
    """

    def __init__(
        self,
        source: LiveAggTradeSource,
        catalog: AggTradesCatalog,
        *,
        symbol: str,
        catalog_path: str = "",
        batch_size: int = 5000,
        now: Callable[[], datetime] | None = None,
        progress: CollectProgress | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self._source = source
        self._catalog = catalog
        self._symbol = symbol
        self._catalog_path = catalog_path
        self._batch_size = batch_size
        self._now = now or (lambda: datetime.now(UTC))
        self._progress = progress

    def execute(
        self,
        *,
        duration: timedelta | None = None,
        max_trades: int | None = None,
    ) -> LiveTickReport:
        if duration is None and max_trades is None:
            raise ValueError(
                "set duration, max_trades, or both; an unbounded collection never returns"
            )
        if duration is not None and duration <= timedelta(0):
            raise ValueError("duration must be positive")
        if max_trades is not None and max_trades < 1:
            raise ValueError("max_trades must be >= 1")

        deadline = None if duration is None else self._now() + duration
        buffer: list[AggTrade] = []
        written = 0
        batches = 0
        first_ts: datetime | None = None
        last_ts: datetime | None = None
        stopped_reason = "trade cap reached"
        try:
            for trade in self._source.trades():
                buffer.append(trade)
                first_ts = trade.ts_utc if first_ts is None else first_ts
                last_ts = trade.ts_utc
                if len(buffer) >= self._batch_size:
                    written += self._flush(buffer)
                    batches += 1
                    if self._progress is not None:
                        self._progress(written, last_ts)
                if max_trades is not None and written + len(buffer) >= max_trades:
                    break
                if deadline is not None and self._now() >= deadline:
                    stopped_reason = "duration reached"
                    break
        finally:
            # Whatever arrived before the deadline is data, not scratch: flush it.
            if buffer:
                written += self._flush(buffer)
                batches += 1
                if self._progress is not None:
                    self._progress(written, last_ts)
            self._source.stop()

        if written == 0:
            raise ValueError(
                f"no aggTrades arrived on the stream for {self._symbol} within the "
                "collection window; nothing was written (an empty series must not look "
                "like a collected one)"
            )
        return LiveTickReport(
            symbol=self._symbol,
            trades_written=written,
            batches=batches,
            first_ts=first_ts,
            last_ts=last_ts,
            catalog_path=self._catalog_path,
            stopped_reason=stopped_reason,
        )

    def _flush(self, buffer: list[AggTrade]) -> int:
        count = self._catalog.write(list(buffer), symbol=self._symbol)
        buffer.clear()
        return count
