from __future__ import annotations

import datetime
import glob
import json
import os
import subprocess
import tempfile
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC
from decimal import Decimal
from pathlib import Path
from typing import Any

import dotenv
import yaml
from fastapi import (
    BackgroundTasks,
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from nautilus_lab.api.catalog_service import (
    describe_catalog,
    describe_catalog_cached,
    invalidate_catalog_cache,
    list_catalogs,
    load_catalog_bars,
    resolve_catalog_path,
)
from nautilus_lab.api.command_center import build_command_center, scan_triangular_demo
from nautilus_lab.api.data_health import (
    describe_data_health_cached,
    invalidate_data_health_cache,
)
from nautilus_lab.api.experiment_history import list_history, load_history_entry
from nautilus_lab.api.journal_service import list_journal_entries, update_journal_decision
from nautilus_lab.api.live_paper_boot import (
    boot_sessions,
    live_config_from_settings,
    registry_from_settings,
)
from nautilus_lab.api.live_sessions import SessionRegistry
from nautilus_lab.api.ml_runner import list_models
from nautilus_lab.api.paper_streamer import (
    LIVE_PAPER_ROBOTS,
    LivePaperSessionManager,
    binance_history_loader,
)
from nautilus_lab.api.research_runner import (
    default_tearsheet_path,
    load_job_result,
    summary_from_result,
)
from nautilus_lab.api.security import TOKEN_HEADER, ApiSecurity
from nautilus_lab.api.settings_schema import (
    mask_secret,
    settings_schema_payload,
    validate_settings_update,
)
from nautilus_lab.application.run_alpha_proposal import ProposeJobConfig, execute_propose
from nautilus_lab.application.run_paper import PAPER_SUPPORTED_ROBOTS
from nautilus_lab.domain.errors import InvalidHypothesisError
from nautilus_lab.domain.regime import (
    BACKTEST_WIRED_ROBOTS,
    HAWKES_ROBOTS,
    TICK_VPIN_ROBOTS,
    RobotName,
    tick_filters_supported,
)
from nautilus_lab.domain.stress_slices import STRESS_SLICES
from nautilus_lab.infrastructure.agg_trades_catalog import ParquetAggTradesCatalog
from nautilus_lab.infrastructure.llm_client import LlmRequestError
from nautilus_lab.infrastructure.nautilus.instrument import binance_symbol_for_instrument
from nautilus_lab.interfaces.composition import settings

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Resume every unfinished live paper session, then bring up the declared portfolio.
    # Shutdown deliberately does NOT stop them: sessions ended by SIGTERM (deploy, reboot)
    # must resume, and only a session a person stopped is final in its journal.
    for line in await boot_sessions(LIVE_SESSIONS, settings(), root=Path(ROOT_DIR)):
        print(f"live paper boot: {line}", flush=True)
    yield


app = FastAPI(title="Nautilus Lab API", lifespan=_lifespan)
REPORTS_DIR = os.path.join(ROOT_DIR, "reports")
HYPOTHESES_DIR = os.path.join(ROOT_DIR, "research", "hypotheses")
SPECS_DIR = os.path.join(ROOT_DIR, "specs", "strategies")
VENV_PYTHON = os.path.join(ROOT_DIR, ".venv", "bin", "python")

os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(HYPOTHESES_DIR, exist_ok=True)
app.mount("/static_reports", StaticFiles(directory=REPORTS_DIR), name="static_reports")
app.mount("/static_hypotheses", StaticFiles(directory=HYPOTHESES_DIR), name="static_hypotheses")

#: Read once at import: changing API_TOKEN / API_ALLOWED_ORIGINS needs a restart, which is
#: the point — a request must not be able to relax the gate it is being checked by.
SECURITY = ApiSecurity.from_values(
    origins=settings().api_allowed_origins,
    token=settings().api_token,
    role=settings().lab_role,
)

# Live paper sessions (api/live_sessions.py): one journal per session when persistence
# is configured (LIVE_PAPER_JOURNAL / LIVE_PAPER_SESSIONS_DIR), shared Binance feeds.
LIVE_SESSIONS: SessionRegistry = registry_from_settings(
    settings(), root=Path(ROOT_DIR), history_loader=binance_history_loader
)


@app.middleware("http")
async def _security_gate(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    reason = SECURITY.refusal(
        method=request.method,
        path=request.url.path,
        origin=request.headers.get("origin"),
        presented_token=request.headers.get(TOKEN_HEADER),
    )
    if reason is not None:
        return JSONResponse(status_code=403, content={"detail": reason})
    return await call_next(request)


# Registered after the gate so it wraps it: a refusal to an allowed origin still carries
# CORS headers and the dashboard can show the reason instead of a bare network error.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(SECURITY.allowed_origins),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

CURRENT_RESEARCH_PROCESS: subprocess.Popen[str] | None = None
CURRENT_INGEST_PROCESS: subprocess.Popen[str] | None = None
CURRENT_ML_PROCESS: subprocess.Popen[str] | None = None
CURRENT_PAPER_PROCESS: subprocess.Popen[str] | None = None

#: When each job was launched, so the dashboard can show elapsed time instead of a
#: bare "running". Only read while the matching process handle is alive.
JOB_STARTED: dict[str, datetime.datetime] = {}

#: Jobs an endpoint has accepted whose process the background task has not finished
#: with yet. The "already running?" check used to look only at the process handle,
#: which the background task sets AFTER the response is sent: two quick clicks both
#: passed the check, spawned two processes and truncated each other's log and result.
#: A poll right after launch also saw "not running" and stopped. Reserving the slot
#: under a lock, inside the request, closes both gaps.
_JOB_LOCK = threading.Lock()
JOBS_STARTING: set[str] = set()


def _job_process(name: str) -> subprocess.Popen[str] | None:
    return {
        "research": CURRENT_RESEARCH_PROCESS,
        "ingest": CURRENT_INGEST_PROCESS,
        "ml_train": CURRENT_ML_PROCESS,
        "paper": CURRENT_PAPER_PROCESS,
    }[name]


def _job_active(name: str) -> bool:
    """Accepted and not finished: reserved, or its process is still alive."""
    process = _job_process(name)
    return name in JOBS_STARTING or (process is not None and process.poll() is None)


def _reserve_job(name: str) -> bool:
    """Claim the job slot atomically. False = another run of this job is active."""
    with _JOB_LOCK:
        if _job_active(name):
            return False
        JOBS_STARTING.add(name)
        return True


def _release_job(name: str) -> None:
    with _JOB_LOCK:
        JOBS_STARTING.discard(name)


SECRET_SETTING_SUFFIXES = ("_TOKEN", "_SECRET", "_KEY", "_URL")


class ResearchRunRequest(BaseModel):
    robot: str = "regime"
    source: str = "catalog"
    bars: int = 3000
    folds: int = 2
    is_fraction: float = 0.7
    embargo_bars: int | None = None
    use_optuna: bool = False
    optuna_trials: int = 20
    pbo: bool = False
    pbo_blocks: int = 8
    bar_vpin: bool = False
    tick_vpin: bool = False
    hawkes: bool = False
    stress_slice: str | None = None
    generate_tearsheet: bool = True
    journal: bool = False
    notify: bool = False
    full_sample: bool = False
    catalog_path: str | None = None
    instrument_id: str | None = None
    bar_interval: str | None = None
    is_start: str | None = None
    is_end: str | None = None
    oos_start: str | None = None
    oos_end: str | None = None
    param_overrides: dict[str, str] = {}


class IngestRunRequest(BaseModel):
    symbols: str = "ETHUSDT,BTCUSDT"
    start: str | None = None
    end: str | None = None
    catalog: str | None = None
    incremental: bool = False
    #: Series to ingest. `klines` is the default (bars for every robot); `trades` pulls
    #: aggregated trades for the tick-level filters; `funding` pulls settlements.
    series: str = "klines"


class SettingsUpdate(BaseModel):
    settings: dict[str, str]


class MLTrainRequest(BaseModel):
    model_type: str = "formulaic"
    catalog_path: str | None = None
    instrument_id: str | None = None
    bar_interval: str | None = None
    output_path: str | None = None
    folds: int = 5
    embargo: int = 10
    horizon: int = 5
    profit_multiple: str = "2"
    stop_multiple: str = "1"
    vol_window: int = 20
    start: str | None = None
    end: str | None = None
    threshold: str = "0.55"


class PaperRunRequest(BaseModel):
    robot: str = "regime"
    bars: int = 2000
    source: str = "catalog"


class PaperLiveStartRequest(BaseModel):
    symbol: str = "BTCUSDT"
    interval: str = "1m"
    robot: str = "regime"
    starting_equity: str = "10000"
    risk_per_trade: str = "0.01"
    stop_pct: str = "0.015"
    take_profit_multiple: str = "2.0"
    mode: str = "paper"
    auto_trade: bool = True
    name: str = ""
    notes: str = ""


class PaperLiveStopsUpdateRequest(BaseModel):
    stop_loss: str | None = None
    take_profit: str | None = None


class JournalPatchRequest(BaseModel):
    decision: str


class ProposeRequest(BaseModel):
    count: int = 5
    dry_run: bool = True
    prompt: str = "01-generate-alphas.md"
    as_of: str | None = None
    model: str | None = None
    base_url: str | None = None
    output_dir: str | None = None
    slug: str | None = None
    journal: bool = False


def _python_executable() -> str:
    return VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python"


def _mask_settings(config: dict[str, str | None]) -> dict[str, str]:
    masked: dict[str, str] = {}
    for key, value in config.items():
        if value is None:
            masked[key] = ""
            continue
        upper = key.upper()
        if (
            any(upper.endswith(suffix) for suffix in SECRET_SETTING_SUFFIXES)
            and "PATH" not in upper
        ):
            masked[key] = mask_secret(str(value))
        else:
            masked[key] = str(value)
    return masked


@app.get("/")
def read_root() -> dict[str, str]:
    return {"status": "ok", "message": "Nautilus Lab API is running"}


def _default_catalog_dir() -> str:
    return str(resolve_catalog_path(None))


JOB_LABELS: dict[str, str] = {
    "research": "Walk-forward / backtest",
    "ingest": "Binance klines ingest",
    "ml_train": "ML training",
    "paper": "Paper order log",
}


def _job_payload(name: str, process: subprocess.Popen[str] | None) -> dict[str, Any]:
    """One job's live state: running, when it started, and how long it has run."""
    running = name in JOBS_STARTING or (process is not None and process.poll() is None)
    started = JOB_STARTED.get(name)
    elapsed = None
    if running and started is not None:
        elapsed = round((datetime.datetime.now(UTC) - started).total_seconds(), 1)
    return {
        "running": running,
        "label": JOB_LABELS.get(name, name),
        "started_at": started.isoformat() if running and started else None,
        "elapsed_seconds": elapsed,
    }


def current_jobs() -> dict[str, dict[str, Any]]:
    """Live state of every job the dashboard can launch, from the process handles."""
    return {
        "research": _job_payload("research", CURRENT_RESEARCH_PROCESS),
        "ingest": _job_payload("ingest", CURRENT_INGEST_PROCESS),
        "ml_train": _job_payload("ml_train", CURRENT_ML_PROCESS),
        "paper": _job_payload("paper", CURRENT_PAPER_PROCESS),
    }


@app.get("/api/status")
def get_status(catalog_path: str | None = None) -> dict[str, Any]:
    """Dashboard heartbeat. `catalog_path` selects which catalog is described."""
    resolved_catalog = str(resolve_catalog_path(catalog_path))
    jobs = current_jobs()
    summary = describe_catalog_cached(resolved_catalog)
    cfg = settings()
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
        "lab_role": SECURITY.role,
        "live_paper_robots": sorted(LIVE_PAPER_ROBOTS),
        "live_paper_persisted": LIVE_SESSIONS.persisted,
    }


@app.get("/api/catalogs")
def get_catalogs() -> dict[str, Any]:
    return list_catalogs()


@app.get("/api/catalog")
def get_catalog(catalog_path: str | None = None) -> dict[str, Any]:
    return describe_catalog(catalog_path)


@app.get("/api/catalog/bars")
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
            catalog_path=catalog_path or _default_catalog_dir(),
            bar_interval=bar_interval,
            start=start,
            end=end,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/data")
def get_data_health(catalog_path: str | None = None) -> dict[str, Any]:
    """Which of the four series trees this catalog actually holds, and how far each reaches.

    The engine reads a missing tick/funding series as an empty one, so "the run finished"
    is not evidence that the filter it was configured with had any data behind it.
    """
    return describe_data_health_cached(catalog_path)


def strategy_spec_payload(data: dict[str, Any]) -> dict[str, Any]:
    """One spec file as the dashboard needs it.

    `wired_in_backtest`, `minimum_bars`, `grid_source`, `domain_module` and
    `strategy_class` live under `implementation:` in the spec schema — the same paths
    `specs/_validator.py` checks. Reading them from the top level made every robot report
    `wired_in_backtest: false` and `minimum_bars: 100`, so the UI labelled working robots
    as fail-closed and the research preflight would have blocked every run. The top-level
    fallback keeps an older-format spec readable instead of silently blank.
    """
    implementation = data.get("implementation")
    impl: dict[str, Any] = implementation if isinstance(implementation, dict) else {}

    def field(name: str, default: object = None) -> object:
        value = impl.get(name)
        if value is None:
            value = data.get(name)
        return default if value is None else value

    params = data.get("params")
    return {
        "name": data.get("name"),
        "title": data.get("title", ""),
        "domain_module": field("domain_module"),
        "strategy_class": field("strategy_class"),
        "backtest_adapter": impl.get("backtest_adapter"),
        "wired_in_backtest": bool(field("wired_in_backtest", False)),
        "minimum_bars": field("minimum_bars", 100),
        "grid_source": field("grid_source"),
        "signal_kind": impl.get("signal_kind"),
        "status": data.get("status", "candidate"),
        # Specs carry no free-text `summary`; `title` is the human one-liner.
        "summary": data.get("summary") or data.get("title", ""),
        "params": params if isinstance(params, list) else [],
        "hypothesis": data.get("hypothesis", ""),
        "invariants": data.get("invariants", []),
    }


@app.get("/api/strategies")
def get_strategies() -> dict[str, Any]:
    results = []
    failed: list[str] = []
    if not os.path.exists(SPECS_DIR):
        return {"strategies": [], "failed_specs": []}

    for spec_file in sorted(glob.glob(os.path.join(SPECS_DIR, "*.yaml"))):
        try:
            with open(spec_file) as f:
                data = yaml.safe_load(f)
        except (OSError, yaml.YAMLError):
            # A spec that cannot be parsed is reported, not skipped: a silently missing
            # robot looks identical to one that was never written.
            failed.append(os.path.basename(spec_file))
            continue
        if not isinstance(data, dict) or not data.get("name"):
            failed.append(os.path.basename(spec_file))
            continue
        results.append(strategy_spec_payload(data))

    return {"strategies": results, "failed_specs": failed}


@app.get("/api/reports")
def get_reports() -> dict[str, Any]:
    if not os.path.exists(REPORTS_DIR):
        return {"reports": []}

    files = glob.glob(os.path.join(REPORTS_DIR, "*.html"))
    reports = []
    for f in sorted(files, key=os.path.getmtime, reverse=True):
        mtime = os.path.getmtime(f)
        size = os.path.getsize(f)
        reports.append(
            {
                "filename": os.path.basename(f),
                "path": f,
                "url": f"/static_reports/{os.path.basename(f)}",
                "modified": datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "size_kb": round(size / 1024, 1),
            }
        )
    return {"reports": reports}


def run_research_subprocess(config: dict[str, Any]) -> None:
    try:
        _run_research(config)
    finally:
        _release_job("research")


def _run_research(config: dict[str, Any]) -> None:
    global CURRENT_RESEARCH_PROCESS
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False,
        encoding="utf-8",
    ) as handle:
        json.dump(config, handle)
        config_path = handle.name

    cmd = [
        _python_executable(),
        "-m",
        "nautilus_lab.api.run_research_job",
        "--config-json",
        config_path,
        "--reports-dir",
        REPORTS_DIR,
    ]
    try:
        CURRENT_RESEARCH_PROCESS = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert CURRENT_RESEARCH_PROCESS.stdout is not None
        extra_log = CURRENT_RESEARCH_PROCESS.stdout.read()
        if extra_log.strip():
            log_path = os.path.join(REPORTS_DIR, "last_run.log")
            if os.path.exists(log_path):
                with open(log_path, "a", encoding="utf-8") as log_file:
                    log_file.write(extra_log)
        CURRENT_RESEARCH_PROCESS.wait()
    finally:
        os.unlink(config_path)


