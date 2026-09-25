"""The batch paper job: replay closed bars through the simulated venue, log the orders."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from nautilus_lab.api.context import Lab
from nautilus_lab.api.jobs import load_json_report, read_log
from nautilus_lab.api.requests import PaperRunRequest
from nautilus_lab.application.run_paper import PAPER_SUPPORTED_ROBOTS
from nautilus_lab.domain.regime import RobotName

router = APIRouter()


def _busy() -> dict[str, Any]:
    return {"status": "error", "message": "Another paper simulation is already running."}


@router.post("/api/paper/run")
def run_paper(ctx: Lab, background_tasks: BackgroundTasks, req: PaperRunRequest) -> dict[str, Any]:
    if ctx.jobs.active("paper"):
        return _busy()
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
    if not ctx.jobs.reserve("paper"):
        return _busy()
    ctx.jobs.submit(
        background_tasks,
        "paper",
        lambda: ctx.jobs.run_module(
            "paper",
            "nautilus_lab.api.run_paper_job",
            config,
            log_name="paper.log",
            json_name="paper.json",
        ),
    )
    return {
        "status": "started",
        "message": f"Paper simulation started for {req.robot} ({req.source})",
        "disclaimer": (
            "Paper session: the simulated venue fills against closed bars. "
            "No exchange is contacted and no order is submitted."
        ),
    }


@router.post("/api/paper/cancel")
def cancel_paper(ctx: Lab) -> dict[str, Any]:
    if not ctx.jobs.cancel("paper"):
        return {"status": "idle", "message": "No paper simulation is running."}
    return {"status": "cancelled", "message": "Paper simulation terminated."}


@router.get("/api/paper/log")
def get_paper_log(ctx: Lab) -> dict[str, Any]:
    is_running = ctx.jobs.active("paper")
    content = read_log(ctx.reports_dir / "paper.log")
    result = load_json_report(ctx.reports_dir / "paper.json")
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
