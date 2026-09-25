"""Research runs: launch a walk-forward/backtest job, follow its log, read its history."""

from __future__ import annotations

import os
import re
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from nautilus_lab.api.catalog_service import resolve_catalog_path
from nautilus_lab.api.context import Lab, LabContext
from nautilus_lab.api.experiment_history import list_history, load_history_entry
from nautilus_lab.api.requests import ResearchRunRequest
from nautilus_lab.api.research_runner import (
    default_tearsheet_path,
    load_job_result,
    summary_from_result,
)
from nautilus_lab.api.responses import ActionResult
from nautilus_lab.domain.regime import RobotName, tick_filters_supported
from nautilus_lab.infrastructure.agg_trades_catalog import ParquetAggTradesCatalog
from nautilus_lab.infrastructure.nautilus.instrument import binance_symbol_for_instrument

router = APIRouter()


def _busy() -> dict[str, Any]:
    return {"status": "error", "message": "Another research process is already running."}


def _refuse_impossible(ctx: LabContext, req: ResearchRunRequest) -> None:
    """Refuse impossible combinations before the job is spawned and before the previous
    run's artifacts are cleared: a request that cannot mean anything should not cost a
    process launch and should not blank the dashboard's last result."""
    if req.full_sample and req.use_optuna and req.source == "catalog":
        raise HTTPException(
            status_code=400,
            detail=(
                "full_sample and use_optuna are mutually exclusive: full-sample is one "
                "in-sample run, Optuna needs a walk-forward split to select on."
            ),
        )
    if req.folds > 1 and req.is_start:
        raise HTTPException(
            status_code=400,
            detail=(
                "multi-window runs derive their own windows; drop the explicit is_start/"
                "oos_start dates or run a single fold."
            ),
        )
    if req.pbo and req.generate_tearsheet:
        raise HTTPException(
            status_code=400,
            detail=(
                "a PBO audit simulates blocks x configurations runs, so a tearsheet has no "
                "single run to draw; drop one of them."
            ),
        )

    # Tick-level filters are constructor inputs of the regime router, so on a robot that
    # never builds one they would be accepted and then ignored: the run would be labelled
    # tick-filtered while every decision came from the bar proxy.
    if req.tick_vpin or req.hawkes:
        unsupported = tick_filters_supported(
            RobotName(req.robot), tick_vpin=req.tick_vpin, hawkes=req.hawkes
        )
        if unsupported:
            raise HTTPException(status_code=400, detail=unsupported)
        if req.source != "catalog":
            raise HTTPException(
                status_code=400,
                detail=(
                    "tick-level filters need the aggregated-trade series, which only exists "
                    "for catalog runs; synthetic bars have no ticks to read."
                ),
            )
        symbol = binance_symbol_for_instrument(req.instrument_id or ctx.settings().instrument_id)
        ticks = ParquetAggTradesCatalog(resolve_catalog_path(req.catalog_path))
        if symbol and not ticks.series_exists(symbol):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"no aggregated-trade series for {symbol} in this catalog: run "
                    f"`lab ingest --trades --symbols {symbol}` first. The engine reads a "
                    "missing tick series as an empty one, which would leave the filter at "
                    "its defaults instead of failing."
                ),
            )


@router.post("/api/research", response_model=ActionResult, response_model_exclude_none=True)
def run_research(
    ctx: Lab, background_tasks: BackgroundTasks, req: ResearchRunRequest
) -> dict[str, Any]:
    if ctx.jobs.active("research"):
        return _busy()
    _refuse_impossible(ctx, req)
    if not ctx.jobs.reserve("research"):
        return _busy()

    # Cleared inside the request, so a poll straight after launch never shows the
    # previous run's result as this one's.
    (ctx.reports_dir / "last_run.log").write_text("", encoding="utf-8")
    (ctx.reports_dir / "last_run.json").unlink(missing_ok=True)

    tearsheet_path = None
    if req.generate_tearsheet and not req.pbo:
        tearsheet_path = default_tearsheet_path(ctx.reports_dir, req.robot)

    config = {**req.model_dump(), "tearsheet_path": tearsheet_path}
    ctx.jobs.submit(
        background_tasks,
        "research",
        lambda: ctx.jobs.run_module(
            "research",
            "nautilus_lab.api.run_research_job",
            config,
            log_name="last_run.log",
            json_name="last_run.json",
            clear_outputs=False,
        ),
    )
    return {
        "status": "started",
        "message": f"Research run launched for {req.robot} ({req.source} mode)",
        "command": (
            f"{ctx.jobs.python} -m nautilus_lab.api.run_research_job "
            f"robot={req.robot} source={req.source}"
        ),
    }


