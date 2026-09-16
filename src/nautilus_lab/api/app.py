from __future__ import annotations

import datetime
import glob
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import dotenv
import yaml
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from nautilus_lab.api.catalog_service import (
    describe_catalog,
    list_catalogs,
    load_catalog_bars,
    resolve_catalog_path,
)
from nautilus_lab.api.command_center import build_command_center, scan_triangular_demo
from nautilus_lab.api.experiment_history import list_history, load_history_entry
from nautilus_lab.api.journal_service import list_journal_entries, update_journal_decision
from nautilus_lab.api.ml_runner import list_models
from nautilus_lab.api.research_runner import (
    default_tearsheet_path,
    load_job_result,
    summary_from_result,
)
from nautilus_lab.api.settings_schema import (
    mask_secret,
    settings_schema_payload,
    validate_settings_update,
)
from nautilus_lab.application.run_alpha_proposal import ProposeJobConfig, execute_propose
from nautilus_lab.domain.errors import InvalidHypothesisError
from nautilus_lab.domain.regime import BACKTEST_WIRED_ROBOTS, RobotName
from nautilus_lab.infrastructure.llm_client import LlmRequestError

app = FastAPI(title="Nautilus Lab API")

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
REPORTS_DIR = os.path.join(ROOT_DIR, "reports")
SPECS_DIR = os.path.join(ROOT_DIR, "specs", "strategies")
VENV_PYTHON = os.path.join(ROOT_DIR, ".venv", "bin", "python")

os.makedirs(REPORTS_DIR, exist_ok=True)
app.mount("/static_reports", StaticFiles(directory=REPORTS_DIR), name="static_reports")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CURRENT_RESEARCH_PROCESS: subprocess.Popen[str] | None = None
CURRENT_INGEST_PROCESS: subprocess.Popen[str] | None = None
CURRENT_ML_PROCESS: subprocess.Popen[str] | None = None
CURRENT_PAPER_PROCESS: subprocess.Popen[str] | None = None

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


class PaperRunRequest(BaseModel):
    robot: str = "regime"
    bars: int = 500
    source: str = "synthetic"


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


