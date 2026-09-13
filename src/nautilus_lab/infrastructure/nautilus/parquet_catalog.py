from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from nautilus_trader.model.data import BarType
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from nautilus_lab.domain.bars import OhlcvBar, validate_bar
from nautilus_lab.domain.errors import CatalogEmptyError
from nautilus_lab.infrastructure.nautilus.bar_convert import (
    datetime_to_nanos,
    to_domain_bar,
    to_engine_bars,
)
from nautilus_lab.infrastructure.nautilus.instrument import eth_usdt_sim


class NautilusParquetCatalog:
    """Adapter over Nautilus `ParquetDataCatalog`. Stores closed bars only."""

    def __init__(self, path: Path) -> None:
        self._path = path.expanduser().resolve()
        self._path.mkdir(parents=True, exist_ok=True)
        self._instrument = eth_usdt_sim()

    @property
    def path(self) -> Path:
        return self._path

    def write(self, bars: Sequence[OhlcvBar], *, bar_type: str) -> int:
        if not bars:
            raise CatalogEmptyError("cannot write an empty bar series")
        nautilus_type = BarType.from_str(bar_type)
        engine_bars = to_engine_bars(
            list(bars), bar_type=nautilus_type, instrument=self._instrument
        )
        catalog = self._catalog()
        catalog.write_data([self._instrument], skip_disjoint_check=True)
        catalog.write_data(engine_bars, skip_disjoint_check=True)
        return len(engine_bars)

    def load(
        self,
        *,
        bar_type: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[OhlcvBar]:
        catalog = self._catalog()
        raw = catalog.bars(
            bar_types=[bar_type],
            start=datetime_to_nanos(start) if start is not None else None,
            end=datetime_to_nanos(end) if end is not None else None,
        )
        if not raw:
            raise CatalogEmptyError(
                f"no bars in catalog {self._path} for {bar_type}. Run `lab ingest` first."
            )
        instrument_id = str(self._instrument.id)
        domain: list[OhlcvBar] = []
        previous_ts: datetime | None = None
        for item in raw:
            bar = to_domain_bar(item, instrument_id)
            if start is not None and bar.ts_utc < start:
                continue
            if end is not None and bar.ts_utc >= end:
                continue
            validate_bar(bar, previous_ts=previous_ts, now=bar.ts_utc)
            domain.append(bar)
            previous_ts = bar.ts_utc
        if not domain:
            raise CatalogEmptyError(
                f"no bars in catalog {self._path} for {bar_type} in the requested window"
            )
        return domain

    def _catalog(self) -> ParquetDataCatalog:
        return ParquetDataCatalog(str(self._path))
