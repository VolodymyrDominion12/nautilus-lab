"""Digest + optional LLM answer for a set of decision records (offline research only).

The route (`api/routes/decision_analysis.py`) only finds the rows and the model; this
function does the work, so it is testable without a web server or a network. With no
model it returns the digest and the prompt instead of an answer: the caller shows the
Markdown, which can be pasted into any chat. It never invents numbers.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nautilus_lab.application.decision_digest import (
    PRESET_QUESTIONS,
    build_digest,
    build_prompt,
    digest_markdown,
)
from nautilus_lab.domain.ports import ChatCompleter

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def resolve_question(question: str | None, preset: str | None) -> str:
    if question and question.strip():
        return question.strip()
    if preset and preset in PRESET_QUESTIONS:
        return PRESET_QUESTIONS[preset]
    return PRESET_QUESTIONS["why_no_trades"]


def analyze_records(
    rows: Sequence[Mapping[str, Any]],
    *,
    question: str,
    completer: ChatCompleter | None,
    model: str | None = None,
    reports_dir: Path | None = None,
    root: Path | None = None,
    session_id: str | None = None,
    no_model_status: str = "no_llm",
) -> dict[str, Any]:
    """Digest the rows; ask the model when one is given; save the report when it answered."""
    digest = build_digest(rows)
    system, user = build_prompt(digest, question)
    markdown = digest_markdown(digest)
    base: dict[str, Any] = {"digest": digest.as_dict(), "markdown": markdown, "question": question}
    if completer is None:
        return {
            **base,
            "status": no_model_status,
            "analysis": None,
            "message": (
                "LLM_API_KEY is not configured: the digest is ready to paste into any chat."
                if no_model_status == "no_llm"
                else "Dry run: prompt built, model not called."
            ),
            "prompt": {"system": system, "user": user},
        }
    answer = completer.complete(system=system, user=user)
    saved: str | None = None
    if reports_dir is not None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        name = _UNSAFE.sub("_", session_id or digest.session_id or "records").strip("._-")
        out_dir = reports_dir / "decision-analysis"
        path = out_dir / f"{name or 'records'}_{stamp}.md"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"{markdown}\n\n## Питання\n\n{question}\n\n"
                f"## Відповідь ({model or 'LLM'})\n\n{answer}\n",
                encoding="utf-8",
            )
            saved = str(path.relative_to(root)) if root is not None else str(path)
        except (OSError, ValueError):
            saved = None
    return {**base, "status": "ok", "analysis": answer, "report": saved, "model": model}