@app.post("/api/research")
def run_research(background_tasks: BackgroundTasks, req: ResearchRunRequest) -> dict[str, Any]:
    global CURRENT_RESEARCH_PROCESS
    if _job_active("research"):
        return {"status": "error", "message": "Another research process is already running."}

    # Refuse impossible combinations here, before the job is spawned and before the previous
    # run's artifacts are cleared: a request that cannot mean anything should not cost a
    # process launch and should not blank the dashboard's last result.
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
        symbol = binance_symbol_for_instrument(req.instrument_id or settings().instrument_id)
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

    if not _reserve_job("research"):
        return {"status": "error", "message": "Another research process is already running."}
    log_path = os.path.join(REPORTS_DIR, "last_run.log")
    json_path = os.path.join(REPORTS_DIR, "last_run.json")
    open(log_path, "w", encoding="utf-8").close()
    if os.path.exists(json_path):
        os.unlink(json_path)

    tearsheet_path = None
    if req.generate_tearsheet and not req.pbo:
        tearsheet_path = default_tearsheet_path(Path(REPORTS_DIR), req.robot)

    config = {
        "robot": req.robot,
        "source": req.source,
        "bars": req.bars,
        "folds": req.folds,
        "is_fraction": req.is_fraction,
        "embargo_bars": req.embargo_bars,
        "use_optuna": req.use_optuna,
        "optuna_trials": req.optuna_trials,
        "pbo": req.pbo,
        "pbo_blocks": req.pbo_blocks,
        "bar_vpin": req.bar_vpin,
        "tick_vpin": req.tick_vpin,
        "hawkes": req.hawkes,
        "stress_slice": req.stress_slice,
        "generate_tearsheet": req.generate_tearsheet,
        "journal": req.journal,
        "notify": req.notify,
        "full_sample": req.full_sample,
        "catalog_path": req.catalog_path,
        "instrument_id": req.instrument_id,
        "bar_interval": req.bar_interval,
        "is_start": req.is_start,
        "is_end": req.is_end,
        "oos_start": req.oos_start,
        "oos_end": req.oos_end,
        "param_overrides": req.param_overrides,
        "tearsheet_path": tearsheet_path,
    }

    cmd_display = (
        f"{_python_executable()} -m nautilus_lab.api.run_research_job "
        f"robot={req.robot} source={req.source}"
    )
    background_tasks.add_task(run_research_subprocess, config)
    JOB_STARTED["research"] = datetime.datetime.now(UTC)
    return {
        "status": "started",
        "message": f"Research run launched for {req.robot} ({req.source} mode)",
        "command": cmd_display,
    }


