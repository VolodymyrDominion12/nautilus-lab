"""Parquet storage for the per-bar taker split, living beside the bar series.

Why this exists as its own series rather than a column in the bar series: the bar
series is written as `nautilus_trader.model.data.Bar`, which has no field for
`takerBuyBaseAssetVolume`. The value therefore cannot survive the engine round-trip
(`to_engine_bars` -> `Bar` -> `to_domain_bar`), and that is exactly how kline field 9
was being lost — defect D4 in docs/23-infrastruktura-danyh-plan.md. Storing it in its
own subtree, keyed by the same bar close timestamp, keeps the bar series byte-for-byte
what Nautilus expects while making the order-flow field recoverable.

Why the interval is part of the path: a bar close at 23:59:59.999 belongs to both an
hourly bar (the 23:00 hour) and a daily bar. Without the interval, a catalog holding
1h and 1d history merged the two series into one file, and the daily taker-buy total
(roughly 24x the hourly volume) overwrote the hourly value for that one bar — which then
failed `validate_bar` with "taker buy base volume must be <= bar volume". One
series
per `(symbol, interval)` keeps the join unambiguous.

Decimals are stored as strings, for the same reason as funding: a Parquet float column
would round-trip exact decimal volumes through binary floating point, and the domain
layer is built on exact decimal arithmetic.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import CatalogEmptyError

_SCHEMA = pa.schema(
    [
        pa.field("ts_utc", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("taker_buy_base_volume", pa.string(), nullable=False),
    ]
)


class ParquetTakerFlowCatalog:
    """Idempotent writer / reader for one taker-flow series per symbol and interval."""

    def __init__(self, path: Path) -> None:
        self._path = path.expanduser().resolve()

    @property
    def path(self) -> Path:
        return self._path

    def series_path(self, symbol: str, interval: str) -> Path:
        return self._path / "data" / "taker_flow" / symbol.upper() / interval / "taker_flow.parquet"

    def write(self, bars: Sequence[OhlcvBar], *, symbol: str, interval: str) -> int:
        """Merge the known taker volumes into the stored series. Returns total rows.

        Bars whose field is None carry no information and are skipped rather than
        written as zero — "unknown" must not be laundered into "no aggressive buying".
        Replace-on-overlap, the same rule the bar catalog follows, so a re-ingest of an
        overlapping window cannot leave two rows for one bar timestamp.
        """
        known = [bar for bar in bars if bar.taker_buy_base_volume is not None]
        if not known:
            raise CatalogEmptyError("cannot write a taker-flow series without the kline field 9")
        merged: dict[datetime, Decimal] = dict(self.load(symbol=symbol, interval=interval))
        for bar in known:
            value = bar.taker_buy_base_volume
            if value is not None:
                merged[bar.ts_utc] = value
        ordered = sorted(merged)

        target = self.series_path(symbol, interval)
        target.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pydict(
            {
                "ts_utc": ordered,
                "instrument": [symbol.upper()] * len(ordered),
                "taker_buy_base_volume": [str(merged[ts]) for ts in ordered],
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
        interval: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Mapping[datetime, Decimal]:
        """Taker-buy base volume by bar close timestamp. Empty mapping when absent."""
        target = self.series_path(symbol, interval)
        if not target.exists():
            return {}
        rows = pq.read_table(target, schema=_SCHEMA).to_pylist()
        series: dict[datetime, Decimal] = {}
        for row in rows:
            ts = row["ts_utc"]
            if start is not None and ts < start:
                continue
            if end is not None and ts >= end:
                continue
            series[ts] = Decimal(str(row["taker_buy_base_volume"]))
        return series

    def series_exists(self, symbol: str, interval: str) -> bool:
        return self.series_path(symbol, interval).exists()
