"""Ingest aggregated trades (Binance public ticks) into the Parquet catalog.

Day by day, and each day is written as soon as it is fetched. That is not a detail:
an earlier version pulled the whole requested window into memory and persisted only
after the final page, so a four-day window produced nothing on disk after fifty
minutes of fetching, and a one-year window could never have finished at all. Writing
per day also makes the job resumable (a restart re-fetches days, and the catalog
deduplicates by `agg_id`) and bounded in memory, which is the difference between a
slow ingest and an impossible one.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

from nautilus_lab.application.dtos import IngestAggTradesReport, IngestAggTradesRequest
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.domain.errors import CatalogEmptyError
from nautilus_lab.domain.ports import AggTradesCatalog, AggTradesFeed

# Called after each stored day with the day's start and how many trades it held.
DayProgress = Callable[[datetime, int], None]


class IngestAggTrades:
    """Fetch public aggregated trades and store them, one UTC day at a time."""

    def __init__(
        self,
        feed: AggTradesFeed,
        catalog: AggTradesCatalog,
        *,
        catalog_path: str = "",
        progress: DayProgress | None = None,
    ) -> None:
        self._feed = feed
        self._catalog = catalog
        self._catalog_path = catalog_path
        self._progress = progress

    def execute(self, request: IngestAggTradesRequest) -> IngestAggTradesReport:
        require_simulated_mode(request.mode)
        if request.start >= request.end:
            raise ValueError("ingest start must be before end")

        written = 0
        first_ts: datetime | None = None
        last_ts: datetime | None = None
        for day_start, day_end in utc_days(request.start, request.end):
            trades = self._feed.fetch(
                symbol=request.symbol,
                start=day_start,
                end=day_end,
                instrument_id=request.instrument_id,
            )
            if not trades:
                # A quiet day is not a failure: Binance has days with no prints for
                # thin symbols, and stopping the whole window over one of them would
                # make an otherwise good ingest look broken.
                if self._progress is not None:
                    self._progress(day_start, 0)
                continue
            written += self._catalog.write(trades, symbol=request.symbol)
            first_ts = trades[0].ts_utc if first_ts is None else first_ts
            last_ts = trades[-1].ts_utc
            if self._progress is not None:
                self._progress(day_start, len(trades))

        if first_ts is None or last_ts is None:
            raise CatalogEmptyError(
                f"no public aggTrades for {request.symbol} "
                f"in [{request.start.isoformat()}, {request.end.isoformat()}). "
                f"Check the symbol name and date range."
            )

        return IngestAggTradesReport(
            trades_written=written,
            first_ts=first_ts,
            last_ts=last_ts,
            catalog_path=self._catalog_path,
            source="binance public aggTrades (no API keys)",
            symbol=request.symbol,
        )


def utc_days(start: datetime, end: datetime) -> Iterator[tuple[datetime, datetime]]:
    """Yield `[day_start, day_end)` slices of `[start, end)`, cut on UTC midnight.

    The first and last slices are clipped to the request, so a window that starts at
    15:00 fetches from 15:00, not from midnight — the caller asked for a window, not
    for whole days.
    """
    if start >= end:
        raise ValueError("start must be before end")
    cursor = start
    while cursor < end:
        midnight = datetime.combine(
            (cursor + timedelta(days=1)).date(), datetime.min.time(), tzinfo=UTC
        )
        slice_end = min(midnight, end)
        yield cursor, slice_end
        cursor = slice_end