@app.post("/api/research/cancel")
def cancel_research() -> dict[str, Any]:
    global CURRENT_RESEARCH_PROCESS
    res_proc = CURRENT_RESEARCH_PROCESS
    if res_proc is None or res_proc.poll() is not None:
        return {"status": "idle", "message": "No research process is running."}
    res_proc.terminate()
    try:
        res_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        res_proc.kill()
    return {"status": "cancelled", "message": "Research process terminated."}


@app.get("/api/research/log")
def get_research_log() -> dict[str, Any]:
    global CURRENT_RESEARCH_PROCESS
    is_running = _job_active("research")
    log_path = os.path.join(REPORTS_DIR, "last_run.log")
    content = ""
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as f:
            content = f.read()

    structured = load_job_result(Path(REPORTS_DIR))
    summary = summary_from_result(structured)
    if structured is None and content:
        summary = _legacy_summary_from_log(content)
    if is_running:
        summary = {**summary, "is_finished": False}

    return {
        "is_running": is_running,
        "log": content,
        "summary": summary,
        "result": structured,
    }


@app.get("/api/research/history")
def get_research_history(limit: int = 20) -> dict[str, Any]:
    rows = list_history(Path(REPORTS_DIR), limit=limit)
    return {"history": rows}


@app.get("/api/research/history/{history_id}")
def get_research_history_entry(history_id: str) -> dict[str, Any]:
    entry = load_history_entry(Path(REPORTS_DIR), history_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"History entry not found: {history_id}")
    return {"entry": entry}


