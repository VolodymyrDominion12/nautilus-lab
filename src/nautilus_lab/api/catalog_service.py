from __future__ import annotations

import contextlib
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nautilus_trader.persistence.catalog import ParquetDataCatalog

from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.infrastructure.timeframe import interval_from_bar_type, nautilus_bar_type
from nautilus_lab.interfaces.composition import settings


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(ts_event_ns: int) -> str:
    """Nautilus nanosecond event timestamp -> ISO-8601 UTC string."""
    return datetime.fromtimestamp(ts_event_ns / 1_000_000_000, tz=UTC).isoformat()


#: The dashboard reads one catalog for the whole process, but the process is launched from
#: whatever directory the terminal happens to be in. `CATALOG_PATH=catalog` is relative, so
#: resolving it against the current working directory made `uvicorn` started from `frontend/`
#: describe an empty `frontend/catalog`: the chart then reported
#: "no bars in catalog ... Run `lab ingest` first." while `catalog/` sat full at the repo root.
#: `parents[3]` is that root for both an editable install and a source checkout
#: (`<root>/src/nautilus_lab/api/catalog_service.py`); when the package is installed elsewhere
#: that path carries no repo markers, and `repo_root()` falls back to the caller's cwd.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_REPO_MARKERS = ("pyproject.toml", ".env.example")


def repo_root() -> Path:
    """The project root when this package lives inside the repository, else the cwd."""
    if any((_REPO_ROOT / marker).exists() for marker in _REPO_MARKERS):
        return _REPO_ROOT
    return Path.cwd()


def resolve_catalog_path(catalog_path: str | None) -> Path:
    """Absolute catalog path. Relative paths mean "relative to the project root".

    Not the cwd: the server may be started from anywhere, and a cwd-relative `catalog` is
    how the dashboard ends up describing an empty directory while the data exists.
    """
    cfg = settings()
    raw = catalog_path or cfg.catalog_path
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = repo_root() / candidate
    return candidate.resolve()


def discover_catalog_paths(cfg: Settings | None = None) -> list[str]:
    """Find all catalog directories: configured paths + discovered directories on disk."""
    resolved = cfg or settings()
    paths: list[str] = []
    seen: set[str] = set()

    for p in resolved.all_catalog_paths():
        res = str(resolve_catalog_path(p))
        if res not in seen:
            seen.add(res)
            paths.append(p)

    root = repo_root()
    for entry in sorted(root.glob("catalog*")):
        if entry.is_dir() and (entry / "data").exists():
            res = str(entry.resolve())
            if res not in seen:
                seen.add(res)
                paths.append(entry.name)

    return paths


def describe_catalog(catalog_path: str | None = None) -> dict[str, Any]:
    resolved = resolve_catalog_path(catalog_path)
    default_interval = settings().bar_interval
    name = resolved.name
    if not resolved.exists():
        return {
            "catalog_path": str(resolved),
            "name": name,
            "exists": False,
            "bar_interval": default_interval,
            "market_type": "unknown",
            "total_instruments": 0,
            "total_bars": 0,
            "first_date": None,
            "last_date": None,
            "instruments": [],
        }

    try:
        cat = ParquetDataCatalog(str(resolved))
        instruments_info: list[dict[str, Any]] = []
        detected_interval: str | None = None
        for inst in cat.instruments():
            bars = cat.bars(instrument_ids=[str(inst.id)])
            count = len(bars)
            if detected_interval is None and count > 0:
                with contextlib.suppress(ValueError):
                    detected_interval = interval_from_bar_type(str(bars[0].bar_type))
            # ISO-8601, not `str(Timestamp)`: pandas renders its own nanosecond precision
            # ("2026-09-18 23:59:59.999000064"), which is not a format a browser is
            # obliged to parse and does not match the tick/funding series' timestamps.
            first_dt = _iso(bars[0].ts_event) if count > 0 else None
            last_dt = _iso(bars[-1].ts_event) if count > 0 else None
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

        eff_interval = detected_interval or default_interval
        total_bars = sum(int(i["bars_count"]) for i in instruments_info)
        first_dates = sorted([i["first_date"] for i in instruments_info if i.get("first_date")])
        last_dates = sorted(
            [i["last_date"] for i in instruments_info if i.get("last_date")], reverse=True
        )

        is_perp = (
            all(i["instrument_id"].endswith("-PERP.SIM") for i in instruments_info)
            if instruments_info
            else False
        )
        is_spot = (
            all(
                "/" in i["instrument_id"] and not i["instrument_id"].endswith("-PERP.SIM")
                for i in instruments_info
            )
            if instruments_info
            else False
        )
        if is_perp:
            mtype = "perp"
        elif is_spot:
            mtype = "spot"
        elif instruments_info:
            mtype = "mixed"
        else:
            mtype = "unknown"

        return {
            "catalog_path": str(resolved),
            "name": name,
            "exists": True,
            "bar_interval": eff_interval,
            "market_type": mtype,
            "instruments": instruments_info,
            "total_instruments": len(instruments_info),
            "total_bars": total_bars,
            "first_date": first_dates[0] if first_dates else None,
            "last_date": last_dates[0] if last_dates else None,
        }
    except Exception as exc:  # noqa: BLE001 — an unreadable catalog is reported, not raised
        return {
            "catalog_path": str(resolved),
            "name": name,
            "exists": True,
            "bar_interval": default_interval,
            "market_type": "unknown",
            "error": str(exc),
            "instruments": [],
            "total_instruments": 0,
            "total_bars": 0,
            "first_date": None,
            "last_date": None,
        }


