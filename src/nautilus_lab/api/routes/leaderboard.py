"""Leaderboard API routes: list and query ranked backtest runs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from nautilus_lab.api.context import Lab
from nautilus_lab.application.leaderboard import (
    load_leaderboard_entries,
    rank_leaderboard_entries,
    regenerate_markdown_file,
)
from nautilus_lab.interfaces.composition import leaderboard_paths

router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard"])


@router.get("")
def get_leaderboard(
    ctx: Lab,
    limit: int = Query(50, ge=1, le=500),
    sort_by: str = Query("oos", pattern="^(oos|excess|sharpe|drawdown|fills|date)$"),
    robot: str | None = None,
    instrument: str | None = None,
    timeframe: str | None = None,
) -> dict[str, Any]:
    """Retrieve ranked backtest runs for the leaderboard."""
    _, jsonl_path = leaderboard_paths(ctx.settings())
    entries = list(load_leaderboard_entries(jsonl_path))

    if robot:
        entries = [e for e in entries if e.robot.lower() == robot.lower()]
    if instrument:
        entries = [e for e in entries if instrument.lower() in e.instrument_id.lower()]
    if timeframe:
        entries = [e for e in entries if e.timeframe.lower() == timeframe.lower()]

    ranked = rank_leaderboard_entries(entries, sort_by=sort_by)
    return {
        "entries": [e.as_dict() for e in ranked[:limit]],
        "total": len(entries),
        "sort_by": sort_by,
    }


@router.get("/{entry_id}")
def get_leaderboard_entry(
    ctx: Lab,
    entry_id: str,
) -> dict[str, Any]:
    """Retrieve full details and reproduction instructions for a specific leaderboard entry."""
    _, jsonl_path = leaderboard_paths(ctx.settings())
    entries = load_leaderboard_entries(jsonl_path)
    for entry in entries:
        if entry.id == entry_id:
            return entry.as_dict()
    raise HTTPException(status_code=404, detail=f"Leaderboard entry {entry_id!r} not found")


@router.post("/sync")
def sync_leaderboard(ctx: Lab) -> dict[str, Any]:
    """Regenerate the human-readable research/leaderboard.md table from the JSONL log."""
    md_path, jsonl_path = leaderboard_paths(ctx.settings())
    regenerate_markdown_file(md_path, jsonl_path)
    return {"status": "ok", "message": f"Leaderboard updated at {md_path}"}
