"""Liveness, readiness, metrics and the dashboard's status and command-center views."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from nautilus_lab.api.catalog_service import describe_catalog_cached, resolve_catalog_path
from nautilus_lab.api.command_center import build_command_center, scan_triangular_demo
from nautilus_lab.api.context import Lab
from nautilus_lab.api.health import render_metrics
from nautilus_lab.api.paper_streamer import LIVE_PAPER_ROBOTS
from nautilus_lab.application.run_paper import PAPER_SUPPORTED_ROBOTS
from nautilus_lab.domain.regime import (
    BACKTEST_WIRED_ROBOTS,
    HAWKES_ROBOTS,
    TICK_VPIN_ROBOTS,
    RobotName,
)
from nautilus_lab.domain.stress_slices import STRESS_SLICES
from nautilus_lab.infrastructure.provenance import code_manifest

router = APIRouter()


@router.get("/")
def read_root() -> dict[str, str]:
    return {"status": "ok", "message": "Nautilus Lab API is running"}


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """The process answers. Says nothing about whether it trades (see /readyz)."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz(ctx: Lab) -> JSONResponse:
    """503 while a feed is silent or a running session cannot write its ledger.

    Outside /api on purpose: the Docker health check and an external uptime monitor call
    it without the dashboard token. It exposes symbols and ages, never balances.
    """
    readiness = ctx.readiness()
    return JSONResponse(status_code=200 if readiness.ready else 503, content=readiness.as_dict())


@router.get("/api/metrics")
def metrics(ctx: Lab) -> Response:
    """Prometheus text format. Under /api: behind the token, since it shows equity."""
    body = render_metrics(ctx.readiness(), ctx.sessions.sessions.values(), manifest=code_manifest())
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")


@router.get("/api/status")
def get_status(ctx: Lab, catalog_path: str | None = None) -> dict[str, Any]:
    """Dashboard heartbeat. `catalog_path` selects which catalog is described."""
    resolved_catalog = str(resolve_catalog_path(catalog_path))
    jobs = ctx.jobs.snapshot()
    summary = describe_catalog_cached(resolved_catalog)
    cfg = ctx.settings()
    return {
        "active_bots": 0,
        "research_running": jobs["research"]["running"],
        "ingest_running": jobs["ingest"]["running"],
        "ml_running": jobs["ml_train"]["running"],
        "paper_running": jobs["paper"]["running"],
        "jobs": jobs,
        "strategies_available": [item.value for item in RobotName],
        "wired_robots": sorted(item.value for item in BACKTEST_WIRED_ROBOTS),
        "tick_vpin_robots": sorted(item.value for item in TICK_VPIN_ROBOTS),
        "hawkes_robots": sorted(item.value for item in HAWKES_ROBOTS),
        "stress_slices": [
            {
                "name": item.name.value,
                "description": item.description,
                "start": item.start.isoformat(),
                "end": item.end.isoformat(),
            }
            for item in STRESS_SLICES.values()
        ],
        "catalog_exists": bool(summary.get("exists", False)),
        "catalog_instruments": int(summary.get("total_instruments", 0) or 0),
        "catalog_path": resolved_catalog,
        "bar_interval": cfg.bar_interval,
        "trading_mode": cfg.trading_mode.value,
        "paper_robots": sorted(item.value for item in PAPER_SUPPORTED_ROBOTS),
        "is_live": False,
        "live_safe_mode": "FAIL_CLOSED",
        "lab_role": ctx.security.role,
        "live_paper_robots": sorted(LIVE_PAPER_ROBOTS),
        "live_paper_persisted": ctx.sessions.persisted,
    }


@router.get("/api/command-center")
def get_command_center(ctx: Lab) -> dict[str, Any]:
    return build_command_center(
        reports_dir=ctx.reports_dir,
        catalog_dir=str(resolve_catalog_path(None)),
        research_running=ctx.jobs.active("research"),
        ingest_running=ctx.jobs.active("ingest"),
        ml_running=ctx.jobs.active("ml_train"),
        paper_running=ctx.jobs.active("paper"),
    )


@router.post("/api/scan/triangular")
def scan_triangular() -> dict[str, Any]:
    return scan_triangular_demo()
