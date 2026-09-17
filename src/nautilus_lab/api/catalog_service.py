from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.infrastructure.timeframe import nautilus_bar_type
from nautilus_lab.interfaces.composition import settings


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def resolve_catalog_path(catalog_path: str | None) -> Path:
    cfg = settings()
    return Path(catalog_path or cfg.catalog_path).expanduser().resolve()


def describe_catalog(catalog_path: str | None = None) -> dict[str, Any]:
    resolved = resolve_catalog_path(catalog_path)
    # The interval is a property of this process's settings, not of the directory, but the
    # dashboard needs it to request bars and to label its chart: one catalog holds one
    # interval, and a chart asking for the wrong one renders empty with no explanation.
    interval = settings().bar_interval
    if not resolved.exists():
        return {
            "catalog_path": str(resolved),
            "exists": False,
            "bar_interval": interval,
            "instruments": [],
        }

    try:
        cat = ParquetDataCatalog(str(resolved))
        instruments_info: list[dict[str, Any]] = []
        for inst in cat.instruments():
            bars = cat.bars(instrument_ids=[str(inst.id)])
            count = len(bars)
            first_dt = str(pd.to_datetime(bars[0].ts_event, unit="ns")) if count > 0 else None
            last_dt = str(pd.to_datetime(bars[-1].ts_event, unit="ns")) if count > 0 else None
            raw_sym = (
                inst.raw_symbol.value if hasattr(inst.raw_symbol, "value") else str(inst.raw_symbol)
            )
            instruments_info.append(
                {
                    "instrument_id": str(inst.id),
                    "raw_symbol": raw_sym,
                    "bars_count": count,
                    "first_date": first_dt,
                    "last_date": last_dt,
                    "quote_currency": str(inst.quote_currency),
                    "maker_fee": float(inst.maker_fee),
                    "taker_fee": float(inst.taker_fee),
                }
            )
        return {
            "catalog_path": str(resolved),
            "exists": True,
            "bar_interval": interval,
            "instruments": instruments_info,
            "total_instruments": len(instruments_info),
        }
    except Exception as exc:
        return {
            "catalog_path": str(resolved),
            "exists": True,
            "bar_interval": interval,
            "error": str(exc),
            "instruments": [],
        }


def list_catalogs(cfg: Settings | None = None) -> dict[str, Any]:
    resolved = cfg or settings()
    catalogs: list[dict[str, Any]] = []
    for path in resolved.all_catalog_paths():
        summary = describe_catalog(path)
        catalogs.append(
            {
                "path": summary["catalog_path"],
                "exists": summary.get("exists", False),
                "total_instruments": summary.get("total_instruments", 0),
                "error": summary.get("error"),
            }
        )
    return {
        "default": resolved.catalog_path,
        "catalogs": catalogs,
    }


# Describing a catalog loads every bar of every instrument from Parquet. The dashboard
# polls its status endpoint on a timer, so an uncached describe means re-reading the whole
# catalog several times a minute for numbers that only change when an ingest finishes.
# The cache is keyed by resolved absolute path and invalidated explicitly after ingest.
_CATALOG_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CATALOG_CACHE_TTL_SECONDS = 10.0


def invalidate_catalog_cache(catalog_path: str | None = None) -> None:
    """Drop cached catalog descriptions, for one path or all of them."""
    if catalog_path is None:
        _CATALOG_CACHE.clear()
        return
    _CATALOG_CACHE.pop(str(Path(catalog_path).expanduser().resolve()), None)


def describe_catalog_cached(
    catalog_path: str | None = None, *, ttl_seconds: float = _CATALOG_CACHE_TTL_SECONDS
) -> dict[str, Any]:
    """`describe_catalog` behind a short TTL cache. Treat the result as read-only."""
    key = str(resolve_catalog_path(catalog_path))
    now = time.monotonic()
    cached = _CATALOG_CACHE.get(key)
    if cached is not None and now - cached[0] < ttl_seconds:
        return cached[1]
    payload = describe_catalog(catalog_path)
    _CATALOG_CACHE[key] = (now, payload)
    return payload


def load_catalog_bars(
    *,
    instrument_id: str | None = None,
    catalog_path: str | None = None,
    bar_interval: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    cfg = settings()
    resolved_id = instrument_id or cfg.instrument_id
    interval = bar_interval or cfg.bar_interval
    bar_type = nautilus_bar_type(resolved_id, interval)
    catalog = NautilusParquetCatalog(resolve_catalog_path(catalog_path), fees=cfg.fee_schedule())
    bars = catalog.load(
        bar_type=bar_type,
        start=_parse_utc(start),
        end=_parse_utc(end),
    )
    if limit > 0 and len(bars) > limit:
        bars = bars[-limit:]
    payload = [
        {
            "time": int(bar.ts_utc.timestamp()),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
        }
        for bar in bars
    ]
    first = bars[0].ts_utc.isoformat() if bars else None
    last = bars[-1].ts_utc.isoformat() if bars else None
    return {
        "instrument_id": resolved_id,
        "bar_type": bar_type,
        "bar_interval": interval,
        "catalog_path": str(catalog.path),
        "count": len(payload),
        "first_date": first,
        "last_date": last,
        "bars": payload,
    }
