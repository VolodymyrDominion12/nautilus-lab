from __future__ import annotations

import datetime
import glob
import os
import re
import subprocess
import time
from typing import Any

import dotenv
import yaml
from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Nautilus Lab API")

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
REPORTS_DIR = os.path.join(ROOT_DIR, "reports")
CATALOG_DIR = os.path.join(ROOT_DIR, "catalog")
SPECS_DIR = os.path.join(ROOT_DIR, "specs", "strategies")

os.makedirs(REPORTS_DIR, exist_ok=True)
app.mount("/static_reports", StaticFiles(directory=REPORTS_DIR), name="static_reports")

# Setup CORS for the React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Process tracking
CURRENT_RESEARCH_PROCESS: subprocess.Popen[str] | None = None
CURRENT_INGEST_PROCESS: subprocess.Popen[str] | None = None


class ResearchRunRequest(BaseModel):
    robot: str = "regime"
    source: str = "catalog"  # "catalog" | "synthetic"
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


class IngestRunRequest(BaseModel):
    symbols: str = "ETHUSDT,BTCUSDT"
    start: str | None = None  # YYYY-MM-DD
    end: str | None = None  # YYYY-MM-DD
    catalog: str | None = None


class SettingsUpdate(BaseModel):
    settings: dict[str, str]


@app.get("/")
def read_root() -> dict[str, str]:
    return {"status": "ok", "message": "Nautilus Lab API is running"}


@app.get("/api/status")
def get_status() -> dict[str, Any]:
    global CURRENT_RESEARCH_PROCESS, CURRENT_INGEST_PROCESS
    res_proc = CURRENT_RESEARCH_PROCESS
    ing_proc = CURRENT_INGEST_PROCESS
    research_running = res_proc is not None and res_proc.poll() is None
    ingest_running = ing_proc is not None and ing_proc.poll() is None

    return {
        "active_bots": 0,
        "research_running": research_running,
        "ingest_running": ingest_running,
        "strategies_available": ["regime", "ema", "pairs", "vpin_momentum", "formulaic_lgbm"],
        "is_live": False,
        "live_safe_mode": "FAIL_CLOSED",
    }


@app.get("/api/catalog")
def get_catalog() -> dict[str, Any]:
    if not os.path.exists(CATALOG_DIR):
        return {"catalog_path": CATALOG_DIR, "exists": False, "instruments": []}

    try:
        import pandas as pd
        from nautilus_trader.persistence.catalog import ParquetDataCatalog

        cat = ParquetDataCatalog(CATALOG_DIR)
        instruments_info = []
        for inst in cat.instruments():
            bars = cat.bars(instrument_ids=[str(inst.id)])
            count = len(bars)
            first_dt = str(pd.to_datetime(bars[0].ts_event, unit="ns")) if count > 0 else None
            last_dt = str(pd.to_datetime(bars[-1].ts_event, unit="ns")) if count > 0 else None

            raw_sym = (
                inst.raw_symbol.value if hasattr(inst.raw_symbol, "value") else str(inst.raw_symbol)
            )
            instruments_info.append(
                {
                    "instrument_id": str(inst.id),
                    "raw_symbol": raw_sym,
                    "bars_count": count,
                    "first_date": first_dt,
                    "last_date": last_dt,
                    "quote_currency": str(inst.quote_currency),
                    "maker_fee": float(inst.maker_fee),
                    "taker_fee": float(inst.taker_fee),
                }
            )

        return {
            "catalog_path": CATALOG_DIR,
            "exists": True,
            "instruments": instruments_info,
            "total_instruments": len(instruments_info),
        }
    except Exception as e:
        return {"catalog_path": CATALOG_DIR, "exists": True, "error": str(e), "instruments": []}


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


def _parse_research_output(log_text: str) -> dict[str, Any]:
    is_fin = "Process finished with code" in log_text or "Exception occurred" in log_text
    is_err = (
        "Process finished with code 1" in log_text
        or "Exception occurred" in log_text
        or "Traceback" in log_text
    )
    summary: dict[str, Any] = {
        "is_finished": is_fin,
        "is_error": is_err,
        "tearsheet_url": None,
        "multi_window": None,
        "single_backtest": None,
        "raw_summary": None,
    }

    # Tearsheet link
    m_ts = re.search(r"tearsheet_saved=([^\s]+)", log_text)
    if m_ts:
        saved_path = m_ts.group(1)
        summary["tearsheet_url"] = f"/static_reports/{os.path.basename(saved_path)}"

    # Multi-window walk-forward
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

    # Single walk-forward or synthetic backtest
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


