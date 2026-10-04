"""Catalog browsing, data coverage and the ingest job."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from nautilus_lab.api.catalog_service import (
    describe_catalog,
    describe_catalog_cached,
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
from nautilus_lab.api.responses import (
    ActionResult,
    CatalogBarsResponse,
    CatalogResponse,
    CatalogsResponse,
    JobLogResponse,
)

router = APIRouter()

#: Kinds of ingest the dashboard may launch, mapped to the CLI flag that selects them.
#: `depth` is the odd one out: it captures live L2 snapshots over a WebSocket and runs
#: until it is stopped, where the other three backfill a bounded REST window.
INGEST_SERIES_FLAGS: dict[str, list[str]] = {
    "klines": [],
    "trades": ["--trades"],
    "funding": ["--funding"],
    "depth": ["--depth"],
    "premium_index": ["--premium-index"],
}

#: Series that need exactly one symbol. `--depth` opens one WebSocket per run, and the CLI
#: silently keeps the first symbol and drops the rest, which would look like a two-symbol
#: capture while only one was recorded.
SINGLE_SYMBOL_SERIES = frozenset({"depth"})

#: Series whose window comes from the capture itself rather than from `--start/--end`.
WINDOWLESS_SERIES = frozenset({"depth"})


#: Archive series -> `lab ingest-archive --dataset`. Ticks and depth have no archive path
#: here: depth is live-only and the tick archive is far larger than this dashboard
#: should start with one click.
ARCHIVE_DATASETS: dict[str, str] = {
    "klines": "klines",
    "funding": "funding",
    "premium_index": "premium",
}
INGEST_SOURCES = frozenset({"rest", "archive"})


def _busy() -> dict[str, Any]:
    return {"status": "error", "message": "An ingest process is already running."}


@router.get("/api/catalogs", response_model=CatalogsResponse)
def get_catalogs() -> dict[str, Any]:
    return list_catalogs()


@router.get("/api/catalog", response_model=CatalogResponse)
def get_catalog(catalog_path: str | None = None) -> dict[str, Any]:
    return describe_catalog(catalog_path)


@router.get("/api/catalog/bars", response_model=CatalogBarsResponse)
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


def _market_of(req: IngestRunRequest) -> str:
    """`spot` or `perp` for a bar ingest: explicit for the archive, from symbols for REST."""
    if req.source == "archive":
        return "perp" if (req.market or "spot") == "um" else "spot"
    symbols = [item.strip() for item in (req.symbols or "").split(",") if item.strip()]
    return "perp" if symbols and all(item.endswith("-PERP") for item in symbols) else "spot"


def _refuse_catalog_mismatch(req: IngestRunRequest) -> None:
    """Bars must land in a catalog of the same interval and market (docs/34, F4).

    Writing 4h bars into a 1d catalog, or perps into a spot one, used to succeed: the
    catalog then reported the first instrument's interval and a "mixed" market, and
    every later read picked the wrong series.
    """
    if req.series != "klines" or not req.catalog:
        return
    summary = describe_catalog_cached(req.catalog)
    if not summary.get("exists") or not summary.get("instruments"):
        return
    interval = req.interval
    held = summary.get("bar_interval")
    if interval and held and held != interval:
        raise HTTPException(
            status_code=400,
            detail=(
                f"catalog {summary.get('name')} holds {held} bars; a {interval} ingest belongs "
                f"in its own catalog (e.g. catalog_{_market_of(req)}_{interval})."
            ),
        )
    market = summary.get("market_type")
    wanted = _market_of(req)
    if market in {"spot", "perp"} and market != wanted:
        raise HTTPException(
            status_code=400,
            detail=(
                f"catalog {summary.get('name')} is a {market} catalog; {wanted} bars belong "
                f"in catalog_{wanted}_{interval or held}."
            ),
        )


def _refuse_impossible(req: IngestRunRequest) -> None:
    if req.source not in INGEST_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown source {req.source!r}; use one of: rest, archive",
        )
    if req.source == "archive" and req.series not in ARCHIVE_DATASETS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"the archive path ingests {', '.join(sorted(ARCHIVE_DATASETS))}; "
                f"{req.series} comes from the REST/live path"
            ),
        )
    if req.source == "archive" and req.incremental:
        raise HTTPException(
            status_code=400,
            detail="the archive path is incremental by its cache; drop `incremental`",
        )
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
    _refuse_catalog_mismatch(req)

    log_path = ctx.reports_dir / "ingest.log"
    log_path.write_text("", encoding="utf-8")

    if req.source == "archive":
        cmd = _archive_command(ctx.jobs.python, req)
        if not ctx.jobs.reserve("ingest"):
            return _busy()

        def archive_work() -> None:
            if ctx.jobs.run_to_log("ingest", cmd, log_path) is None:
                return
            # The archive run may create catalogs and touch several of them (funding
            # goes into every perp catalog): drop every cached description.
            invalidate_catalog_cache(None)
            invalidate_data_health_cache(None)

        ctx.jobs.submit(background_tasks, "ingest", archive_work)
        return {
            "status": "started",
            "message": f"Archive ingest started for symbols: {req.symbols}",
            "command": " ".join(cmd),
        }

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
    if req.interval:
        cmd.extend(["--interval", req.interval])
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


def _archive_command(python: str, req: IngestRunRequest) -> list[str]:
    cmd = [
        python,
        "-m",
        "nautilus_lab.interfaces.cli",
        "ingest-archive",
        "--dataset",
        ARCHIVE_DATASETS[req.series],
        "--symbols",
        req.symbols or "BTCUSDT,ETHUSDT",
    ]
    if req.series == "klines":
        cmd.extend(["--market", "um" if req.market == "um" else "spot"])
    if req.series in {"klines", "premium_index"}:
        cmd.extend(["--interval", req.interval or "1d"])
    if req.start:
        cmd.extend(["--start", req.start])
    if req.end:
        cmd.extend(["--end", req.end])
    if req.catalog:
        cmd.extend(["--catalog", req.catalog])
    return cmd


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
