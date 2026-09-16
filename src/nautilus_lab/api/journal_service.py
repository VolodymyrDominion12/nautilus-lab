from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nautilus_lab.application.journal import (
    ACCEPTED,
    PENDING,
    REJECTED,
    RERUN,
    JournalEntry,
    load_records,
)
from nautilus_lab.interfaces.composition import journal_paths, settings

VALID_DECISIONS = frozenset({PENDING, ACCEPTED, REJECTED, RERUN})


def list_journal_entries() -> list[dict[str, Any]]:
    cfg = settings()
    _, jsonl_path = journal_paths(cfg)
    entries = load_records(jsonl_path)
    rows: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        row = entry.as_dict()
        row["index"] = index
        rows.append(row)
    rows.reverse()
    return rows


def update_journal_decision(index: int, decision: str) -> dict[str, Any]:
    if decision not in VALID_DECISIONS:
        msg = f"decision must be one of {sorted(VALID_DECISIONS)}"
        raise ValueError(msg)
    cfg = settings()
    _, jsonl_path = journal_paths(cfg)
    entries = list(load_records(jsonl_path))
    if index < 0 or index >= len(entries):
        msg = f"journal index out of range: {index}"
        raise ValueError(msg)
    current = entries[index]
    updated = JournalEntry(
        created_at=current.created_at,
        source=current.source,
        subject=current.subject,
        gates=current.gates,
        decision=decision,
        reason=current.reason,
        oos_return=current.oos_return,
        buy_and_hold_return=current.buy_and_hold_return,
        fills=current.fills,
        artifact=current.artifact,
    )
    entries[index] = updated
    _rewrite_jsonl(jsonl_path, entries)
    row = updated.as_dict()
    row["index"] = index
    return row


def _rewrite_jsonl(jsonl_path: Path, entries: list[JournalEntry]) -> None:
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(entry.as_dict(), ensure_ascii=False) for entry in entries]
    jsonl_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def journal_summary() -> dict[str, int]:
    counts = {PENDING: 0, ACCEPTED: 0, REJECTED: 0, RERUN: 0}
    for row in list_journal_entries():
        decision = str(row.get("decision", PENDING))
        if decision in counts:
            counts[decision] += 1
    return counts
