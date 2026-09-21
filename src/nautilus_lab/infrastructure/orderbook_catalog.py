from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from nautilus_lab.domain.order_book import BookLevel, OrderBookSnapshot


class ParquetOrderBookCatalog:
    """Parquet store for L2 Orderbook snapshots.

    Layout:
        <root>/
          data/
            orderbook/
              <SYMBOL>/
                <YYYY-MM-DD>.parquet   # one file per UTC day

    Each Parquet file is a flat DataFrame with columns:
        ts_utc (datetime64[us, UTC]), instrument_id (str),
        bids_price (list[str]), bids_size (list[str]),
        asks_price (list[str]), asks_size (list[str])

    Arrays of strings preserve exact decimal precision without floating point loss.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def path(self) -> Path:
        return self._root

    def _symbol_dir(self, symbol: str) -> Path:
        return self._root / "data" / "orderbook" / symbol.upper()

    def series_dir(self, symbol: str) -> Path:
        return self._symbol_dir(symbol)

    def series_exists(self, symbol: str) -> bool:
        directory = self._symbol_dir(symbol)
        return directory.exists() and any(directory.glob("*.parquet"))

    def write(self, snapshots: Sequence[OrderBookSnapshot], *, symbol: str) -> int:
        if not snapshots:
            return 0

        by_day: dict[str, list[OrderBookSnapshot]] = {}
        for snap in snapshots:
            day_key = snap.ts_utc.strftime("%Y-%m-%d")
            by_day.setdefault(day_key, []).append(snap)

        directory = self._symbol_dir(symbol)
        directory.mkdir(parents=True, exist_ok=True)

        total_written = 0
        for day_key, day_snaps in sorted(by_day.items()):
            out_path = directory / f"{day_key}.parquet"
            df = _snapshots_to_dataframe(day_snaps)

            if out_path.exists():
                existing = pd.read_parquet(out_path)
                df = (
                    pd.concat([existing, df], ignore_index=True)
                    .drop_duplicates(subset="ts_utc")
                    .sort_values("ts_utc")
                    .reset_index(drop=True)
                )

            df.to_parquet(out_path, index=False)
            total_written += len(day_snaps)

        return total_written

    def load(
        self,
        *,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[OrderBookSnapshot]:
        directory = self._symbol_dir(symbol)
        if not directory.exists():
            return []

        parquet_files = sorted(directory.glob("*.parquet"))
        if not parquet_files:
            return []

        frames: list[pd.DataFrame] = []
        for file in parquet_files:
            day_str = file.stem
            if start is not None:
                day_end = datetime.fromisoformat(f"{day_str}T23:59:59.999999+00:00")
                if day_end < start:
                    continue
            if end is not None:
                day_start = datetime.fromisoformat(f"{day_str}T00:00:00+00:00")
                if day_start >= end:
                    continue
            frames.append(pd.read_parquet(file))

        if not frames:
            return []

        df = pd.concat(frames, ignore_index=True).sort_values("ts_utc").reset_index(drop=True)

        ts_col = pd.to_datetime(df["ts_utc"], utc=True)
        mask = pd.Series([True] * len(df), index=df.index)
        if start is not None:
            mask &= ts_col >= pd.Timestamp(start)
        if end is not None:
            mask &= ts_col < pd.Timestamp(end)
        df = df[mask]

        return _dataframe_to_snapshots(df)


def _snapshots_to_dataframe(snapshots: list[OrderBookSnapshot]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_utc": pd.to_datetime([s.ts_utc for s in snapshots], utc=True),
            "instrument_id": [s.instrument_id for s in snapshots],
            "bids_price": [[str(b.price) for b in s.bids] for s in snapshots],
            "bids_size": [[str(b.size) for b in s.bids] for s in snapshots],
            "asks_price": [[str(a.price) for a in s.asks] for s in snapshots],
            "asks_size": [[str(a.size) for a in s.asks] for s in snapshots],
        }
    )


def _dataframe_to_snapshots(df: pd.DataFrame) -> list[OrderBookSnapshot]:
    snapshots: list[OrderBookSnapshot] = []
    for _, row in df.iterrows():
        ts: object = row["ts_utc"]
        if isinstance(ts, pd.Timestamp):
            ts_dt = ts.to_pydatetime()
        elif isinstance(ts, datetime):
            ts_dt = ts
        else:
            ts_dt = pd.Timestamp(str(ts)).to_pydatetime()
        if ts_dt.tzinfo is None:
            ts_dt = ts_dt.replace(tzinfo=UTC)

        bids = tuple(
            BookLevel(price=Decimal(p), size=Decimal(s))
            for p, s in zip(row["bids_price"], row["bids_size"], strict=True)
        )
        asks = tuple(
            BookLevel(price=Decimal(p), size=Decimal(s))
            for p, s in zip(row["asks_price"], row["asks_size"], strict=True)
        )

        snapshots.append(
            OrderBookSnapshot(
                instrument_id=str(row["instrument_id"]),
                ts_utc=ts_dt,
                bids=bids,
                asks=asks,
            )
        )
    return snapshots
