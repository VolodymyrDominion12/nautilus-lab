"""The dashboard API: `create_app(settings)` and the `app` uvicorn serves.

    uvicorn nautilus_lab.api.app:app

Routes live in `api/routes/` (one router per area), process state in `LabContext`
(`api/context.py`), background jobs in `JobManager` (`api/jobs.py`). This module only
wires them: middleware, static mounts, the lifespan. A test builds its own app from its
own settings with `create_app(cfg)` instead of patching globals here (docs/27 E-2.1).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from nautilus_lab.api.context import ROOT_DIR, LabContext
from nautilus_lab.api.health import run_watchdog
from nautilus_lab.api.jobs import JobManager
from nautilus_lab.api.live_paper_boot import boot_sessions, ensure_journal_writable
from nautilus_lab.api.routes import ROUTERS
from nautilus_lab.api.security import TOKEN_HEADER
from nautilus_lab.infrastructure.provenance import code_manifest
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.interfaces.composition import notifier

__all__ = ["app", "create_app"]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    ctx: LabContext = app.state.lab
    cfg = ctx.settings()
    # A configured journal nobody can write to stops the process instead of decorating
    # the log: sessions would run in memory, the dashboard would look healthy and the
    # ledger would be empty. Better to crash-loop visibly than to lie quietly.
    ensure_journal_writable(cfg, root=ctx.root)
    # Resume every unfinished live paper session, then bring up the declared portfolio.
    # Shutdown deliberately does NOT stop them: sessions ended by SIGTERM (deploy, reboot)
    # must resume, and only a session a person stopped is final in its journal.
    boot_lines = await boot_sessions(ctx.sessions, cfg, root=ctx.root)
    for line in boot_lines:
        print(f"live paper boot: {line}", flush=True)
    # Jobs a previous API process left behind: adopt the living, record the lost.
    for line in await asyncio.to_thread(ctx.jobs.adopt):
        print(f"jobs boot: {line}", flush=True)
    alerts = notifier(cfg)
    if ctx.sessions.active():
        # One message per start: a deploy or a crash-restart is visible where the alerts
        # go, with the code revision the ledgers continue under.
        await asyncio.to_thread(
            alerts.notify,
            f"live paper started: {code_manifest().summary_line()}; " + "; ".join(boot_lines),
            "INFO",
        )
    watchdog: asyncio.Task[None] | None = None
    if cfg.live_paper_watchdog_seconds > 0:
        watchdog = asyncio.create_task(
            run_watchdog(
                ctx.readiness,
                alerts,
                every_seconds=cfg.live_paper_watchdog_seconds,
                sessions=lambda: list(ctx.sessions.sessions.values()),
                heartbeat=ctx.heartbeat(),
            )
        )
    yield
    if watchdog is not None:
        watchdog.cancel()


def create_app(
    cfg: Settings | None = None,
    *,
    root: Path = ROOT_DIR,
    jobs: JobManager | None = None,
) -> FastAPI:
    """A fresh API. `cfg=None` reads `.env` per request, as the served app always has."""
    ctx = LabContext.build(cfg, root=root, jobs=jobs)
    app = FastAPI(title="Nautilus Lab API", lifespan=_lifespan)
    app.state.lab = ctx

    ctx.reports_dir.mkdir(parents=True, exist_ok=True)
    ctx.hypotheses_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static_reports", StaticFiles(directory=ctx.reports_dir), name="static_reports")
    app.mount(
        "/static_hypotheses", StaticFiles(directory=ctx.hypotheses_dir), name="static_hypotheses"
    )

    @app.middleware("http")
    async def _security_gate(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        reason = ctx.security.refusal(
            method=request.method,
            path=request.url.path,
            origin=request.headers.get("origin"),
            presented_token=request.headers.get(TOKEN_HEADER),
        )
        if reason is not None:
            return JSONResponse(status_code=403, content={"detail": reason})
        return await call_next(request)

    # Registered after the gate so it wraps it: a refusal to an allowed origin still
    # carries CORS headers and the dashboard can show the reason instead of a bare
    # network error.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(ctx.security.allowed_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in ROUTERS:
        app.include_router(router)
    return app


app = create_app()
