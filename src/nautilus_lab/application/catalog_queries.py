from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from nautilus_lab.domain.errors import CatalogEmptyError
from nautilus_lab.infrastructure.nautilus.instrument import binance_symbol_to_instrument_id
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.infrastructure.timeframe import NAUTILUS_BAR_SPEC, nautilus_bar_type


def bar_interval_to_timedelta(interval: str) -> timedelta:
    mapping = {
        "1m": timedelta(minutes=1),
        "5m": timedelta(minutes=5),
        "15m": timedelta(minutes=15),
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
        "1d": timedelta(days=1),
    }
    if interval not in mapping:
        allowed = ", ".join(NAUTILUS_BAR_SPEC)
        raise ValueError(f"unsupported bar interval {interval!r}; use one of: {allowed}")
    return mapping[interval]


def catalog_tail(
    cfg: Settings,
    *,
    catalog_path: str | None,
    instrument_id: str,
    bar_interval: str,
) -> datetime | None:
    bar_type = nautilus_bar_type(instrument_id, bar_interval)
    path = Path(catalog_path or cfg.catalog_path)
    if not path.exists():
        return None
    catalog = NautilusParquetCatalog(path, fees=cfg.fee_schedule())
    try:
        bars = catalog.load(bar_type=bar_type)
    except CatalogEmptyError:
        return None
    if not bars:
        return None
    return bars[-1].ts_utc


def incremental_ingest_start(
    cfg: Settings,
    *,
    catalog_path: str | None,
    symbol: str,
    default_start: datetime,
    end: datetime,
) -> datetime | None:
    """Return ingest start after the last stored bar, or default_start if empty."""
    instrument_id = binance_symbol_to_instrument_id(symbol)
    tail = catalog_tail(
        cfg,
        catalog_path=catalog_path,
        instrument_id=instrument_id,
        bar_interval=cfg.bar_interval,
    )
    if tail is None:
        return default_start
    start = tail + bar_interval_to_timedelta(cfg.bar_interval)
    if start >= end:
        return None
    return start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC)