def _legacy_summary_from_log(log_text: str) -> dict[str, Any]:
    import re

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


def _catalog_arg(cmd: list[str]) -> str | None:
    """The `--catalog` value in a built CLI command, if the flag carries one."""
    if "--catalog" not in cmd:
        return None
    index = cmd.index("--catalog") + 1
    return cmd[index] if index < len(cmd) else None


def run_ingest_subprocess(cmd: list[str], log_path: str) -> None:
    try:
        _run_ingest(cmd, log_path)
    finally:
        _release_job("ingest")


def _run_ingest(cmd: list[str], log_path: str) -> None:
    global CURRENT_INGEST_PROCESS
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"Command: {' '.join(cmd)}\n")
        f.write(f"Started at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.flush()
        try:
            CURRENT_INGEST_PROCESS = subprocess.Popen(
                cmd,
                stdout=f,
                stderr=subprocess.STDOUT,
                text=True,
            )
            CURRENT_INGEST_PROCESS.wait()
            f.write(f"\nProcess finished with code {CURRENT_INGEST_PROCESS.returncode}\n")
            # The status endpoint caches catalog descriptions; an ingest is exactly the
            # event that makes the cached counts wrong. The coverage panel caches the same
            # way, and a tick ingest changes nothing else in it.
            invalidate_catalog_cache(_catalog_arg(cmd))
            invalidate_data_health_cache(_catalog_arg(cmd))
        except Exception as e:
            f.write(f"\nException occurred: {e!s}\n")


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


@app.post("/api/catalog/ingest")
def run_ingest(background_tasks: BackgroundTasks, req: IngestRunRequest) -> dict[str, Any]:
    global CURRENT_INGEST_PROCESS
    if _job_active("ingest"):
        return {"status": "error", "message": "An ingest process is already running."}

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

    log_path = os.path.join(REPORTS_DIR, "ingest.log")
    open(log_path, "w", encoding="utf-8").close()

    cmd = [_python_executable(), "-m", "nautilus_lab.interfaces.cli", "ingest"]
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

    if not _reserve_job("ingest"):
        return {"status": "error", "message": "An ingest process is already running."}
    background_tasks.add_task(run_ingest_subprocess, cmd, log_path)
    JOB_STARTED["ingest"] = datetime.datetime.now(UTC)
    return {
        "status": "started",
        "message": f"Ingest started for symbols: {req.symbols}",
        "command": " ".join(cmd),
    }


@app.post("/api/catalog/ingest/cancel")
def cancel_ingest() -> dict[str, Any]:
    global CURRENT_INGEST_PROCESS
    ing_proc = CURRENT_INGEST_PROCESS
    if ing_proc is None or ing_proc.poll() is not None:
        return {"status": "idle", "message": "No ingest process is running."}
    ing_proc.terminate()
    try:
        ing_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        ing_proc.kill()
    return {"status": "cancelled", "message": "Ingest process terminated."}


@app.get("/api/catalog/ingest/log")
def get_ingest_log() -> dict[str, Any]:
    global CURRENT_INGEST_PROCESS
    is_running = _job_active("ingest")
    log_path = os.path.join(REPORTS_DIR, "ingest.log")
    content = ""
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as f:
            content = f.read()
    return {
        "is_running": is_running,
        "log": content,
    }


@app.get("/api/settings/schema")
def get_settings_schema() -> dict[str, Any]:
    return settings_schema_payload()


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    env_path = os.path.join(ROOT_DIR, ".env")
    if not os.path.exists(env_path):
        env_path = os.path.join(ROOT_DIR, ".env.example")

    config = dotenv.dotenv_values(env_path)
    return {"settings": _mask_settings(dict(config))}


@app.put("/api/settings")
def update_settings(update: SettingsUpdate) -> dict[str, str]:
    try:
        validated = validate_settings_update(update.settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    env_path = os.path.join(ROOT_DIR, ".env")
    if not os.path.exists(env_path):
        open(env_path, "a", encoding="utf-8").close()

    for key, value in validated.items():
        if (
            any(key.upper().endswith(suffix) for suffix in SECRET_SETTING_SUFFIXES)
            and "****" in value
        ):
            continue
        dotenv.set_key(env_path, key, str(value))

    return {"status": "success"}


def _load_json_report(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else None


def _run_subprocess_job(
    *,
    module: str,
    config: dict[str, Any],
    log_name: str,
    json_name: str,
    process_attr: str,
) -> None:
    global \
        CURRENT_RESEARCH_PROCESS, \
        CURRENT_INGEST_PROCESS, \
        CURRENT_ML_PROCESS, \
        CURRENT_PAPER_PROCESS
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False,
        encoding="utf-8",
    ) as handle:
        json.dump(config, handle)
        config_path = handle.name

    cmd = [
        _python_executable(),
        "-m",
        module,
        "--config-json",
        config_path,
        "--reports-dir",
        REPORTS_DIR,
    ]
    log_path = os.path.join(REPORTS_DIR, log_name)
    json_path = os.path.join(REPORTS_DIR, json_name)
    open(log_path, "w", encoding="utf-8").close()
    if os.path.exists(json_path):
        os.unlink(json_path)

    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if process_attr == "research":
            CURRENT_RESEARCH_PROCESS = process
        elif process_attr == "ml":
            CURRENT_ML_PROCESS = process
        elif process_attr == "paper":
            CURRENT_PAPER_PROCESS = process
        assert process.stdout is not None
        extra_log = process.stdout.read()
        if extra_log.strip():
            with open(log_path, "a", encoding="utf-8") as log_file:
                log_file.write(extra_log)
        process.wait()
    finally:
        os.unlink(config_path)
        if process_attr == "research":
            CURRENT_RESEARCH_PROCESS = None
        elif process_attr == "ml":
            CURRENT_ML_PROCESS = None
        elif process_attr == "paper":
            CURRENT_PAPER_PROCESS = None


def run_ml_subprocess(config: dict[str, Any]) -> None:
    try:
        _run_subprocess_job(
            module="nautilus_lab.api.run_ml_job",
            config=config,
            log_name="ml_train.log",
            json_name="ml_train.json",
            process_attr="ml",
        )
    finally:
        _release_job("ml_train")


def run_paper_subprocess(config: dict[str, Any]) -> None:
    try:
        _run_subprocess_job(
            module="nautilus_lab.api.run_paper_job",
            config=config,
            log_name="paper.log",
            json_name="paper.json",
            process_attr="paper",
        )
    finally:
        _release_job("paper")


@app.get("/api/command-center")
def get_command_center() -> dict[str, Any]:
    return build_command_center(
        reports_dir=Path(REPORTS_DIR),
        catalog_dir=_default_catalog_dir(),
        research_running=_job_active("research"),
        ingest_running=_job_active("ingest"),
        ml_running=_job_active("ml_train"),
        paper_running=_job_active("paper"),
    )


@app.get("/api/journal")
def get_journal() -> dict[str, Any]:
    return {"entries": list_journal_entries()}


@app.patch("/api/journal/{index}")
def patch_journal(index: int, req: JournalPatchRequest) -> dict[str, Any]:
    try:
        row = update_journal_decision(index, req.decision)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"entry": row}


@app.get("/api/ml/models")
def get_ml_models() -> dict[str, Any]:
    return {"models": list_models()}


@app.post("/api/ml/train")
def run_ml_train(background_tasks: BackgroundTasks, req: MLTrainRequest) -> dict[str, Any]:
    global CURRENT_ML_PROCESS
    if _job_active("ml_train"):
        return {"status": "error", "message": "Another ML training job is already running."}
    config = req.model_dump()
    if not _reserve_job("ml_train"):
        return {"status": "error", "message": "Another ML training job is already running."}
    background_tasks.add_task(run_ml_subprocess, config)
    JOB_STARTED["ml_train"] = datetime.datetime.now(UTC)
    return {
        "status": "started",
        "message": f"ML training started for {req.model_type}",
    }


@app.post("/api/ml/train/cancel")
def cancel_ml_train() -> dict[str, Any]:
    global CURRENT_ML_PROCESS
    proc = CURRENT_ML_PROCESS
    if proc is None or proc.poll() is not None:
        return {"status": "idle", "message": "No ML training job is running."}
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    return {"status": "cancelled", "message": "ML training job terminated."}


@app.get("/api/ml/train/log")
def get_ml_train_log() -> dict[str, Any]:
    global CURRENT_ML_PROCESS
    is_running = _job_active("ml_train")
    log_path = os.path.join(REPORTS_DIR, "ml_train.log")
    content = ""
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as handle:
            content = handle.read()
    result = _load_json_report(Path(REPORTS_DIR) / "ml_train.json")
    summary: dict[str, Any] = {"is_finished": not is_running, "is_error": False}
    if result:
        summary = {
            "is_finished": bool(result.get("is_finished", not is_running)),
            "is_error": bool(result.get("is_error")),
            "model_type": result.get("model_type"),
            "model_path": result.get("model_path"),
            "accuracy": result.get("accuracy"),
            "rows": result.get("rows"),
            "take_profit_rate": result.get("take_profit_rate"),
            "oof_precision": result.get("oof_precision"),
            "oof_recall": result.get("oof_recall"),
            "beats_always_take": result.get("beats_always_take"),
            "majority_rate": result.get("majority_rate"),
            "beats_majority": result.get("beats_majority"),
            "train_window": result.get("train_window"),
            "created_at": result.get("created_at"),
            "error_message": result.get("error_message"),
        }
    elif content:
        summary["is_finished"] = "Process finished with code" in content
        summary["is_error"] = "Process finished with code 1" in content or "Traceback" in content
    if is_running:
        summary["is_finished"] = False
    return {"is_running": is_running, "log": content, "summary": summary, "result": result}


@app.post("/api/paper/run")
def run_paper(background_tasks: BackgroundTasks, req: PaperRunRequest) -> dict[str, Any]:
    global CURRENT_PAPER_PROCESS
    if _job_active("paper"):
        return {"status": "error", "message": "Another paper simulation is already running."}
    try:
        robot = RobotName(req.robot)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"unknown robot: {req.robot}") from exc
    if robot not in PAPER_SUPPORTED_ROBOTS:
        supported = ", ".join(sorted(item.value for item in PAPER_SUPPORTED_ROBOTS))
        raise HTTPException(
            status_code=400,
            detail=(
                f"paper mode cannot build robot {robot.value!r}; supported: {supported}. "
                "Other robots need a paper adapter that does not exist yet."
            ),
        )
    config = req.model_dump()
    if not _reserve_job("paper"):
        return {"status": "error", "message": "Another paper simulation is already running."}
    background_tasks.add_task(run_paper_subprocess, config)
    JOB_STARTED["paper"] = datetime.datetime.now(UTC)
    return {
        "status": "started",
        "message": f"Paper simulation started for {req.robot} ({req.source})",
        "disclaimer": (
            "Paper session: the simulated venue fills against closed bars. "
            "No exchange is contacted and no order is submitted."
        ),
    }