@app.get("/api/status")
def get_status() -> dict[str, Any]:
    global CURRENT_RESEARCH_PROCESS, CURRENT_INGEST_PROCESS
    res_proc = CURRENT_RESEARCH_PROCESS
    ing_proc = CURRENT_INGEST_PROCESS
    research_running = res_proc is not None and res_proc.poll() is None
    ingest_running = ing_proc is not None and ing_proc.poll() is None
    catalog_dir = _default_catalog_dir()
    catalog_exists = os.path.exists(catalog_dir)
    catalog_instruments = 0
    if catalog_exists:
        try:
            summary = describe_catalog(catalog_dir)
            catalog_instruments = int(summary.get("total_instruments", 0))
        except Exception:
            catalog_instruments = 0

    return {
        "active_bots": 0,
        "research_running": research_running,
        "ingest_running": ingest_running,
        "strategies_available": [item.value for item in RobotName],
        "wired_robots": sorted(item.value for item in BACKTEST_WIRED_ROBOTS),
        "catalog_exists": catalog_exists,
        "catalog_instruments": catalog_instruments,
        "catalog_path": catalog_dir,
        "is_live": False,
        "live_safe_mode": "FAIL_CLOSED",
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


@app.get("/api/strategies")
def get_strategies() -> dict[str, Any]:
    results = []
    if not os.path.exists(SPECS_DIR):
        return {"strategies": []}

    for spec_file in sorted(glob.glob(os.path.join(SPECS_DIR, "*.yaml"))):
        try:
            with open(spec_file) as f:
                data = yaml.safe_load(f)
                results.append(
                    {
                        "name": data.get("name"),
                        "domain_module": data.get("domain_module"),
                        "strategy_class": data.get("strategy_class"),
                        "wired_in_backtest": bool(data.get("wired_in_backtest")),
                        "minimum_bars": data.get("minimum_bars", 100),
                        "grid_source": data.get("grid_source"),
                        "status": data.get("status", "candidate"),
                        "summary": data.get("summary", ""),
                        "params": data.get("params", []),
                        "hypothesis": data.get("hypothesis", ""),
                    }
                )
        except Exception:
            continue

    return {"strategies": results}


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
    res_proc = CURRENT_RESEARCH_PROCESS
    if res_proc is not None and res_proc.poll() is None:
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
    res_proc = CURRENT_RESEARCH_PROCESS
    is_running = res_proc is not None and res_proc.poll() is None
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


def run_ingest_subprocess(cmd: list[str], log_path: str) -> None:
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
        except Exception as e:
            f.write(f"\nException occurred: {e!s}\n")


@app.post("/api/catalog/ingest")
def run_ingest(background_tasks: BackgroundTasks, req: IngestRunRequest) -> dict[str, Any]:
    global CURRENT_INGEST_PROCESS
    ing_proc = CURRENT_INGEST_PROCESS
    if ing_proc is not None and ing_proc.poll() is None:
        return {"status": "error", "message": "An ingest process is already running."}

    log_path = os.path.join(REPORTS_DIR, "ingest.log")
    open(log_path, "w", encoding="utf-8").close()

    cmd = [_python_executable(), "-m", "nautilus_lab.interfaces.cli", "ingest"]
    if req.symbols:
        cmd.extend(["--symbols", req.symbols])
    if req.start:
        cmd.extend(["--start", req.start])
    if req.end:
        cmd.extend(["--end", req.end])
    if req.catalog:
        cmd.extend(["--catalog", req.catalog])
    if req.incremental:
        cmd.append("--incremental")

    background_tasks.add_task(run_ingest_subprocess, cmd, log_path)
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
    ing_proc = CURRENT_INGEST_PROCESS
    is_running = ing_proc is not None and ing_proc.poll() is None
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
    _run_subprocess_job(
        module="nautilus_lab.api.run_ml_job",
        config=config,
        log_name="ml_train.log",
        json_name="ml_train.json",
        process_attr="ml",
    )


def run_paper_subprocess(config: dict[str, Any]) -> None:
    _run_subprocess_job(
        module="nautilus_lab.api.run_paper_job",
        config=config,
        log_name="paper.log",
        json_name="paper.json",
        process_attr="paper",
    )


@app.get("/api/command-center")
def get_command_center() -> dict[str, Any]:
    global \
        CURRENT_RESEARCH_PROCESS, \
        CURRENT_INGEST_PROCESS, \
        CURRENT_ML_PROCESS, \
        CURRENT_PAPER_PROCESS
    return build_command_center(
        reports_dir=Path(REPORTS_DIR),
        catalog_dir=_default_catalog_dir(),
        research_running=(
            CURRENT_RESEARCH_PROCESS is not None and CURRENT_RESEARCH_PROCESS.poll() is None
        ),
        ingest_running=(
            CURRENT_INGEST_PROCESS is not None and CURRENT_INGEST_PROCESS.poll() is None
        ),
        ml_running=(CURRENT_ML_PROCESS is not None and CURRENT_ML_PROCESS.poll() is None),
        paper_running=(CURRENT_PAPER_PROCESS is not None and CURRENT_PAPER_PROCESS.poll() is None),
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
    if CURRENT_ML_PROCESS is not None and CURRENT_ML_PROCESS.poll() is None:
        return {"status": "error", "message": "Another ML training job is already running."}
    config = req.model_dump()
    background_tasks.add_task(run_ml_subprocess, config)
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
    is_running = CURRENT_ML_PROCESS is not None and CURRENT_ML_PROCESS.poll() is None
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
    if CURRENT_PAPER_PROCESS is not None and CURRENT_PAPER_PROCESS.poll() is None:
        return {"status": "error", "message": "Another paper simulation is already running."}
    config = req.model_dump()
    background_tasks.add_task(run_paper_subprocess, config)
    return {
        "status": "started",
        "message": f"Paper simulation started for {req.robot} ({req.source})",
        "disclaimer": "Paper mode logs hypothetical orders only; no position state.",
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
    is_running = CURRENT_PAPER_PROCESS is not None and CURRENT_PAPER_PROCESS.poll() is None
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
