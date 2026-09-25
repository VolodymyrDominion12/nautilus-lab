"""One `APIRouter` per area of the dashboard API (docs/27 E-2.1). `create_app` includes
them all; each takes the process state through the `Lab` dependency."""

from __future__ import annotations

from fastapi import APIRouter

from nautilus_lab.api.routes import catalog, library, live, ml, paper, research, settings, status

ROUTERS: tuple[APIRouter, ...] = (
    status.router,
    catalog.router,
    research.router,
    library.router,
    ml.router,
    paper.router,
    live.router,
    settings.router,
)