@app.post("/api/paper/cancel")
def cancel_paper() -> dict[str, Any]:
    global CURRENT_PAPER_PROCESS
    proc = CURRENT_PAPER_PROCESS
    if proc is None or proc.poll() is not None:
        return {"status": "idle", "message": "No paper simulation is running."}
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    return {"status": "cancelled", "message": "Paper simulation terminated."}


@app.get("/api/paper/log")
def get_paper_log() -> dict[str, Any]:
    global CURRENT_PAPER_PROCESS
    is_running = _job_active("paper")
    log_path = os.path.join(REPORTS_DIR, "paper.log")
    content = ""
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as handle:
            content = handle.read()
    result = _load_json_report(Path(REPORTS_DIR) / "paper.json")
    summary: dict[str, Any] = {"is_finished": not is_running, "is_error": False, "order_count": 0}
    if result:
        summary = {
            "is_finished": bool(result.get("is_finished", not is_running)),
            "is_error": bool(result.get("is_error")),
            "robot": result.get("robot"),
            "order_count": result.get("order_count", 0),
            "error_message": result.get("error_message"),
            "disclaimer": result.get("disclaimer"),
        }
    elif content:
        summary["is_finished"] = "Process finished with code" in content
        summary["is_error"] = "Process finished with code 1" in content or "Traceback" in content
    if is_running:
        summary["is_finished"] = False
    return {"is_running": is_running, "log": content, "summary": summary, "result": result}


