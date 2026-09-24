"""Append-only event log of the live paper terminal, and what can be resumed from it.

The live terminal (`api/paper_streamer.py`) used to keep its whole ledger in process
memory: a deploy, a crash or a VPS reboot erased the open position, every fill and the
equity curve, and nothing started the session again. On a server that is expected to
run for weeks, that makes the ledger worthless as evidence.

One JSON object per line, never rewritten:

* ``session_start`` — session id, the frozen configuration it trades with and the
                      provenance of the code (git revision, lock hash, versions);
* ``session_resume`` — the process restarted and continued the session; carries the
                      provenance of the code that runs from here on (a deploy may
                      have changed it);
* ``fill``          — every simulated fill, exactly as the terminal shows it;
* ``snapshot``      — the account after every closed bar, fill or stop change:
                      balance, fees, breaker marks, the open position and the
                      equity point of that bar;
* ``session_stop``  — written only when a person stops the session.

A process that dies (SIGTERM on deploy, OOM, reboot) writes no ``session_stop``, so
the last started session is *resumable*: its last snapshot is the state to restore,
its fills are the ledger, its snapshots are the equity curve. A torn last line — the
process died mid-write — is skipped, never fatal: losing one snapshot costs one bar,
refusing to start costs the whole session.

The same file is the research artifact: pull it to the workstation and read it with
``pandas.read_json(path, lines=True)``.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SESSION_START = "session_start"
SESSION_STOP = "session_stop"
SESSION_RESUME = "session_resume"
FILL = "fill"
SNAPSHOT = "snapshot"


@dataclass(frozen=True, slots=True)
class ResumableSession:
    """Everything needed to continue a session the process did not stop on purpose."""

    session_id: str
    started_at: str
    config: dict[str, Any]
    snapshot: dict[str, Any] | None
    fills: list[dict[str, Any]] = field(default_factory=list)
    equity_points: list[dict[str, Any]] = field(default_factory=list)


class LivePaperJournal:
    """Append-only JSONL writer/reader. One instance per file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    # ------------------------------------------------------------------ writing
    def append(self, event_type: str, session_id: str, payload: dict[str, Any]) -> None:
        record = {
            "type": event_type,
            "session_id": session_id,
            "logged_at": datetime.now(UTC).isoformat(),
            **payload,
        }
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            # A paper ledger that loses its last fill on power loss is not a ledger.
            # One fsync per closed bar or fill is nothing at bar frequencies.
            os.fsync(handle.fileno())

    # ------------------------------------------------------------------ reading
    def events(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as handle:
            for number, raw in enumerate(handle, start=1):
                text = raw.strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                except json.JSONDecodeError:
                    logger.warning(
                        "%s:%d is not valid JSON (torn write?); skipped", self.path, number
                    )
                    continue
                if isinstance(record, dict) and "type" in record and "session_id" in record:
                    yield record

    def load_resumable(self, *, max_equity_points: int = 500) -> ResumableSession | None:
        """The last started session, unless a person stopped it. None when nothing to resume."""
        start: dict[str, Any] | None = None
        fills: list[dict[str, Any]] = []
        snapshots: list[dict[str, Any]] = []
        stopped = False
        for record in self.events():
            kind = record["type"]
            if kind == SESSION_START:
                start, fills, snapshots, stopped = record, [], [], False
                continue
            if start is None or record["session_id"] != start["session_id"]:
                continue
            if kind == FILL and isinstance(record.get("fill"), dict):
                fills.append(record["fill"])
            elif kind == SNAPSHOT:
                snapshots.append(record)
            elif kind == SESSION_STOP:
                stopped = True
        if start is None or stopped or not isinstance(start.get("config"), dict):
            return None
        equity_points = [
            snap["equity_point"] for snap in snapshots if isinstance(snap.get("equity_point"), dict)
        ][-max_equity_points:]
        return ResumableSession(
            session_id=str(start["session_id"]),
            started_at=str(start.get("started_at") or start.get("logged_at") or ""),
            config=start["config"],
            snapshot=snapshots[-1] if snapshots else None,
            fills=fills,
            equity_points=equity_points,
        )

    def sessions(self) -> list[SessionRecord]:
        """Every session this file has seen, oldest first: identity, config, final state."""
        found: dict[str, SessionRecord] = {}
        for record in self.events():
            sid = str(record["session_id"])
            kind = record["type"]
            if kind == SESSION_START and isinstance(record.get("config"), dict):
                found[sid] = SessionRecord(
                    session_id=sid,
                    started_at=str(record.get("started_at") or record.get("logged_at") or ""),
                    config=record["config"],
                    path=self.path,
                )
                continue
            entry = found.get(sid)
            if entry is None:
                continue
            if kind == SNAPSHOT:
                entry.last_snapshot = record
            elif kind == FILL:
                entry.fill_count += 1
            elif kind == SESSION_STOP:
                entry.stopped = True
                entry.stopped_at = str(record.get("stopped_at") or record.get("logged_at") or "")
        return list(found.values())


@dataclass(slots=True)
class SessionRecord:
    """One session as a journal remembers it (running, interrupted or stopped)."""

    session_id: str
    started_at: str
    config: dict[str, Any]
    path: Path
    stopped: bool = False
    stopped_at: str | None = None
    fill_count: int = 0
    last_snapshot: dict[str, Any] | None = None

    @property
    def name(self) -> str:
        return str(self.config.get("name") or "")