def list_catalogs(cfg: Settings | None = None) -> dict[str, Any]:
    resolved = cfg or settings()
    catalogs: list[dict[str, Any]] = []
    all_symbols_set: set[str] = set()

    for path_str in discover_catalog_paths(resolved):
        summary = describe_catalog_cached(path_str)
        insts = summary.get("instruments", [])
        total_bars = summary.get("total_bars") or sum(int(i.get("bars_count", 0)) for i in insts)
        symbols = [str(i.get("raw_symbol") or i.get("instrument_id", "")) for i in insts]

        symbol_counts: dict[str, int] = {}
        for i in insts:
            raw = str(i.get("raw_symbol") or i.get("instrument_id", ""))
            clean_s = raw.removesuffix("-PERP").replace("/", "")
            symbol_counts[clean_s] = int(i.get("bars_count", 0))
            all_symbols_set.add(clean_s)

        path_obj = Path(summary["catalog_path"])
        name = summary.get("name") or path_obj.name
        data_dir = path_obj / "data"

        has_funding = (
            (data_dir / "funding").exists() and any((data_dir / "funding").iterdir())
            if (data_dir / "funding").exists()
            else False
        )
        has_premium_index = (
            (data_dir / "premium_index").exists() and any((data_dir / "premium_index").iterdir())
            if (data_dir / "premium_index").exists()
            else False
        )
        has_ticks = (
            (data_dir / "agg_trade").exists() and any((data_dir / "agg_trade").iterdir())
            if (data_dir / "agg_trade").exists()
            else False
        )
        has_orderbook = (
            ((data_dir / "orderbook").exists() and any((data_dir / "orderbook").iterdir()))
            or ((data_dir / "order_book").exists() and any((data_dir / "order_book").iterdir()))
            if (data_dir / "orderbook").exists() or (data_dir / "order_book").exists()
            else False
        )
        has_taker_flow = (
            (data_dir / "taker_flow").exists() and any((data_dir / "taker_flow").iterdir())
            if (data_dir / "taker_flow").exists()
            else False
        )

        catalogs.append(
            {
                "path": summary["catalog_path"],
                "name": name,
                "exists": summary.get("exists", False),
                "total_instruments": summary.get("total_instruments", 0),
                "total_bars": total_bars,
                "bar_interval": summary.get("bar_interval"),
                "market_type": summary.get("market_type", "unknown"),
                "first_date": summary.get("first_date"),
                "last_date": summary.get("last_date"),
                "symbols": symbols,
                "symbol_counts": symbol_counts,
                "has_funding": has_funding,
                "has_premium_index": has_premium_index,
                "has_ticks": has_ticks,
                "has_orderbook": has_orderbook,
                "has_taker_flow": has_taker_flow,
                "error": summary.get("error"),
            }
        )

    return {
        "default": resolved.catalog_path,
        "catalogs": catalogs,
        "all_symbols": sorted(all_symbols_set),
    }


# Describing a catalog loads every bar of every instrument from Parquet. The dashboard
# polls its status endpoint on a timer, so an uncached describe means re-reading the whole
# catalog several times a minute for numbers that only change when an ingest finishes.
# The cache is keyed by resolved absolute path and invalidated explicitly after ingest.
_CATALOG_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CATALOG_CACHE_TTL_SECONDS = 10.0


def invalidate_catalog_cache(catalog_path: str | None = None) -> None:
    """Drop cached catalog descriptions, for one path or all of them.

    The key must be built the way `describe_catalog_cached` builds it — resolving one of them
    against the cwd and the other against the project root would leave an ingest's cache entry
    in place, and the dashboard would keep reporting the pre-ingest bar counts.
    """
    if catalog_path is None:
        _CATALOG_CACHE.clear()
        return
    _CATALOG_CACHE.pop(str(resolve_catalog_path(catalog_path)), None)


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


def normalize_instrument_id(instrument_id: str) -> str:
    """Ensure an instrument id ends in .SIM and carries a valid currency-pair slash."""
    if instrument_id.endswith(".SIM"):
        return instrument_id
    if "/" not in instrument_id:
        from nautilus_lab.infrastructure.nautilus.instrument import binance_symbol_to_instrument_id

        try:
            return binance_symbol_to_instrument_id(instrument_id)
        except ValueError:
            return f"{instrument_id}.SIM"
    return f"{instrument_id}.SIM"


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
    raw_id = instrument_id or cfg.instrument_id
    resolved_id = normalize_instrument_id(raw_id)
    resolved_path = resolve_catalog_path(catalog_path)
    interval = bar_interval
    if not interval:
        desc = describe_catalog_cached(str(resolved_path))
        interval = desc.get("bar_interval") or cfg.bar_interval
    bar_type = nautilus_bar_type(resolved_id, interval)
    catalog = NautilusParquetCatalog(
        resolved_path,
        spot_fees=cfg.spot_fee_schedule(),
        usdm_fees=cfg.usdm_fee_schedule(),
    )
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
