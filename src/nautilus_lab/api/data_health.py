"""Per-series coverage for one catalog: bars, taker flow, aggregated trades, funding.

One catalog is four independent trees written by four different ingests, and each one
can be missing or stale on its own:

* ``data/bar/<INSTRUMENT>/``  — the klines every robot reads;
* ``data/taker_flow/<SYMBOL>/taker_flow.parquet`` — kline field 9, the real taker split;
* ``data/agg_trade/<SYMBOL>/<YYYY-MM-DD>.parquet`` — ticks, required by the tick-level
  VPIN and Hawkes filters (a missing series silently degrades both);
* ``data/funding/<SYMBOL>/funding.parquet`` — funding settlements.

The dashboard needs to say which of them exist before a run is launched, because the
engine treats a missing series as empty rather than as an error. Counts come from the
Parquet footer and from the day shards' filenames — nothing here reads a full column of
ticks, so the payload stays cheap enough to poll.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pyarrow.compute as pc
import pyarrow.parquet as pq

from nautilus_lab.api.catalog_service import describe_catalog_cached, resolve_catalog_path
from nautilus_lab.infrastructure.agg_trades_catalog import ParquetAggTradesCatalog
from nautilus_lab.infrastructure.funding_catalog import ParquetFundingCatalog
from nautilus_lab.infrastructure.nautilus.instrument import binance_symbol_for_instrument
from nautilus_lab.infrastructure.taker_flow_catalog import ParquetTakerFlowCatalog
from nautilus_lab.interfaces.composition import settings

#: Describing coverage stats every shard of the tick series. The dashboard polls, and a
#: year of daily shards is ~365 stat calls, so the result is cached like the catalog
#: description and invalidated by the same ingest.
_HEALTH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_HEALTH_CACHE_TTL_SECONDS = 30.0


def invalidate_data_health_cache(catalog_path: str | None = None) -> None:
    """Drop cached coverage for one catalog path, or all of them."""
    if catalog_path is None:
        _HEALTH_CACHE.clear()
        return
    _HEALTH_CACHE.pop(str(resolve_catalog_path(catalog_path)), None)


def _parquet_rows(path: Path) -> int | None:
    """Row count from the Parquet footer. None when the file cannot be read."""
    try:
        metadata = pq.ParquetFile(path).metadata
    except Exception:
        return None
    if metadata is None:
        return None
    return int(metadata.num_rows)


def _parquet_span(path: Path, column: str) -> tuple[str | None, str | None]:
    """First and last value of one timestamp column, read alone. (None, None) on failure."""
    try:
        table = pq.read_table(path, columns=[column])
    except Exception:
        return None, None
    if table.num_rows == 0:
        return None, None
    stats = pc.min_max(table.column(column)).as_py()
    if not isinstance(stats, dict):
        return None, None
    first = stats.get("min")
    last = stats.get("max")
    return (
        first.isoformat() if hasattr(first, "isoformat") else None,
        last.isoformat() if hasattr(last, "isoformat") else None,
    )


def _taker_flow_health(root: Path, symbol: str) -> dict[str, Any]:
    target = ParquetTakerFlowCatalog(root).series_path(symbol)
    if not target.exists():
        return {"present": False, "rows": None, "first": None, "last": None}
    first, last = _parquet_span(target, "ts_utc")
    return {
        "present": True,
        "rows": _parquet_rows(target),
        "first": first,
        "last": last,
    }


def _funding_health(root: Path, symbol: str) -> dict[str, Any]:
    target = ParquetFundingCatalog(root).series_path(symbol)
    if not target.exists():
        return {"present": False, "rows": None, "first": None, "last": None}
    first, last = _parquet_span(target, "ts_utc")
    return {
        "present": True,
        "rows": _parquet_rows(target),
        "first": first,
        "last": last,
    }


def _ticks_health(root: Path, symbol: str) -> dict[str, Any]:
    """Aggregated trades, summarised from the day shards without reading tick columns."""
    directory = ParquetAggTradesCatalog(root).series_dir(symbol)
    if not directory.exists():
        return {
            "present": False,
            "files": 0,
            "rows": None,
            "first": None,
            "last": None,
            "bytes": 0,
        }
    shards = sorted(directory.glob("*.parquet"))
    if not shards:
        return {
            "present": False,
            "files": 0,
            "rows": None,
            "first": None,
            "last": None,
            "bytes": 0,
        }
    rows = 0
    rows_known = True
    size = 0
    for shard in shards:
        size += shard.stat().st_size
        count = _parquet_rows(shard)
        if count is None:
            rows_known = False
        else:
            rows += count
    days = sorted(shard.stem for shard in shards)
    return {
        "present": True,
        "files": len(shards),
        # Day filenames are UTC days, so the span is a day-resolution bound, not a tick
        # timestamp: the panel labels it as such rather than implying tick precision.
        "first": f"{days[0]}T00:00:00+00:00",
        "last": f"{days[-1]}T23:59:59.999999+00:00",
        "rows": rows if rows_known else None,
        "bytes": size,
    }


def describe_data_health(catalog_path: str | None = None) -> dict[str, Any]:
    """Coverage of all four series trees for every instrument in one catalog."""
    resolved = resolve_catalog_path(catalog_path)
    payload = describe_catalog_cached(str(resolved))
    instruments = payload.get("instruments") or []
    rows: list[dict[str, Any]] = []
    for instrument in instruments:
        instrument_id = str(instrument.get("instrument_id", ""))
        symbol = binance_symbol_for_instrument(instrument_id)
        entry: dict[str, Any] = {
            "instrument_id": instrument_id,
            "symbol": symbol,
            "bars": {
                "present": int(instrument.get("bars_count", 0) or 0) > 0,
                "rows": int(instrument.get("bars_count", 0) or 0),
                "first": instrument.get("first_date"),
                "last": instrument.get("last_date"),
            },
            "taker_flow": {"present": False, "rows": None, "first": None, "last": None},
            "ticks": {
                "present": False,
                "files": 0,
                "rows": None,
                "first": None,
                "last": None,
                "bytes": 0,
            },
            "funding": {"present": False, "rows": None, "first": None, "last": None},
        }
        if symbol:
            entry["taker_flow"] = _taker_flow_health(resolved, symbol)
            entry["ticks"] = _ticks_health(resolved, symbol)
            entry["funding"] = _funding_health(resolved, symbol)
        rows.append(entry)
    return {
        "catalog_path": str(resolved),
        "exists": bool(payload.get("exists", False)),
        "bar_interval": payload.get("bar_interval") or settings().bar_interval,
        "error": payload.get("error"),
        "instruments": rows,
        "tick_filters_ready": any(bool(row["ticks"]["present"]) for row in rows),
    }


def describe_data_health_cached(
    catalog_path: str | None = None, *, ttl_seconds: float = _HEALTH_CACHE_TTL_SECONDS
) -> dict[str, Any]:
    """`describe_data_health` behind a short TTL cache. Treat the result as read-only."""
    key = str(resolve_catalog_path(catalog_path))
    now = time.monotonic()
    cached = _HEALTH_CACHE.get(key)
    if cached is not None and now - cached[0] < ttl_seconds:
        return cached[1]
    payload = describe_data_health(catalog_path)
    _HEALTH_CACHE[key] = (now, payload)
    return payload