@router.post("/api/research/cancel", response_model=ActionResult, response_model_exclude_none=True)
def cancel_research(ctx: Lab) -> dict[str, Any]:
    if not ctx.jobs.cancel("research"):
        return {"status": "idle", "message": "No research process is running."}
    return {"status": "cancelled", "message": "Research process terminated."}


@router.get("/api/research/log")
def get_research_log(ctx: Lab) -> dict[str, Any]:
    is_running = ctx.jobs.active("research")
    log_path = ctx.reports_dir / "last_run.log"
    content = log_path.read_text(encoding="utf-8") if log_path.exists() else ""

    structured = load_job_result(ctx.reports_dir)
    summary = summary_from_result(structured)
    if structured is None and content:
        summary = legacy_summary_from_log(content)
    if is_running:
        summary = {**summary, "is_finished": False}

    return {
        "is_running": is_running,
        "log": content,
        "summary": summary,
        "result": structured,
    }


@router.get("/api/research/history")
def get_research_history(ctx: Lab, limit: int = 20) -> dict[str, Any]:
    return {"history": list_history(ctx.reports_dir, limit=limit)}


@router.get("/api/research/history/{history_id}")
def get_research_history_entry(ctx: Lab, history_id: str) -> dict[str, Any]:
    entry = load_history_entry(ctx.reports_dir, history_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"History entry not found: {history_id}")
    return {"entry": entry}


def legacy_summary_from_log(log_text: str) -> dict[str, Any]:
    """Summary of a run from before the structured result file existed: parse its log."""
    summary = summary_from_result(None)
    summary["is_finished"] = (
        "Process finished with code" in log_text or "Exception occurred" in log_text
    )
    summary["is_error"] = (
        "Process finished with code 1" in log_text
        or "Exception occurred" in log_text
        or "Traceback" in log_text
    )
    m_ts = re.search(r"tearsheet_saved=([^\s]+)", log_text)
    if m_ts:
        saved_path = m_ts.group(1)
        summary["tearsheet_url"] = f"/static_reports/{os.path.basename(saved_path)}"
    m_agg = re.search(
        r"out-of-sample aggregate profitable=(\d+/\d+)\s+mean=([^\s]+)"
        r"\s+median=([^\s]+)\s+worst=([^\s]+)\s+best=([^\s]+)",
        log_text,
    )
    m_bh = re.search(r"baseline buy&hold mean=([^\s]+)\s+oos_fills=(\d+)", log_text)
    if m_agg and m_bh:
        summary["multi_window"] = {
            "profitable": m_agg.group(1),
            "mean_oos": m_agg.group(2),
            "median_oos": m_agg.group(3),
            "worst_oos": m_agg.group(4),
            "best_oos": m_agg.group(5),
            "buy_and_hold_mean": m_bh.group(1),
            "total_oos_fills": int(m_bh.group(2)),
        }
    m_single = re.search(r"fills=(\d+)\s+positions=(\d+)\s+ending=([0-9.]+)", log_text)
    m_metrics = re.search(
        r"fees_paid=([0-9.]+)\s+max_dd=([0-9.]+)\s+turnover=([0-9.]+)\s+sharpe_like=([0-9.\-]+)",
        log_text,
    )
    if m_single:
        summary["single_backtest"] = {
            "fills": int(m_single.group(1)),
            "positions": int(m_single.group(2)),
            "ending_balance": float(m_single.group(3)),
            "fees_paid": float(m_metrics.group(1)) if m_metrics else 0.0,
            "max_dd_pct": f"{float(m_metrics.group(2)) * 100:.2f}%" if m_metrics else "0%",
            "turnover": float(m_metrics.group(3)) if m_metrics else 0.0,
            "sharpe": float(m_metrics.group(4)) if m_metrics else 0.0,
        }
    return summary