def run_research_subprocess(cmd: list[str], log_path: str) -> None:
    global CURRENT_RESEARCH_PROCESS
    with open(log_path, "w") as f:
        f.write(f"Command: {' '.join(cmd)}\n")
        f.write(f"Started at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.flush()
        try:
            CURRENT_RESEARCH_PROCESS = subprocess.Popen(
                cmd,
                stdout=f,
                stderr=subprocess.STDOUT,
                text=True,
            )
            CURRENT_RESEARCH_PROCESS.wait()
            f.write(f"\nProcess finished with code {CURRENT_RESEARCH_PROCESS.returncode}\n")
        except Exception as e:
            f.write(f"\nException occurred: {e!s}\n")


@app.post("/api/research")
def run_research(background_tasks: BackgroundTasks, req: ResearchRunRequest) -> dict[str, Any]:
    global CURRENT_RESEARCH_PROCESS
    res_proc = CURRENT_RESEARCH_PROCESS
    if res_proc is not None and res_proc.poll() is None:
        return {"status": "error", "message": "Another research process is already running."}

    log_path = os.path.join(REPORTS_DIR, "last_run.log")
    open(log_path, "w").close()

    ts = int(time.time())
    tearsheet_filename = f"tearsheet_{req.robot}_{ts}.html"
    tearsheet_path = os.path.join("reports", tearsheet_filename)

    cmd = [
        ".venv/bin/python",
        "-m",
        "nautilus_lab.interfaces.cli",
        "research",
        "--robot",
        req.robot,
    ]

    if req.source == "synthetic":
        cmd.extend(["--synthetic", "--bars", str(req.bars)])
    else:
        # Catalog mode
        if req.folds >= 2:
            cmd.extend(["--folds", str(req.folds)])
        else:
            cmd.append("--walk-forward")
        cmd.extend(["--is-fraction", str(req.is_fraction)])

    if req.embargo_bars is not None and req.embargo_bars > 0:
        cmd.extend(["--embargo-bars", str(req.embargo_bars)])

    if req.use_optuna:
        cmd.extend(["--optuna", "--trials", str(req.optuna_trials)])

    if req.pbo:
        cmd.extend(["--pbo", "--pbo-blocks", str(req.pbo_blocks)])

    if req.bar_vpin:
        cmd.append("--bar-vpin")

    if req.stress_slice:
        cmd.extend(["--slice", req.stress_slice])

    if req.generate_tearsheet and not req.pbo:
        cmd.extend(["--tearsheet", tearsheet_path])

    if req.journal:
        cmd.append("--journal")

    background_tasks.add_task(run_research_subprocess, cmd, log_path)
    return {
        "status": "started",
        "message": f"Research run launched for {req.robot} ({req.source} mode)",
        "command": " ".join(cmd),
    }


@app.get("/api/research/log")
def get_research_log() -> dict[str, Any]:
    global CURRENT_RESEARCH_PROCESS
    res_proc = CURRENT_RESEARCH_PROCESS
    is_running = res_proc is not None and res_proc.poll() is None
    log_path = os.path.join(REPORTS_DIR, "last_run.log")
    content = ""
    if os.path.exists(log_path):
        with open(log_path) as f:
            content = f.read()

    summary = _parse_research_output(content)
    return {
        "is_running": is_running,
        "log": content,
        "summary": summary,
    }


def run_ingest_subprocess(cmd: list[str], log_path: str) -> None:
    global CURRENT_INGEST_PROCESS
    with open(log_path, "w") as f:
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
    open(log_path, "w").close()

    cmd = [".venv/bin/python", "-m", "nautilus_lab.interfaces.cli", "ingest"]
    if req.symbols:
        cmd.extend(["--symbols", req.symbols])
    if req.start:
        cmd.extend(["--start", req.start])
    if req.end:
        cmd.extend(["--end", req.end])
    if req.catalog:
        cmd.extend(["--catalog", req.catalog])

    background_tasks.add_task(run_ingest_subprocess, cmd, log_path)
    return {
        "status": "started",
        "message": f"Ingest started for symbols: {req.symbols}",
        "command": " ".join(cmd),
    }


@app.get("/api/catalog/ingest/log")
def get_ingest_log() -> dict[str, Any]:
    global CURRENT_INGEST_PROCESS
    ing_proc = CURRENT_INGEST_PROCESS
    is_running = ing_proc is not None and ing_proc.poll() is None
    log_path = os.path.join(REPORTS_DIR, "ingest.log")
    content = ""
    if os.path.exists(log_path):
        with open(log_path) as f:
            content = f.read()
    return {
        "is_running": is_running,
        "log": content,
    }


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    env_path = os.path.join(ROOT_DIR, ".env")
    if not os.path.exists(env_path):
        env_path = os.path.join(ROOT_DIR, ".env.example")

    config = dotenv.dotenv_values(env_path)
    return {"settings": config}


@app.put("/api/settings")
def update_settings(update: SettingsUpdate) -> dict[str, str]:
    env_path = os.path.join(ROOT_DIR, ".env")
    if not os.path.exists(env_path):
        open(env_path, "a").close()

    for key, value in update.settings.items():
        dotenv.set_key(env_path, key, str(value))

    return {"status": "success"}
