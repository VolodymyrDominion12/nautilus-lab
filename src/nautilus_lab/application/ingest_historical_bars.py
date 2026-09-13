from __future__ import annotations

from nautilus_lab.application.dtos import IngestReport, IngestRequest
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.domain.errors import CatalogEmptyError
from nautilus_lab.domain.ports import BarCatalog, PublicBarFeed


class IngestHistoricalBars:
    def __init__(self, feed: PublicBarFeed, catalog: BarCatalog, *, catalog_path: str) -> None:
        self._feed = feed
        self._catalog = catalog
        self._catalog_path = catalog_path

    def execute(self, request: IngestRequest) -> IngestReport:
        require_simulated_mode(request.mode)
        if request.start >= request.end:
            raise ValueError("ingest start must be before end")
        bars = self._feed.fetch(
            symbol=request.symbol,
            interval=request.interval,
            start=request.start,
            end=request.end,
            instrument_id=request.instrument_id,
        )
        if not bars:
            raise CatalogEmptyError(
                f"no public klines for {request.symbol} {request.interval} "
                f"in [{request.start.isoformat()}, {request.end.isoformat()})"
            )
        written = self._catalog.write(bars, bar_type=request.bar_type)
        return IngestReport(
            bars_written=written,
            first_ts=bars[0].ts_utc,
            last_ts=bars[-1].ts_utc,
            catalog_path=self._catalog_path,
            source="binance public klines (no API keys)",
        )
