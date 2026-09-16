from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
        "recent_experiments": history,
        "models": models[:5],
        "journal": journal_counts,
        "last_research": last_research,
    }


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
