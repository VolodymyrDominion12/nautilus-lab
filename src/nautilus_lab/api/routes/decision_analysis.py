"""Decision-log digest and LLM analysis (offline research, never on the trading path).

`POST /api/decisions/analyze` used to return a canned text with invented numbers
("filters blocked 15% of signals"). It now builds a digest with real counts from a
session's log files, or from the records the caller sends, and asks the configured
OpenAI-compatible model when `LLM_API_KEY` is set (the answer is saved under
`reports/decision-analysis/`). Without a key it answers `status: "no_llm"` with the
digest Markdown, ready to paste into any chat (`application/decision_analysis.py`).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from nautilus_lab.api.context import Lab, LabContext
from nautilus_lab.application.decision_analysis import analyze_records, resolve_question
from nautilus_lab.application.decision_digest import (
    PRESET_QUESTIONS,
    build_digest,
    digest_markdown,
)
from nautilus_lab.infrastructure.llm_client import LlmRequestError

router = APIRouter()

#: Records sent inline are capped: the digest counts them, but a browser should not post
#: a week of 1m bars.
MAX_INLINE_RECORDS = 20000


class AnalyzeDecisionsRequest(BaseModel):
    session: str | None = None
    records: list[dict[str, Any]] = Field(default_factory=list)
    question: str = ""
    preset: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    dry_run: bool = False


def _session_rows(
    ctx: LabContext, key: str, since: datetime | None, until: datetime | None
) -> tuple[str, list[dict[str, Any]]]:
    registry = ctx.sessions
    manager = registry.find(key)
    session_id = manager.session_id if manager is not None and manager.session_id else key
    writer = registry.decision_log_writer
    read_range = getattr(writer, "read_range", None)
    if read_range is None:
        raise HTTPException(status_code=409, detail="Decision logging is disabled")
    rows: list[dict[str, Any]] = read_range(session_id, since=since, until=until)
    return session_id, rows


@router.get("/api/decisions/presets")
def decision_presets() -> dict[str, Any]:
    return {"status": "ok", "presets": PRESET_QUESTIONS}


@router.get("/api/paper/sessions/{key}/decision-digest")
def decision_digest(
    ctx: Lab,
    key: str,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """Counts and key narratives of one session, as JSON and as paste-ready Markdown."""
    _, rows = _session_rows(ctx, key, since, until)
    digest = build_digest(rows)
    return {"status": "ok", "digest": digest.as_dict(), "markdown": digest_markdown(digest)}


@router.post("/api/decisions/analyze")
async def analyze_decisions(ctx: Lab, req: AnalyzeDecisionsRequest) -> dict[str, Any]:
    """Digest of a session (or of the posted records) plus, when configured, an LLM answer."""
    if req.session:
        session_id: str | None
        session_id, rows = _session_rows(ctx, req.session, req.since, req.until)
    else:
        session_id, rows = None, req.records[:MAX_INLINE_RECORDS]
    if not rows:
        raise HTTPException(status_code=400, detail="No decision records to analyze.")
    question = resolve_question(req.question, req.preset)
    cfg = ctx.settings()
    if req.dry_run or not (cfg.llm_api_key or "").strip():
        return analyze_records(
            rows,
            question=question,
            completer=None,
            no_model_status="dry_run" if req.dry_run else "no_llm",
        )

    # Imported here: the research-only client must not load with the trading API.
    from nautilus_lab.interfaces.composition import llm_completer

    try:
        completer = llm_completer(cfg)
        return await asyncio.to_thread(
            analyze_records,
            rows,
            question=question,
            completer=completer,
            model=cfg.llm_model,
            reports_dir=ctx.reports_dir,
            root=ctx.root,
            session_id=session_id,
        )
    except LlmRequestError as exc:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}") from exc
