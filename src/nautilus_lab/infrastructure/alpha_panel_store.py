"""Build the alpha panel from the project's Parquet catalogs, and cache it as `.npz`.

Bars come through `NautilusParquetCatalog`, so the 16-byte Nautilus decimals are
decoded by the same code the backtests use, with the same dedup and ordering checks.
Taker flow, premium index and funding come through their own catalogs.

Building the panel converts every bar through Decimal, which takes seconds per coin.
The `.npz` cache makes the next screen start in well under a second. It is a cache,
not evidence: delete it, or pass `rebuild=True`, after an ingest.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from nautilus_lab.application.alpha.panel import (
    FloatArray,
    IntArray,
    Panel,
    align_columns,
    bucket_events,
    minutes_from_ns,
)
from nautilus_lab.infrastructure.funding_catalog import ParquetFundingCatalog
from nautilus_lab.infrastructure.nautilus.bar_convert import datetime_to_nanos
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.premium_index_catalog import ParquetPremiumIndexCatalog
from nautilus_lab.infrastructure.taker_flow_catalog import ParquetTakerFlowCatalog

_SPEC = {1: "1-MINUTE", 5: "5-MINUTE", 15: "15-MINUTE", 60: "1-HOUR", 240: "4-HOUR", 1440: "1-DAY"}
_CACHE_VERSION = 1


def interval_minutes(interval: str) -> int:
    unit, value = interval[-1], int(interval[:-1])
    return value * {"m": 1, "h": 60, "d": 1440}[unit]


def bar_type_for(symbol: str, interval: str, *, perp: bool) -> str:
    base = symbol.upper().removesuffix("-PERP")
    instrument = f"{base}-PERP" if perp else base
    return f"{instrument}.SIM-{_SPEC[interval_minutes(interval)]}-LAST-EXTERNAL"


def _minutes(stamps: Sequence[datetime]) -> IntArray:
    ns = np.array([datetime_to_nanos(ts) for ts in stamps], dtype=np.int64)
    return minutes_from_ns(ns)


def build_panel(
    *,
    bar_catalog: Path,
    symbols: Sequence[str],
    interval: str,
    perp: bool = True,
    funding_catalog: Path | None = None,
) -> Panel:
    bars_api = NautilusParquetCatalog(bar_catalog)
    taker_api = ParquetTakerFlowCatalog(bar_catalog)
    premium_api = ParquetPremiumIndexCatalog(bar_catalog)
    funding_api = ParquetFundingCatalog(funding_catalog or bar_catalog)

    columns: dict[str, dict[str, tuple[IntArray, FloatArray]]] = {
        name: {} for name in ("close", "high", "low", "volume", "taker_buy", "premium")
    }
    funding_events: dict[str, tuple[IntArray, FloatArray]] = {}
    grids: list[IntArray] = []
    for symbol in symbols:
        base = symbol.upper().removesuffix("-PERP")
        bars = bars_api.load(bar_type=bar_type_for(base, interval, perp=perp))
        ts = _minutes([bar.ts_utc for bar in bars])
        grids.append(ts)
        columns["close"][base] = (ts, np.array([float(b.close) for b in bars]))
        columns["high"][base] = (ts, np.array([float(b.high) for b in bars]))
        columns["low"][base] = (ts, np.array([float(b.low) for b in bars]))
        columns["volume"][base] = (ts, np.array([float(b.volume) for b in bars]))

        flow_symbol = f"{base}-PERP" if perp else base
        flow = taker_api.load(symbol=flow_symbol, interval=interval)
        columns["taker_buy"][base] = (
            _minutes(list(flow.keys())),
            np.array([float(v) for v in flow.values()]),
        )
        premium = premium_api.load(symbol=base, interval=interval) if perp else []
        columns["premium"][base] = (
            _minutes([p.ts_utc for p in premium]),
            np.array([float(p.close) for p in premium]),
        )
        snapshots = funding_api.load(symbol=base) if perp else []
        funding_events[base] = (
            _minutes([s.ts_utc for s in snapshots]),
            np.array([float(s.funding_rate) for s in snapshots]),
        )

    grid = np.unique(np.concatenate(grids)) if grids else np.empty(0, dtype=np.int64)
    fields = {name: align_columns(grid, series) for name, series in columns.items()}
    paid = np.full((grid.size, len(symbols)), np.nan)
    last = np.full((grid.size, len(symbols)), np.nan)
    for column, (events, rates) in enumerate(funding_events.values()):
        paid[:, column], last[:, column] = bucket_events(grid, events, rates)
    fields["funding_paid"] = paid
    fields["funding_last"] = last
    names = tuple(s.upper().removesuffix("-PERP") for s in symbols)
    return Panel(ts_min=grid, symbols=names, fields=fields, bar_minutes=interval_minutes(interval))


def save_panel(panel: Panel, path: Path, *, source: dict[str, str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "version": _CACHE_VERSION,
        "symbols": list(panel.symbols),
        "bar_minutes": panel.bar_minutes,
        "fields": sorted(panel.fields),
        "source": source or {},
    }
    # `Any` values: numpy's stub would otherwise match `**arrays` against the
    # `allow_pickle: bool` keyword and reject a perfectly valid call.
    arrays: dict[str, Any] = {f"field__{name}": values for name, values in panel.fields.items()}
    arrays["ts_min"] = panel.ts_min
    arrays["meta"] = np.array(json.dumps(meta))
    temporary = path.with_name(path.name + ".tmp.npz")
    np.savez_compressed(temporary, **arrays)
    temporary.replace(path)


def load_panel(path: Path) -> Panel:
    with np.load(path, allow_pickle=False) as data:
        meta = json.loads(str(data["meta"]))
        if meta.get("version") != _CACHE_VERSION:
            raise ValueError(f"panel cache {path} has version {meta.get('version')}; rebuild it")
        fields = {
            name: np.asarray(data[f"field__{name}"], dtype=np.float64) for name in meta["fields"]
        }
        return Panel(
            ts_min=np.asarray(data["ts_min"], dtype=np.int64),
            symbols=tuple(meta["symbols"]),
            fields=fields,
            bar_minutes=int(meta["bar_minutes"]),
        )


def load_or_build(
    cache: Path,
    *,
    rebuild: bool,
    bar_catalog: Path,
    symbols: Sequence[str],
    interval: str,
    perp: bool,
    funding_catalog: Path | None,
) -> Panel:
    wanted = tuple(s.upper().removesuffix("-PERP") for s in symbols)
    if cache.exists() and not rebuild:
        panel = load_panel(cache)
        if set(wanted) <= set(panel.symbols) and panel.bar_minutes == interval_minutes(interval):
            return panel.select_symbols(wanted)
    panel = build_panel(
        bar_catalog=bar_catalog,
        symbols=symbols,
        interval=interval,
        perp=perp,
        funding_catalog=funding_catalog,
    )
    save_panel(
        panel,
        cache,
        source={
            "bar_catalog": str(bar_catalog),
            "funding_catalog": str(funding_catalog or bar_catalog),
            "interval": interval,
        },
    )
    return panel