def _idle_state() -> dict[str, Any]:
    """What the terminal shows when no session is selected or running."""
    state = LivePaperSessionManager().to_state_dict()
    state["persisted"] = LIVE_SESSIONS.persisted
    return state


def _session_or_404(key: str) -> LivePaperSessionManager:
    manager = LIVE_SESSIONS.find(key)
    if manager is None:
        raise HTTPException(status_code=404, detail=f"no live paper session {key!r}")
    return manager


def _primary_or_400() -> LivePaperSessionManager:
    manager = LIVE_SESSIONS.primary()
    if manager is None:
        raise HTTPException(status_code=400, detail="no live paper session")
    return manager


async def _create_session(req: PaperLiveStartRequest) -> LivePaperSessionManager:
    # Robot parameters, fees and breakers come from the same Settings the research runs
    # use, so the terminal rehearses the tested configuration rather than its own defaults.
    config = live_config_from_settings(
        settings(),
        symbol=req.symbol,
        interval=req.interval,
        robot=req.robot,
        starting_equity=Decimal(req.starting_equity),
        risk_per_trade=Decimal(req.risk_per_trade),
        stop_pct=Decimal(req.stop_pct),
        take_profit_multiple=Decimal(req.take_profit_multiple),
        mode=req.mode,
        auto_trade=req.auto_trade,
        name=req.name,
        notes=req.notes,
        created_from="ui",
    )
    try:
        return await LIVE_SESSIONS.create(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _close_position(manager: LivePaperSessionManager) -> dict[str, Any]:
    msg = manager.close_position_manual()
    await manager.broadcast_state()
    return {"status": "ok", "message": msg}


async def _update_stops(
    manager: LivePaperSessionManager, req: PaperLiveStopsUpdateRequest
) -> dict[str, Any]:
    sl = Decimal(req.stop_loss) if req.stop_loss else None
    tp = Decimal(req.take_profit) if req.take_profit else None
    msg = manager.update_stops(sl, tp)
    await manager.broadcast_state()
    return {"status": "ok", "message": msg}


async def _set_paused(key: str, paused: bool) -> LivePaperSessionManager:
    try:
        return await LIVE_SESSIONS.set_paused(key, paused)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"no live paper session {key!r}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---- several sessions -------------------------------------------------------------
@app.get("/api/paper/sessions")
def list_paper_sessions() -> dict[str, Any]:
    return {"sessions": LIVE_SESSIONS.summaries(), "portfolio": LIVE_SESSIONS.portfolio()}


@app.get("/api/paper/portfolio")
def get_paper_portfolio() -> dict[str, Any]:
    return LIVE_SESSIONS.portfolio()


@app.post("/api/paper/sessions")
async def create_paper_session(req: PaperLiveStartRequest) -> dict[str, Any]:
    manager = await _create_session(req)
    return {
        "status": "started",
        "session_id": manager.session_id,
        "name": manager.config.name,
        "message": f"Started {manager.config.name} ({manager.config.symbol})",
    }


@app.get("/api/paper/sessions/{key}")
def get_paper_session(key: str) -> dict[str, Any]:
    return _session_or_404(key).to_state_dict()


@app.post("/api/paper/sessions/{key}/stop")
async def stop_paper_session(key: str) -> dict[str, Any]:
    manager = _session_or_404(key)
    await manager.stop()
    return {"status": "stopped", "message": f"Stopped {manager.config.name}"}


@app.post("/api/paper/sessions/{key}/pause")
async def pause_paper_session(key: str) -> dict[str, Any]:
    manager = await _set_paused(key, True)
    return {"status": "paused", "message": f"Paused entries of {manager.config.name}"}


@app.post("/api/paper/sessions/{key}/resume")
async def resume_paper_session(key: str) -> dict[str, Any]:
    manager = await _set_paused(key, False)
    return {"status": "active", "message": f"Resumed entries of {manager.config.name}"}


@app.post("/api/paper/sessions/{key}/close-position")
async def close_paper_session_position(key: str) -> dict[str, Any]:
    return await _close_position(_session_or_404(key))


@app.post("/api/paper/sessions/{key}/update-stops")
async def update_paper_session_stops(key: str, req: PaperLiveStopsUpdateRequest) -> dict[str, Any]:
    return await _update_stops(_session_or_404(key), req)


# ---- one-session endpoints, kept for older dashboards: act on the primary session ---
@app.get("/api/paper/live/state")
def get_paper_live_state() -> dict[str, Any]:
    manager = LIVE_SESSIONS.primary()
    return _idle_state() if manager is None else manager.to_state_dict()


@app.post("/api/paper/live/start")
async def start_paper_live(req: PaperLiveStartRequest) -> dict[str, Any]:
    manager = await _create_session(req)
    return {
        "status": "started",
        "session_id": manager.session_id,
        "message": f"Started live paper session for {req.symbol}",
    }


@app.post("/api/paper/live/stop")
async def stop_paper_live() -> dict[str, Any]:
    await _primary_or_400().stop()
    return {"status": "stopped", "message": "Live paper session stopped"}


@app.post("/api/paper/live/close-position")
async def close_paper_live_position() -> dict[str, Any]:
    return await _close_position(_primary_or_400())


@app.post("/api/paper/live/update-stops")
async def update_paper_live_stops(req: PaperLiveStopsUpdateRequest) -> dict[str, Any]:
    return await _update_stops(_primary_or_400(), req)


@app.websocket("/api/paper/live-stream")
async def paper_live_stream_ws(websocket: WebSocket) -> None:
    """State + bars of one session: `?session=<id or name>`, else the primary session."""
    # HTTP middleware never sees a WebSocket handshake, and CORS does not apply to one,
    # so the same gate runs here. Browsers cannot set headers on a WebSocket: the token
    # travels as `?token=`.
    reason = SECURITY.refusal(
        method="GET",
        path=websocket.url.path,
        origin=websocket.headers.get("origin"),
        presented_token=websocket.query_params.get("token"),
    )
    if reason is not None:
        await websocket.close(code=1008, reason=reason)
        return
    await websocket.accept()
    key = websocket.query_params.get("session")
    manager = LIVE_SESSIONS.find(key) if key else LIVE_SESSIONS.primary()
    if manager is not None:
        manager.subscribers.add(websocket)
    try:
        state = _idle_state() if manager is None else manager.to_state_dict()
        await websocket.send_text(json.dumps({"type": "INIT_STATE", "data": state}))
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if manager is not None:
            manager.subscribers.discard(websocket)


@app.post("/api/scan/triangular")
def scan_triangular() -> dict[str, Any]:
    return scan_triangular_demo()


@app.post("/api/propose")
def run_propose(req: ProposeRequest) -> dict[str, Any]:
    as_of = None
    if req.as_of:
        try:
            as_of = datetime.date.fromisoformat(req.as_of)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid as_of date: {req.as_of}") from exc
    job = ProposeJobConfig(
        count=req.count,
        dry_run=req.dry_run,
        prompt=req.prompt,
        as_of=as_of,
        model=req.model,
        base_url=req.base_url,
        output_dir=req.output_dir,
        slug=req.slug,
        journal=req.journal,
    )
    try:
        return execute_propose(job)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidHypothesisError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LlmRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/hypotheses")
def get_hypotheses() -> dict[str, Any]:
    if not os.path.exists(HYPOTHESES_DIR):
        return {"hypotheses": []}

    files = glob.glob(os.path.join(HYPOTHESES_DIR, "*.json"))
    items: list[dict[str, Any]] = []
    for f in sorted(files, key=os.path.getmtime, reverse=True):
        mtime = os.path.getmtime(f)
        size = os.path.getsize(f)
        basename = os.path.basename(f)
        iso_mtime = datetime.datetime.fromtimestamp(mtime, tz=UTC).isoformat()
        item: dict[str, Any] = {
            "file": basename,
            "modified": iso_mtime,
            "size_kb": round(size / 1024, 1),
            "url": f"/static_hypotheses/{basename}",
        }
        try:
            with open(f, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                item["model"] = data.get("model", "unknown")
                item["as_of"] = data.get("as_of", "")
                item["count_parsed"] = data.get("count_parsed", 0)
                item["count_flagged"] = data.get("count_flagged", 0)
                review = data.get("review")
                if isinstance(review, dict):
                    item["review_status"] = review.get("status", "pending")
        except Exception:
            pass
        items.append(item)
    return {"hypotheses": items}


@app.get("/api/hypotheses/{filename}")
def get_hypothesis_detail(filename: str) -> dict[str, Any]:
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    target = os.path.join(HYPOTHESES_DIR, filename)
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="hypothesis file not found")
    try:
        with open(target, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise HTTPException(status_code=500, detail="invalid hypothesis file format")
        return data
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="corrupt hypothesis JSON") from exc
