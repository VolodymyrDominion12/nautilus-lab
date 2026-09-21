import logging
from typing import final

from nautilus_lab.domain.order_book import OrderBookSnapshot
from nautilus_lab.infrastructure.binance_orderbook import BinanceLiveOrderBook
from nautilus_lab.infrastructure.orderbook_catalog import ParquetOrderBookCatalog


@final
class IngestOrderBook:
    """Collects live L2 snapshots from Binance and saves them to Parquet."""

    def __init__(self, catalog: ParquetOrderBookCatalog) -> None:
        self._catalog = catalog
        self._logger = logging.getLogger(type(self).__name__)

    def __call__(self, symbol: str, batch_size: int = 100) -> None:
        """Run the ingestion loop. Block until interrupted.
        
        Args:
            symbol: e.g. ETHUSDT
            batch_size: flush to disk every N snapshots (100 = ~10 seconds at 100ms updates)
        """
        self._logger.info("Starting live L2 ingest for %s...", symbol)
        live_feed = BinanceLiveOrderBook(symbol)
        
        buffer: list[OrderBookSnapshot] = []
        try:
            for snap in live_feed.snapshots():
                buffer.append(snap)
                
                if len(buffer) >= batch_size:
                    written = self._catalog.write(buffer, symbol=symbol)
                    self._logger.info("Flushed %d L2 snapshots for %s", written, symbol)
                    buffer.clear()
        except KeyboardInterrupt:
            self._logger.info("Ingest interrupted.")
        finally:
            if buffer:
                written = self._catalog.write(buffer, symbol=symbol)
                self._logger.info("Flushed final %d L2 snapshots for %s", written, symbol)
