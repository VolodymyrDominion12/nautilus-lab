"""Append-only log of paper sessions.

A paper session that leaves no trace is a session you will repeat by accident, and
one whose fills you cannot check afterwards is not evidence of anything. This writes
one JSON object per session — window, frozen configuration, every fill, every
position, fees and the closing mark — so a session can be re-read without re-running
it, and so two sessions can be compared.

Deliberately not part of the research journal: `research/journal.md` is a git-tracked
record of *research decisions*, while paper sessions are runtime artifacts under
`reports/` that would otherwise bury the decisions in noise.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nautilus_lab.application.dtos import PaperSessionReport

DEFAULT_SESSION_LOG = "reports/paper/sessions.jsonl"


def session_record(report: PaperSessionReport, *, created_at: str) -> dict[str, Any]:
    """Machine-readable session record. Decimals become strings, never floats."""
    return {
        "created_at": created_at,
        "robot": report.robot.value,
        "instrument_id": report.instrument_id,
        "mode": report.mode.value,
        "source": report.source,
        "bars": report.bar_count,
        "window_start": None if report.window_start is None else report.window_start.isoformat(),
        "window_end": None if report.window_end is None else report.window_end.isoformat(),
        "starting_equity": str(report.starting_equity),
        "ending_equity": None if report.ending_equity is None else str(report.ending_equity),
        "realized_pnl": str(report.realized_pnl),
        "unrealized_pnl": str(report.unrealized_pnl),
        "mark_price": None if report.mark_price is None else str(report.mark_price),
        "fees_paid": str(report.fees_paid),
        "traded_notional": str(report.traded_notional),
        "turnover": str(report.turnover),
        "fill_count": len(report.fills),
        "position_count": len(report.positions),
        "open_position": (
            None
            if report.open_position is None
            else {
                "side": report.open_position.side,
                "qty": str(report.open_position.qty),
                "entry_price": str(report.open_position.entry_price),
            }
        ),
        "risk_breaches": dict(report.risk_breaches),
        "fills": [
            {
                "ts_utc": fill.ts_utc.isoformat(),
                "instrument_id": fill.instrument_id,
                "side": fill.side,
                "qty": str(fill.qty),
                "price": str(fill.price),
                "commission": str(fill.commission),
                "liquidity": fill.liquidity,
                "is_reduce_only": fill.is_reduce_only,
            }
            for fill in report.fills
        ],
        "positions": [
            {
                "instrument_id": position.instrument_id,
                "side": position.side,
                "qty": str(position.qty),
                "entry_price": str(position.entry_price),
                "exit_price": None if position.exit_price is None else str(position.exit_price),
                "opened_utc": position.opened_utc.isoformat(),
                "closed_utc": (
                    None if position.closed_utc is None else position.closed_utc.isoformat()
                ),
                "realized_pnl": str(position.realized_pnl),
                "is_open": position.is_open,
            }
            for position in report.positions
        ],
    }


def append_session(
    report: PaperSessionReport,
    *,
    created_at: str,
    path: Path | str = DEFAULT_SESSION_LOG,
) -> Path:
    """Append one session line and return the file written. Append only, never rewrite."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = session_record(report, created_at=created_at)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return target
