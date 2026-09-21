from __future__ import annotations

from nautilus_lab.application.dtos import IngestAggTradesReport, IngestAggTradesRequest
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.domain.errors import CatalogEmptyError
from nautilus_lab.domain.ports import AggTradesCatalog, AggTradesFeed


class IngestAggTrades:
    """Fetch public Binance aggTrades and persist them in the Parquet catalog.

    This is the application-layer use case for the ``lab ingest --trades`` command.
    The domain does not know about HTTP or Parquet; this class wires them together.

    Typical data volumes:
    - ETH/USDT spot on a quiet hour: ~5 000-15 000 aggTrades
    - ETH/USDT spot on a volatile hour: ~100 000+ aggTrades

    The catalog stores one Parquet file per UTC day to keep file sizes manageable
    and allow incremental updates.
    """

    def __init__(
        self,
        feed: AggTradesFeed,
        catalog: AggTradesCatalog,
        *,
        catalog_path: str,
    ) -> None:
        self._feed = feed
        self._catalog = catalog
        self._catalog_path = catalog_path

    def execute(self, request: IngestAggTradesRequest) -> IngestAggTradesReport:
        """Fetch and store aggTrades for the symbol/window in the request."""
        require_simulated_mode(request.mode)
        if request.start >= request.end:
            raise ValueError("ingest start must be before end")

        trades = self._feed.fetch(
            symbol=request.symbol,
            start=request.start,
            end=request.end,
            instrument_id=request.instrument_id,
        )
        if not trades:
            raise CatalogEmptyError(
                f"no public aggTrades for {request.symbol} "
                f"in [{request.start.isoformat()}, {request.end.isoformat()}). "
                f"Check the symbol name and date range."
            )

        written = self._catalog.write(trades, symbol=request.symbol)
        return IngestAggTradesReport(
            trades_written=written,
            first_ts=trades[0].ts_utc,
            last_ts=trades[-1].ts_utc,
            catalog_path=self._catalog_path,
            source="binance public aggTrades (no API keys)",
            symbol=request.symbol,
        )
