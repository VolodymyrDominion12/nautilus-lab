from __future__ import annotations

from nautilus_lab.application.dtos import IngestReport, IngestRequest
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import CatalogEmptyError
from nautilus_lab.domain.ports import BarCatalog, PublicBarFeed, TakerFlowCatalog


class IngestHistoricalBars:
    def __init__(
        self,
        feed: PublicBarFeed,
        catalog: BarCatalog,
        *,
        catalog_path: str,
        taker_flow: TakerFlowCatalog | None = None,
    ) -> None:
        self._feed = feed
        self._catalog = catalog
        self._catalog_path = catalog_path
        self._taker_flow = taker_flow

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
        written = self._catalog.write(
            bars,
            bar_type=request.bar_type,
            instrument_id=request.instrument_id,
        )
        # The bar series cannot hold kline field 9, so the taker split is written to its
        # own series in the same pass. Same bars, same timestamps, two stores — and if
        # the feed returned no such field the writer refuses instead of storing zeros.
        flow_rows = 0
        if self._taker_flow is not None and _has_taker_flow(bars):
            flow_rows = self._taker_flow.write(bars, symbol=request.symbol)
        return IngestReport(
            bars_written=written,
            first_ts=bars[0].ts_utc,
            last_ts=bars[-1].ts_utc,
            catalog_path=self._catalog_path,
            source="binance public klines (no API keys)",
            taker_flow_rows=flow_rows,
        )


def _has_taker_flow(bars: list[OhlcvBar]) -> bool:
    """True when the feed actually knows the taker split (kline field 9 present)."""
    return any(bar.taker_buy_base_volume is not None for bar in bars)
