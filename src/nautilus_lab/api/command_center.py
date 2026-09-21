from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nautilus_lab.api.data_health import describe_data_health_cached
from nautilus_lab.api.experiment_history import list_history
from nautilus_lab.api.journal_service import journal_summary
from nautilus_lab.api.ml_runner import list_models
from nautilus_lab.domain.regime import BACKTEST_WIRED_ROBOTS, RobotName


def build_command_center(
    *,
    reports_dir: Path,
    catalog_dir: str,
    research_running: bool,
    ingest_running: bool,
    ml_running: bool,
    paper_running: bool,
) -> dict[str, Any]:
    history = list_history(reports_dir, limit=5)
    models = list_models()
    journal_counts = journal_summary()
    last_research = _read_json(reports_dir / "last_run.json")
    health = describe_data_health_cached(catalog_dir)
    instruments = health.get("instruments") or []
    return {
        "jobs": {
            "research": {"running": research_running, "label": "Walk-forward / backtest"},
            "ingest": {"running": ingest_running, "label": "Binance klines ingest"},
            "ml_train": {"running": ml_running, "label": "LightGBM training"},
            "paper": {"running": paper_running, "label": "Paper order log"},
        },
        "safety": {"live_enabled": False, "mode": "FAIL_CLOSED"},
        "robots": {
            "total": len(RobotName),
            "wired": sorted(item.value for item in BACKTEST_WIRED_ROBOTS),
        },
        "catalog_path": catalog_dir,
        # Staleness is the first question a research dashboard has to answer: a catalog
        # that ends months ago silently turns every walk-forward into a study of the past.
        "catalog_last_date": _last_date(instruments),
        "catalog_total_bars": _total_bars(instruments),
        "catalog_bar_interval": health.get("bar_interval"),
        "data_series": _series_summary(instruments),
        "recent_experiments": history,
        "models": models[:5],
        "journal": journal_counts,
        "last_research": last_research,
    }


def _last_date(instruments: list[dict[str, Any]]) -> str | None:
    dates = [
        str(entry["bars"]["last"])
        for entry in instruments
        if isinstance(entry.get("bars"), dict) and entry["bars"].get("last")
    ]
    return max(dates) if dates else None


def _total_bars(instruments: list[dict[str, Any]]) -> int:
    return sum(
        int(entry["bars"].get("rows") or 0)
        for entry in instruments
        if isinstance(entry.get("bars"), dict)
    )


def _series_summary(instruments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per instrument: which optional series exist beside its bars."""
    rows: list[dict[str, Any]] = []
    for entry in instruments:
        ticks = entry.get("ticks") or {}
        taker_flow = entry.get("taker_flow") or {}
        orderbook = entry.get("orderbook") or {}
        funding = entry.get("funding") or {}
        bars = entry.get("bars") or {}
        rows.append(
            {
                "instrument_id": entry.get("instrument_id"),
                "symbol": entry.get("symbol"),
                "bars": int(bars.get("rows") or 0),
                "bars_last": bars.get("last"),
                "taker_flow": bool(taker_flow.get("present")),
                "ticks": bool(ticks.get("present")),
                "tick_rows": ticks.get("rows"),
                "tick_last": ticks.get("last"),
                "orderbook": bool(orderbook.get("present")),
                "orderbook_rows": orderbook.get("rows"),
                "funding": bool(funding.get("present")),
            }
        )
    return rows


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else None


def scan_triangular_demo() -> dict[str, Any]:
    from decimal import Decimal

    from nautilus_lab.application.scan_triangular import scan_triangular_opportunities

    rates = {
        ("USDT", "BTC"): Decimal("0.000015"),
        ("BTC", "ETH"): Decimal("15"),
        ("ETH", "USDT"): Decimal("3500"),
    }
    opportunities = scan_triangular_opportunities(rates)
    return {
        "opportunities": [
            {"cycle": item.cycle, "profit_log": str(item.profit_log)} for item in opportunities
        ],
        "count": len(opportunities),
        "note": "Demo rates only — not live market data.",
    }
