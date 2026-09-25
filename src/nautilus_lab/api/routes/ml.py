"""ML model training job and the list of trained models."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks

from nautilus_lab.api.context import Lab
from nautilus_lab.api.jobs import load_json_report, read_log
from nautilus_lab.api.ml_runner import list_models
from nautilus_lab.api.requests import MLTrainRequest

router = APIRouter()


def _busy() -> dict[str, Any]:
    return {"status": "error", "message": "Another ML training job is already running."}


@router.get("/api/ml/models")
def get_ml_models() -> dict[str, Any]:
    return {"models": list_models()}


@router.post("/api/ml/train")
def run_ml_train(
    ctx: Lab, background_tasks: BackgroundTasks, req: MLTrainRequest
) -> dict[str, Any]:
    if ctx.jobs.active("ml_train"):
        return _busy()
    config = req.model_dump()
    if not ctx.jobs.reserve("ml_train"):
        return _busy()
    ctx.jobs.submit(
        background_tasks,
        "ml_train",
        lambda: ctx.jobs.run_module(
            "ml_train",
            "nautilus_lab.api.run_ml_job",
            config,
            log_name="ml_train.log",
            json_name="ml_train.json",
        ),
    )
    return {"status": "started", "message": f"ML training started for {req.model_type}"}


@router.post("/api/ml/train/cancel")
def cancel_ml_train(ctx: Lab) -> dict[str, Any]:
    if not ctx.jobs.cancel("ml_train"):
        return {"status": "idle", "message": "No ML training job is running."}
    return {"status": "cancelled", "message": "ML training job terminated."}


@router.get("/api/ml/train/log")
def get_ml_train_log(ctx: Lab) -> dict[str, Any]:
    is_running = ctx.jobs.active("ml_train")
    content = read_log(ctx.reports_dir / "ml_train.log")
    result = load_json_report(ctx.reports_dir / "ml_train.json")
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
