from __future__ import annotations

from nautilus_lab.application.dtos import FundingIngestReport, FundingIngestRequest
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.domain.errors import CatalogEmptyError
from nautilus_lab.domain.ports import FundingCatalog, FundingRateFeed


class IngestFundingHistory:
    """Fetch public funding settlements and persist them beside the bar series."""

    def __init__(
        self,
        feed: FundingRateFeed,
        catalog: FundingCatalog,
        *,
        catalog_path: str,
    ) -> None:
        self._feed = feed
        self._catalog = catalog
        self._catalog_path = catalog_path

    def execute(self, request: FundingIngestRequest) -> FundingIngestReport:
        require_simulated_mode(request.mode)
        if request.start >= request.end:
            raise ValueError("ingest start must be before end")
        snapshots = self._feed.fetch_history(
            symbol=request.symbol,
            start=request.start,
            end=request.end,
        )
        if not snapshots:
            raise CatalogEmptyError(
                f"no public funding settlements for {request.symbol} "
                f"in [{request.start.isoformat()}, {request.end.isoformat()})"
            )
        written = self._catalog.write(snapshots, symbol=request.symbol)
        return FundingIngestReport(
            snapshots_written=written,
            first_ts=snapshots[0].ts_utc,
            last_ts=snapshots[-1].ts_utc,
            catalog_path=self._catalog_path,
            source="binance public USD-M funding (no API keys)",
            symbol=request.symbol,
            missing_index_price=sum(1 for item in snapshots if item.index_price is None),
        )
