"""Parquet storage for funding settlements, living beside the bar series.

Section 9 of the data-infrastructure document is explicit that columnar Parquet —
not CSV or JSON — is the storage standard for financial time series, and that the
choice is what separates a usable history from a slow one. Funding is an event
series rather than OHLCV, so it gets its own subtree
(`<catalog>/data/funding/<SYMBOL>/funding.parquet`) instead of being forced into
the Nautilus bar schema.

Decimals are stored as strings. That is deliberate: a Parquet float column would
round-trip `Decimal("0.00003705")` through binary floating point, and the whole
domain layer is built on exact decimal arithmetic.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from nautilus_lab.domain.errors import CatalogEmptyError
from nautilus_lab.domain.funding import FundingSnapshot

_SCHEMA = pa.schema(
    [
        pa.field("ts_utc", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("funding_rate", pa.string(), nullable=False),
        pa.field("mark_price", pa.string(), nullable=False),
        # Nullable by design: "index unknown" must survive a round trip as unknown,
        # not come back as a number that makes the basis look flat.
        pa.field("index_price", pa.string(), nullable=True),
    ]
)


class ParquetFundingCatalog:
    """Idempotent writer / reader for one funding series per symbol."""

    def __init__(self, path: Path) -> None:
        self._path = path.expanduser().resolve()

    @property
    def path(self) -> Path:
        return self._path

    def series_path(self, symbol: str) -> Path:
        return self._path / "data" / "funding" / symbol.upper() / "funding.parquet"

    def write(self, snapshots: Sequence[FundingSnapshot], *, symbol: str) -> int:
        """Merge into the stored series, keyed by settlement time. Returns total rows.

        Replace-on-overlap rather than append: re-ingesting an overlapping window must
        not leave two rows for the same settlement. The newest ingest wins, the same
        rule the bar catalog follows.
        """
        if not snapshots:
            raise CatalogEmptyError("cannot write an empty funding series")
        merged: dict[datetime, FundingSnapshot] = {
            item.ts_utc: item for item in self.load(symbol=symbol)
        }
        for item in snapshots:
            merged[item.ts_utc] = item
        ordered = [merged[key] for key in sorted(merged)]

        target = self.series_path(symbol)
        target.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pydict(
            {
                "ts_utc": [item.ts_utc for item in ordered],
                "instrument": [item.instrument for item in ordered],
                "funding_rate": [str(item.funding_rate) for item in ordered],
                "mark_price": [str(item.mark_price) for item in ordered],
                "index_price": [
                    None if item.index_price is None else str(item.index_price) for item in ordered
                ],
            },
            schema=_SCHEMA,
        )
        # Write-then-rename: a crash mid-write must not destroy a good series.
        temporary = target.with_suffix(".parquet.tmp")
        pq.write_table(table, temporary, compression="zstd")
        os.replace(temporary, target)
        return len(ordered)

    def load(
        self,
        *,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[FundingSnapshot]:
        target = self.series_path(symbol)
        if not target.exists():
            return []
        rows = pq.read_table(target, schema=_SCHEMA).to_pylist()
        snapshots: list[FundingSnapshot] = []
        for row in rows:
            ts = row["ts_utc"]
            if start is not None and ts < start:
                continue
            if end is not None and ts >= end:
                continue
            raw_index = row["index_price"]
            snapshots.append(
                FundingSnapshot(
                    instrument=str(row["instrument"]),
                    funding_rate=Decimal(str(row["funding_rate"])),
                    mark_price=Decimal(str(row["mark_price"])),
                    index_price=None if raw_index is None else Decimal(str(raw_index)),
                    ts_utc=ts,
                )
            )
        snapshots.sort(key=lambda item: item.ts_utc)
        return snapshots

    def series_exists(self, symbol: str) -> bool:
        return self.series_path(symbol).exists()
