"""Batch backtests: launch a robots x instruments matrix, read its table and each run.

The batch runs as one background process (`api/run_batch_job.py`) that owns its
`batch.json`; these endpoints create a batch, start that process, and read what it wrote.
Status survives an API restart because it lives in the file, not in this process.

Per-fold decisions of a run are served here **and** through the existing
`/api/paper/sessions/{fold-session}/…` endpoints (`routes/live.py` falls back to the batch
directory), so the trade page behind a link works the same for a batch fold, a single
research run and a live paper session.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from nautilus_lab.api.batch_store import (
    RUNNING,
    batch_dir,
    batch_payload,
    cell_dir,
    create_batch,
    decision_reader,
    delete_batch,
    effective_status,
    fold_sessions,
    import_sweep,
    list_batches,
    load_batch,
    pid_alive,
    read_json,
    request_from_dict,
    reset_batch,
    run_payload,
)
from nautilus_lab.api.context import Lab, LabContext, python_executable
from nautilus_lab.application.batch_plan import (
    DEFAULT_ROBOTS,
    DEFAULT_SYMBOLS,
    BatchCell,
    BatchRequest,
    plan_cells,
)
from nautilus_lab.application.decision_digest import build_digest, digest_markdown
from nautilus_lab.application.decision_margins import margin_distribution
from nautilus_lab.application.trade_history import (
    reconstruct_trades_from_decisions,
    trade_summary,
)
from nautilus_lab.domain.regime import BACKTEST_WIRED_ROBOTS

router = APIRouter()

#: Child processes started by this API process, reaped by a waiter thread each.
_PROCESSES: dict[str, subprocess.Popen[bytes]] = {}


class BatchRunRequest(BaseModel):
    robots: list[str] = Field(default_factory=lambda: list(DEFAULT_ROBOTS))
    symbols: list[str] = Field(default_factory=lambda: list(DEFAULT_SYMBOLS))
    interval: str = "1h"
    catalog: str = "catalog"
    funding_catalog: str = "catalog_2019_4h"
    funding_interval: str = "4h"
    folds: int = 4
    is_fraction: str = "0.7"
    parallel: int = 2
    label: str = ""
    days: int | None = None
    env: dict[str, str] = Field(default_factory=dict)
    dry_run: bool = False


def _to_request(req: BatchRunRequest) -> BatchRequest:
    try:
        days = req.days
        if days is None and "BACKTEST_DAYS" in req.env:
            try:
                days = int(req.env["BACKTEST_DAYS"])
            except ValueError as exc:
                raise HTTPException(
                    status_code=422, detail=f"invalid BACKTEST_DAYS: {req.env['BACKTEST_DAYS']}"
                ) from exc
        return BatchRequest(
            robots=tuple(req.robots),
            symbols=tuple(s.upper() for s in req.symbols),
            interval=req.interval,
            catalog=req.catalog,
            funding_catalog=req.funding_catalog,
            funding_interval=req.funding_interval,
            folds=req.folds,
            is_fraction=Decimal(req.is_fraction),
            parallel=req.parallel,
            label=req.label,
            days=days,
            env=dict(req.env),
        )
    except (ValueError, InvalidOperation) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _running_batch(ctx: LabContext) -> str | None:
    for row in list_batches(ctx.reports_dir, limit=20):
        if row["status"] in (RUNNING, "queued") and row.get("imported_from") is None:
            batch = load_batch(ctx.reports_dir, str(row["id"])) or {}
            if pid_alive(batch.get("pid")) or str(row["id"]) in _PROCESSES:
                return str(row["id"])
    return None


def _launch(ctx: LabContext, batch_id: str, path: Path) -> None:
    cmd = [
        python_executable(ctx.root),
        "-m",
        "nautilus_lab.api.run_batch_job",
        "--batch-dir",
        str(path),
    ]
    log = (path / "batch.log").open("wb")
    process = subprocess.Popen(  # noqa: S603 — fixed argv built by the API, no shell
        cmd, cwd=ctx.root, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
    )
    _PROCESSES[batch_id] = process

    def reap() -> None:
        try:
            process.wait()
        finally:
            log.close()
            _PROCESSES.pop(batch_id, None)

    threading.Thread(target=reap, name=f"batch-{batch_id}", daemon=True).start()


def _plan_payload(cells: list[BatchCell]) -> list[dict[str, Any]]:
    return [
        {
            "cell_id": cell.cell_id,
            "robot": cell.robot,
            "symbol": cell.symbol,
            "interval": cell.interval,
            "catalog": cell.catalog,
            "runnable": cell.runnable,
            "blocked": cell.blocked,
        }
        for cell in cells
    ]


def _planned_cells(ctx: LabContext, request: BatchRequest) -> list[BatchCell]:
    return plan_cells(
        request,
        exists=lambda rel: (ctx.root / rel).exists(),
        wired=[robot.value for robot in BACKTEST_WIRED_ROBOTS],
    )


@router.post("/api/batches")
def start_batch(ctx: Lab, req: BatchRunRequest) -> dict[str, Any]:
    """Plan the matrix; unless `dry_run`, write the batch and start its process."""
    request = _to_request(req)
    cells = _planned_cells(ctx, request)
    plan = _plan_payload(cells)
    if req.dry_run:
        return {"status": "ok", "dry_run": True, "cells": plan}
    if not any(cell.runnable for cell in cells):
        raise HTTPException(status_code=422, detail="no runnable cell in this batch")
    busy = _running_batch(ctx)
    if busy is not None:
        raise HTTPException(status_code=409, detail=f"batch {busy} is still running")
    batch_id, path = create_batch(ctx.reports_dir, request, cells)
    _launch(ctx, batch_id, path)
    return {"status": "started", "batch_id": batch_id, "cells": plan}


@router.get("/api/batches")
def get_batches(ctx: Lab, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    return {"status": "ok", "batches": list_batches(ctx.reports_dir, limit=limit)}


@router.post("/api/batches/import-sweep")
def import_decision_sweep(ctx: Lab) -> dict[str, Any]:
    """Bring `reports/decision-sweep/` (the 2026-09-29 sweep) into the batch table."""
    sweep = ctx.reports_dir / "decision-sweep"
    if not (sweep / "status.json").exists():
        raise HTTPException(status_code=404, detail="reports/decision-sweep/status.json not found")
    return {"status": "ok", "batch_id": import_sweep(ctx.reports_dir, sweep)}


def _batch_or_404(ctx: LabContext, batch_id: str) -> dict[str, Any]:
    try:
        payload = batch_payload(ctx.reports_dir, batch_id, ctx.settings())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail=f"batch {batch_id!r} not found")
    return payload


@router.get("/api/batches/{batch_id}")
def get_batch(ctx: Lab, batch_id: str) -> dict[str, Any]:
    return {"status": "ok", "batch": _batch_or_404(ctx, batch_id)}


@router.post("/api/batches/{batch_id}/cancel")
def cancel_batch(ctx: Lab, batch_id: str) -> dict[str, Any]:
    batch = load_batch(ctx.reports_dir, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"batch {batch_id!r} not found")
    pid = batch.get("pid")
    if not isinstance(pid, int) or effective_status(batch) != RUNNING or not pid_alive(pid):
        return {"status": "idle", "message": "batch is not running"}
    os.kill(pid, signal.SIGTERM)
    return {"status": "cancelling", "message": f"sent SIGTERM to batch {batch_id}"}


@router.post("/api/batches/{batch_id}/restart")
def restart_batch(ctx: Lab, batch_id: str) -> dict[str, Any]:
    """Delete this batch's results and run the same request again, under the same id.

    The record the researcher clicked keeps its address (`#/batch/<id>`): what is re-run is
    the request stored in `batch.json`, and what is thrown away is the data — decisions,
    cached summaries, logs and the trial ledger (`batch_store.reset_batch`). Keeping the id
    while deleting the artifacts is the point: a restart that appended to the old run would
    show old numbers under a new status.

    Refused for an imported sweep (its stored request holds robots but no symbols/intervals,
    so there is nothing to re-run) and while any batch is still running — cancel it first,
    a second batch would fight the first over the same cores. `422` when the re-planned
    matrix has no runnable cell left (its model or catalog went away).
    """
    try:
        batch = load_batch(ctx.reports_dir, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if batch is None:
        raise HTTPException(status_code=404, detail=f"batch {batch_id!r} not found")
    if batch.get("imported_from"):
        raise HTTPException(
            status_code=422,
            detail="an imported batch keeps no runnable request: launch it as a new batch",
        )
    try:
        request = request_from_dict(batch.get("request") or {})
    except (ValueError, KeyError, ArithmeticError) as exc:
        raise HTTPException(
            status_code=422, detail=f"batch {batch_id!r} has no re-runnable request: {exc}"
        ) from exc
    busy = _running_batch(ctx)
    if busy is not None:
        raise HTTPException(
            status_code=409, detail=f"batch {busy} is still running, cancel it before restarting"
        )
    cells = _planned_cells(ctx, request)
    if not any(cell.runnable for cell in cells):
        raise HTTPException(status_code=422, detail="no runnable cell in this batch")
    path = reset_batch(ctx.reports_dir, batch_id, cells)
    _launch(ctx, batch_id, path)
    return {"status": "restarted", "batch_id": batch_id, "cells": _plan_payload(cells)}


@router.delete("/api/batches/{batch_id}")
def delete_batch_route(ctx: Lab, batch_id: str) -> dict[str, Any]:
    proc = _PROCESSES.pop(batch_id, None)
    if proc is not None:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            proc.kill()
            proc.wait(timeout=2)
    try:
        deleted = delete_batch(ctx.reports_dir, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"batch {batch_id!r} not found")
    return {"status": "ok", "deleted": batch_id}


# --- one run (cell) of a batch --------------------------------------------------------


def _cell_path(ctx: LabContext, batch_id: str, cell_id: str) -> Path:
    try:
        path = cell_dir(batch_dir(ctx.reports_dir, batch_id), cell_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"run {batch_id}/{cell_id} not found")
    return path


def _fold_session(path: Path, fold: int | None) -> list[str]:
    sessions = fold_sessions(read_json(path / "last_run.json"), path)
    if fold is None:
        return [str(item["session_id"]) for item in sessions]
    for item in sessions:
        if item.get("index") == fold:
            return [str(item["session_id"])]
    raise HTTPException(status_code=404, detail=f"fold {fold} has no decisions")


@router.get("/api/batches/{batch_id}/runs/{cell_id}")
def get_run(ctx: Lab, batch_id: str, cell_id: str) -> dict[str, Any]:
    try:
        payload = run_payload(ctx.reports_dir, batch_id, cell_id, ctx.settings())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail=f"run {batch_id}/{cell_id} not found")
    return {"status": "ok", "run": payload}


@router.get("/api/batches/{batch_id}/runs/{cell_id}/decisions")
def get_run_decisions(
    ctx: Lab,
    batch_id: str,
    cell_id: str,
    fold: int | None = Query(None, ge=0),
    lines: int = Query(500, ge=1, le=20000),
    outcome: str | None = Query(None, description="Comma-separated outcome codes"),
    kind: str | None = Query(None, pattern="^(bar_decision|intrabar)$"),
    regime: str | None = None,
    signal_side: str | None = Query(None, alias="signal", pattern="^(buy|sell|flat)$"),
) -> dict[str, Any]:
    path = _cell_path(ctx, batch_id, cell_id)
    reader = decision_reader(path, ctx.settings())
    outcomes = [item.strip() for item in outcome.split(",") if item.strip()] if outcome else None
    logs: list[dict[str, Any]] = []
    for session in _fold_session(path, fold):
        logs.extend(
            reader.get_recent_logs(
                session,
                lines=lines,
                outcomes=outcomes,
                kind=kind,
                regime=regime,
                signal=signal_side,
            )
        )
    return {"status": "ok", "logs": logs[-lines:]}


@router.get("/api/batches/{batch_id}/runs/{cell_id}/trades")
def get_run_trades(
    ctx: Lab, batch_id: str, cell_id: str, fold: int | None = Query(None, ge=0)
) -> dict[str, Any]:
    """Trades of every fold (or one), each tagged with the fold session it links to."""
    path = _cell_path(ctx, batch_id, cell_id)
    reader = decision_reader(path, ctx.settings())
    rows: list[dict[str, Any]] = []
    for index, session in enumerate(_fold_session(path, fold)):
        logs = reader.get_recent_logs(session, lines=200_000)
        for trade in reconstruct_trades_from_decisions(logs):
            summary = trade_summary(trade)
            summary["fold"] = fold if fold is not None else index
            summary["fold_session"] = session
            rows.append(summary)
    return {"status": "ok", "trades": rows}


@router.get("/api/batches/{batch_id}/runs/{cell_id}/digest")
def get_run_digest(
    ctx: Lab, batch_id: str, cell_id: str, fold: int | None = Query(None, ge=0)
) -> dict[str, Any]:
    path = _cell_path(ctx, batch_id, cell_id)
    reader = decision_reader(path, ctx.settings())
    logs: list[dict[str, Any]] = []
    for session in _fold_session(path, fold):
        logs.extend(reader.get_recent_logs(session, lines=200_000))
    digest = build_digest(logs)
    return {"status": "ok", "digest": digest.as_dict(), "markdown": digest_markdown(digest)}


@router.get("/api/batches/{batch_id}/runs/{cell_id}/margins")
def get_run_margins(
    ctx: Lab, batch_id: str, cell_id: str, fold: int | None = Query(None, ge=0)
) -> dict[str, Any]:
    """Distance to threshold of every logged condition, for the "threshold ±X%" slider."""
    path = _cell_path(ctx, batch_id, cell_id)
    reader = decision_reader(path, ctx.settings())
    logs: list[dict[str, Any]] = []
    for session in _fold_session(path, fold):
        logs.extend(reader.get_recent_logs(session, lines=200_000))
    return {"status": "ok", "margins": margin_distribution(logs)}
