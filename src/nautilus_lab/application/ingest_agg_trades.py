"""Ingest aggregated trades (Binance public ticks) into the Parquet catalog.

Slice by slice — one hour by default — and every slice is written as soon as it is
fetched. That is not a detail, it is the whole difference between a usable command and
a decorative one:

* an earlier version pulled the entire requested window into memory and persisted only
  after the final page, so a four-day window wrote nothing in fifty minutes and a
  one-year window could never have finished;
* a day-at-a-time version was still too coarse. Measured 2026-09-23: one Binance
  `aggTrades` page is 1000 trades covering ~120 seconds of ETHUSDT market time, so a
  day is ~720 pages and the whole day sat in RAM until page 720. A 30-minute run of
  one day produced no file at all.

Hourly slices bound memory, make progress observable, survive a kill (the catalog
deduplicates by `agg_id`, so a restart simply re-fetches the current slice), and keep
each fetch short enough that one stalled socket does not cost an entire day.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

from nautilus_lab.application.dtos import IngestAggTradesReport, IngestAggTradesRequest
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.domain.errors import CatalogEmptyError
from nautilus_lab.domain.ports import AggTradesCatalog, AggTradesFeed

# Called after each stored slice with the slice start and how many trades it held.
SliceProgress = Callable[[datetime, int], None]


class IngestAggTrades:
    """Fetch public aggregated trades and store them, one UTC day at a time."""

    def __init__(
        self,
        feed: AggTradesFeed,
        catalog: AggTradesCatalog,
        *,
        catalog_path: str = "",
        progress: SliceProgress | None = None,
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
        for slice_start, slice_end in utc_slices(request.start, request.end):
            trades = self._feed.fetch(
                symbol=request.symbol,
                start=slice_start,
                end=slice_end,
                instrument_id=request.instrument_id,
            )
            if not trades:
                # A quiet slice is not a failure: Binance has minutes with no prints for
                # thin symbols, and stopping the whole window over one of them would
                # make an otherwise good ingest look broken.
                if self._progress is not None:
                    self._progress(slice_start, 0)
                continue
            written += self._catalog.write(trades, symbol=request.symbol)
            first_ts = trades[0].ts_utc if first_ts is None else first_ts
            last_ts = trades[-1].ts_utc
            if self._progress is not None:
                self._progress(slice_start, len(trades))

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


def utc_slices(
    start: datetime,
    end: datetime,
    *,
    step: timedelta = timedelta(hours=1),
) -> Iterator[tuple[datetime, datetime]]:
    """Yield `[slice_start, slice_end)` pieces of `[start, end)`, `step` long.

    Slices are aligned to `step` boundaries (hourly by default) and the last one is
    clipped to `end`, so a window that ends mid-hour fetches up to `end` and not past
    it. The caller gets exactly the window it asked for, in pieces small enough to
    persist as they arrive.
    """
    if start >= end:
        raise ValueError("start must be before end")
    if step <= timedelta(0):
        raise ValueError("step must be positive")
    midnight = datetime.combine(start.date(), datetime.min.time(), tzinfo=UTC)
    steps_elapsed = (start - midnight) // step
    boundary = midnight + (steps_elapsed + 1) * step
    cursor = start
    while cursor < end:
        slice_end = min(boundary, end)
        yield cursor, slice_end
        cursor = slice_end
        boundary += step
