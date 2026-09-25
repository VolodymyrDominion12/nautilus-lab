"""Catalog browsing, data coverage and the ingest job."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from nautilus_lab.api.catalog_service import (
    describe_catalog,
    invalidate_catalog_cache,
    list_catalogs,
    load_catalog_bars,
    resolve_catalog_path,
)
from nautilus_lab.api.context import Lab
from nautilus_lab.api.data_health import (
    describe_data_health_cached,
    invalidate_data_health_cache,
)
from nautilus_lab.api.requests import IngestRunRequest
from nautilus_lab.api.responses import ActionResult, CatalogsResponse, JobLogResponse

router = APIRouter()

#: Kinds of ingest the dashboard may launch, mapped to the CLI flag that selects them.
#: `depth` is the odd one out: it captures live L2 snapshots over a WebSocket and runs
#: until it is stopped, where the other three backfill a bounded REST window.
INGEST_SERIES_FLAGS: dict[str, list[str]] = {
    "klines": [],
    "trades": ["--trades"],
    "funding": ["--funding"],
    "depth": ["--depth"],
}

#: Series that need exactly one symbol. `--depth` opens one WebSocket per run, and the CLI
#: silently keeps the first symbol and drops the rest, which would look like a two-symbol
#: capture while only one was recorded.
SINGLE_SYMBOL_SERIES = frozenset({"depth"})

#: Series whose window comes from the capture itself rather than from `--start/--end`.
WINDOWLESS_SERIES = frozenset({"depth"})


def _busy() -> dict[str, Any]:
    return {"status": "error", "message": "An ingest process is already running."}


@router.get("/api/catalogs", response_model=CatalogsResponse)
def get_catalogs() -> dict[str, Any]:
    return list_catalogs()


@router.get("/api/catalog")
def get_catalog(catalog_path: str | None = None) -> dict[str, Any]:
    return describe_catalog(catalog_path)


@router.get("/api/catalog/bars")
def get_catalog_bars(
    instrument_id: str | None = None,
    catalog_path: str | None = None,
    bar_interval: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    try:
        return load_catalog_bars(
            instrument_id=instrument_id,
            catalog_path=catalog_path or str(resolve_catalog_path(None)),
            bar_interval=bar_interval,
            start=start,
            end=end,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/data")
def get_data_health(catalog_path: str | None = None) -> dict[str, Any]:
    """Which of the four series trees this catalog actually holds, and how far each reaches.

    The engine reads a missing tick/funding series as an empty one, so "the run finished"
    is not evidence that the filter it was configured with had any data behind it.
    """
    return describe_data_health_cached(catalog_path)


def _catalog_arg(cmd: list[str]) -> str | None:
    """The `--catalog` value in a built CLI command, if the flag carries one."""
    if "--catalog" not in cmd:
        return None
    index = cmd.index("--catalog") + 1
    return cmd[index] if index < len(cmd) else None


def _refuse_impossible(req: IngestRunRequest) -> None:
    if req.series not in INGEST_SERIES_FLAGS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unknown series {req.series!r}; use one of: "
                f"{', '.join(sorted(INGEST_SERIES_FLAGS))}"
            ),
        )
    if req.incremental and req.series != "klines":
        # `--incremental` walks forward from the last stored bar, which only the bar series
        # has; the CLI ignores it for the others, so accepting it here would look like a
        # partial fetch while the full window was pulled anyway.
        raise HTTPException(
            status_code=400,
            detail=(
                f"incremental only applies to the bar series; a {req.series} ingest always "
                "walks the requested window."
            ),
        )
    symbols = [item.strip() for item in (req.symbols or "").split(",") if item.strip()]
    if req.series in SINGLE_SYMBOL_SERIES and len(symbols) > 1:
        raise HTTPException(
            status_code=400,
            detail=(
                f"a {req.series} ingest captures one symbol at a time; got {len(symbols)}. "
                "Run it once per symbol."
            ),
        )
    if req.series in WINDOWLESS_SERIES and (req.start or req.end):
        raise HTTPException(
            status_code=400,
            detail=(
                f"a {req.series} ingest has no window to request: it records from the moment "
                "it starts until it is stopped. Drop start/end."
            ),
        )


@router.post("/api/catalog/ingest", response_model=ActionResult, response_model_exclude_none=True)
def run_ingest(
    ctx: Lab, background_tasks: BackgroundTasks, req: IngestRunRequest
) -> dict[str, Any]:
    if ctx.jobs.active("ingest"):
        return _busy()
    _refuse_impossible(req)

    log_path = ctx.reports_dir / "ingest.log"
    log_path.write_text("", encoding="utf-8")

    cmd = [ctx.jobs.python, "-m", "nautilus_lab.interfaces.cli", "ingest"]
    cmd.extend(INGEST_SERIES_FLAGS[req.series])
    if req.symbols:
        cmd.extend(["--symbols", req.symbols])
    if req.start and req.series not in WINDOWLESS_SERIES:
        cmd.extend(["--start", req.start])
    if req.end and req.series not in WINDOWLESS_SERIES:
        cmd.extend(["--end", req.end])
    if req.catalog:
        cmd.extend(["--catalog", req.catalog])
    if req.incremental:
        cmd.append("--incremental")

    if not ctx.jobs.reserve("ingest"):
        return _busy()

    def work() -> None:
        if ctx.jobs.run_to_log("ingest", cmd, log_path) is None:
            return
        # The status endpoint caches catalog descriptions; an ingest is exactly the event
        # that makes the cached counts wrong. The coverage panel caches the same way.
        invalidate_catalog_cache(_catalog_arg(cmd))
        invalidate_data_health_cache(_catalog_arg(cmd))

    ctx.jobs.submit(background_tasks, "ingest", work)
    return {
        "status": "started",
        "message": f"Ingest started for symbols: {req.symbols}",
        "command": " ".join(cmd),
    }


@router.post(
    "/api/catalog/ingest/cancel", response_model=ActionResult, response_model_exclude_none=True
)
def cancel_ingest(ctx: Lab) -> dict[str, Any]:
    if not ctx.jobs.cancel("ingest"):
        return {"status": "idle", "message": "No ingest process is running."}
    return {"status": "cancelled", "message": "Ingest process terminated."}


@router.get("/api/catalog/ingest/log", response_model=JobLogResponse)
def get_ingest_log(ctx: Lab) -> dict[str, Any]:
    log_path = ctx.reports_dir / "ingest.log"
    content = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    return {"is_running": ctx.jobs.active("ingest"), "log": content}
