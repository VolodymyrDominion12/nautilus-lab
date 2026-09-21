from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from nautilus_lab.domain.ticks import AggTrade


class ParquetAggTradesCatalog:
    """Parquet store for aggregated trades beside the bar catalog.

    Layout (mirrors the taker-flow catalog convention)::

        <root>/
          data/
            agg_trade/
              <SYMBOL>/
                <YYYY-MM-DD>.parquet   # one file per UTC day

    Each Parquet file is a flat DataFrame with columns::

        agg_id (int64), ts_utc (datetime64[us, UTC]), instrument_id (str),
        price (str), qty (str), is_buyer_maker (bool)

    ``price`` and ``qty`` are stored as strings to preserve Binance's exact decimal
    representation (no float precision loss). Load-side callers that need arithmetic
    should do ``Decimal(row["price"])`` — the cost is negligible compared to a round-trip.

    Day-level sharding keeps individual files small (<<100 MB for any spot symbol on
    hourly ingest windows) and lets incremental updates overwrite exactly one day at a
    time without touching the rest of the catalog.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def path(self) -> Path:
        return self._root

    def _symbol_dir(self, symbol: str) -> Path:
        return self._root / "data" / "agg_trade" / symbol.upper()

    def series_dir(self, symbol: str) -> Path:
        """Directory holding this symbol's day shards. May not exist yet."""
        return self._symbol_dir(symbol)

    def series_exists(self, symbol: str) -> bool:
        """True when at least one day shard is stored for this symbol.

        The engine treats a missing tick series as an empty one, so a tick-level filter
        over it would run on defaults and still be labelled tick-based. Callers that
        offer such a filter ask this first.
        """
        directory = self._symbol_dir(symbol)
        return directory.exists() and any(directory.glob("*.parquet"))

    def write(self, trades: Sequence[AggTrade], *, symbol: str) -> int:
        """Persist ``trades`` grouped by UTC day. Returns the count written.

        Typical data volumes:
            - ETH/USDT spot on a quiet hour: ~5,000-15,000 aggTrades by UTC day.
        """
        if not trades:
            return 0

        # Group trades by UTC day.
        by_day: dict[str, list[AggTrade]] = {}
        for trade in trades:
            day_key = trade.ts_utc.strftime("%Y-%m-%d")
            by_day.setdefault(day_key, []).append(trade)

        directory = self._symbol_dir(symbol)
        directory.mkdir(parents=True, exist_ok=True)

        total_written = 0
        for day_key, day_trades in sorted(by_day.items()):
            out_path = directory / f"{day_key}.parquet"
            df = _trades_to_dataframe(day_trades)

            if out_path.exists():
                # Merge with existing data: read → concat → dedup → sort → rewrite.
                existing = pd.read_parquet(out_path)
                df = (
                    pd.concat([existing, df], ignore_index=True)
                    .drop_duplicates(subset="agg_id")
                    .sort_values("agg_id")
                    .reset_index(drop=True)
                )

            df.to_parquet(out_path, index=False)
            total_written += len(day_trades)

        return total_written

    def load(
        self,
        *,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[AggTrade]:
        """Load aggregated trades for ``symbol`` in [start, end).

        Returns an empty list when no data exists for the requested window rather than
        raising, so that a caller can handle missing data gracefully.
        """
        directory = self._symbol_dir(symbol)
        if not directory.exists():
            return []

        parquet_files = sorted(directory.glob("*.parquet"))
        if not parquet_files:
            return []

        frames: list[pd.DataFrame] = []
        for file in parquet_files:
            # Use the filename date for a fast pre-filter before reading the file.
            day_str = file.stem  # "YYYY-MM-DD"
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

        df = pd.concat(frames, ignore_index=True).sort_values("agg_id").reset_index(drop=True)

        # Apply precise time filter — recompute the mask on the reset index so that
        # pandas does not need to reindex the boolean series (which would silence the
        # alignment warning but silently drop rows).
        ts_col = pd.to_datetime(df["ts_utc"], utc=True)
        mask = pd.Series([True] * len(df), index=df.index)
        if start is not None:
            mask &= ts_col >= pd.Timestamp(start)
        if end is not None:
            mask &= ts_col < pd.Timestamp(end)
        df = df[mask]

        return _dataframe_to_trades(df)


def _trades_to_dataframe(trades: list[AggTrade]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "agg_id": [t.agg_id for t in trades],
            "ts_utc": pd.to_datetime([t.ts_utc for t in trades], utc=True),
            "instrument_id": [t.instrument_id for t in trades],
            "price": [t.price for t in trades],
            "qty": [t.qty for t in trades],
            "is_buyer_maker": [t.is_buyer_maker for t in trades],
        }
    )


def _dataframe_to_trades(df: pd.DataFrame) -> list[AggTrade]:
    trades: list[AggTrade] = []
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
        trades.append(
            AggTrade(
                instrument_id=str(row["instrument_id"]),
                ts_utc=ts_dt,
                agg_id=int(row["agg_id"]),
                price=str(row["price"]),
                qty=str(row["qty"]),
                is_buyer_maker=bool(row["is_buyer_maker"]),
            )
        )
    return trades
