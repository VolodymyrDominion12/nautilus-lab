"""Parquet storage for Binance USD-M premium index klines."""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from nautilus_lab.domain.errors import CatalogEmptyError
from nautilus_lab.domain.premium_index import PremiumIndexBar

_SCHEMA = pa.schema(
    [
        pa.field("ts_utc", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("interval", pa.string(), nullable=False),
        pa.field("open", pa.string(), nullable=False),
        pa.field("high", pa.string(), nullable=False),
        pa.field("low", pa.string(), nullable=False),
        pa.field("close", pa.string(), nullable=False),
    ]
)


class ParquetPremiumIndexCatalog:
    """Idempotent Parquet storage for premium index klines per symbol and interval."""

    def __init__(self, path: Path) -> None:
        self._path = path.expanduser().resolve()

    @property
    def path(self) -> Path:
        return self._path

    def series_path(self, symbol: str, interval: str) -> Path:
        clean_symbol = symbol.removesuffix("-PERP").upper()
        return (
            self._path
            / "data"
            / "premium_index"
            / clean_symbol
            / interval
            / "premium_index.parquet"
        )

    def write(self, bars: Sequence[PremiumIndexBar], *, symbol: str, interval: str) -> int:
        if not bars:
            raise CatalogEmptyError("cannot write an empty premium index series")
        clean_symbol = symbol.removesuffix("-PERP").upper()
        merged: dict[datetime, PremiumIndexBar] = {
            item.ts_utc: item for item in self.load(symbol=clean_symbol, interval=interval)
        }
        for item in bars:
            merged[item.ts_utc] = item
        ordered = [merged[key] for key in sorted(merged)]

        target = self.series_path(clean_symbol, interval)
        target.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pydict(
            {
                "ts_utc": [item.ts_utc for item in ordered],
                "symbol": [clean_symbol for _ in ordered],
                "interval": [interval for _ in ordered],
                "open": [str(item.open) for item in ordered],
                "high": [str(item.high) for item in ordered],
                "low": [str(item.low) for item in ordered],
                "close": [str(item.close) for item in ordered],
            },
            schema=_SCHEMA,
        )
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
    ) -> list[PremiumIndexBar]:
        target = self.series_path(symbol, interval)
        if not target.exists():
            return []
        table = pq.read_table(target)
        bars: list[PremiumIndexBar] = []
        for i in range(len(table)):
            ts = table["ts_utc"][i].as_py()
            if start is not None and ts < start:
                continue
            if end is not None and ts >= end:
                continue
            bars.append(
                PremiumIndexBar(
                    symbol=str(table["symbol"][i].as_py()),
                    interval=str(table["interval"][i].as_py()),
                    ts_utc=ts,
                    open=Decimal(str(table["open"][i].as_py())),
                    high=Decimal(str(table["high"][i].as_py())),
                    low=Decimal(str(table["low"][i].as_py())),
                    close=Decimal(str(table["close"][i].as_py())),
                )
            )
        return bars
