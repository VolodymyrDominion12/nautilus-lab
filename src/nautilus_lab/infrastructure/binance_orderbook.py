import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from nautilus_lab.domain.order_book import BookLevel, OrderBookSnapshot


class BinanceLiveOrderBook:
    """Connects to Binance WebSocket to yield live L2 snapshots.

    Uses the partial book depth stream (`@depth20@100ms`) which pushes the top 20
    bids and asks every 100ms. This avoids the complexity of maintaining a local
    order book from raw updates.
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol.lower()
        self.url = f"wss://stream.binance.com:9443/ws/{self.symbol}@depth20@100ms"
        self._logger = logging.getLogger(type(self).__name__)

    def snapshots(self) -> Iterator[OrderBookSnapshot]:
        self._logger.info("Connecting to %s", self.url)
        try:
            with connect(self.url) as ws:
                while True:
                    msg = ws.recv()
                    ts = datetime.now(UTC)
                    payload = json.loads(msg)

                    bids = tuple(
                        BookLevel(price=Decimal(p), size=Decimal(s))
                        for p, s in payload.get("bids", [])
                    )
                    asks = tuple(
                        BookLevel(price=Decimal(p), size=Decimal(s))
                        for p, s in payload.get("asks", [])
                    )

                    if not bids or not asks:
                        continue

                    yield OrderBookSnapshot(
                        instrument_id=self.symbol.upper(),
                        ts_utc=ts,
                        bids=bids,
                        asks=asks,
                    )
        except ConnectionClosed as exc:
            self._logger.warning("WebSocket closed: %s", exc)
        except KeyboardInterrupt:
            self._logger.info("Stopped live orderbook ingestion via interrupt.")
