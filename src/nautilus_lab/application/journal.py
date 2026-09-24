"""Append-only research journal.

A run that leaves no trace is a run you will repeat by accident. This module writes one
row per finished run into the human log (`research/journal.md`) and one JSON line into
the machine log (`research/journal.jsonl`).

Rules that make it safe to call from the CLI:

* **Append only.** An existing row is never rewritten, so a decision you typed by hand
  survives the next run. New runs add new rows.
* **Fail closed on a malformed journal.** If the marker pair is missing or inverted,
  writing raises instead of guessing where the table ends.
* **ASCII in code, Ukrainian in the document.** Decision tokens are English words
  (`pending`, `accepted`, ...); the markdown legend explains them.
* Nothing here touches the exchange, the engine or the network: it is bookkeeping.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from nautilus_lab.domain.errors import JournalFormatError
from nautilus_lab.domain.provenance import RunManifest

ROWS_START = "<!-- journal:rows:start -->"
ROWS_END = "<!-- journal:rows:end -->"

#: Decision tokens. The first is what an automatic row gets; a human edits it in place.
PENDING = "pending"
ACCEPTED = "accepted"
REJECTED = "rejected"
RERUN = "rerun"

_DECISION_MARKERS: dict[str, str] = {
    PENDING: "⏳ pending",
    ACCEPTED: "✅ accepted",
    REJECTED: "❌ rejected",
    RERUN: "🔁 rerun",
}

_MAX_CELL = 240


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """One finished run: what was tested, under which gates, with which numbers."""

    created_at: datetime
    source: str
    subject: str
    gates: str
    decision: str = PENDING
    reason: str = ""
    oos_return: Decimal | None = None
    buy_and_hold_return: Decimal | None = None
    fills: int | None = None
    artifact: str | None = None
    #: Code, dependencies, settings and data of the run (docs/27 E-1.4). Only the JSONL
    #: log carries it; the markdown table keeps its columns so hand-typed rows survive.
    provenance: RunManifest | None = None

    def __post_init__(self) -> None:
        if self.decision not in _DECISION_MARKERS:
            raise ValueError(
                f"decision must be one of {sorted(_DECISION_MARKERS)}, got {self.decision!r}"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "created_at": self.created_at.astimezone(UTC).isoformat(),
            "source": self.source,
            "subject": self.subject,
            "gates": self.gates,
            "decision": self.decision,
            "reason": self.reason,
            "oos_return": None if self.oos_return is None else str(self.oos_return),
            "buy_and_hold_return": (
                None if self.buy_and_hold_return is None else str(self.buy_and_hold_return)
            ),
            "fills": self.fills,
            "artifact": self.artifact,
            "provenance": None if self.provenance is None else self.provenance.as_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> JournalEntry:
        """Rebuild an entry from the JSONL log. Rejects anything it cannot trust."""

        def _decimal(key: str) -> Decimal | None:
            value = payload.get(key)
            if value is None:
                return None
            if not isinstance(value, str):
                raise ValueError(f"{key} must be a string or null")
            return Decimal(value)

        created = payload.get("created_at")
        if not isinstance(created, str):
            raise ValueError("created_at must be an ISO-8601 string")
        decision = payload.get("decision")
        if not isinstance(decision, str):
            raise ValueError("decision must be a string")
        fills = payload.get("fills")
        if fills is not None and not isinstance(fills, int):
            raise ValueError("fills must be an integer or null")
        # Records written before E-1.4 have no provenance: that is "unknown", not an error.
        raw_provenance = payload.get("provenance")
        if raw_provenance is not None and not isinstance(raw_provenance, dict):
            raise ValueError("provenance must be an object or null")
        return cls(
            created_at=datetime.fromisoformat(created),
            source=_text(payload, "source"),
            subject=_text(payload, "subject"),
            gates=_text(payload, "gates"),
            decision=decision,
            reason=_text(payload, "reason", allow_empty=True),
            oos_return=_decimal("oos_return"),
            buy_and_hold_return=_decimal("buy_and_hold_return"),
            fills=fills,
            artifact=_optional_text(payload, "artifact"),
            provenance=(
                None
                if raw_provenance is None
                else RunManifest.from_dict({str(k): v for k, v in raw_provenance.items()})
            ),
        )

    def markdown_row(self) -> str:
        cells = (
            self.created_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M"),
            self.source,
            self.subject,
            self.gates,
            _pct(self.oos_return),
            _pct(self.buy_and_hold_return),
            _DECISION_MARKERS[self.decision],
            self.reason,
        )
        return "| " + " | ".join(_cell(item) for item in cells) + " |"


def record_run(*, markdown_path: Path, jsonl_path: Path, entry: JournalEntry) -> None:
    """Append one row to the markdown table and one record to the JSONL log."""
    append_row(markdown_path, entry)
    append_record(jsonl_path, entry)


def append_row(markdown_path: Path, entry: JournalEntry) -> None:
    """Insert a row just before the end marker. Existing rows are left untouched."""
    try:
        text = markdown_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise JournalFormatError(f"journal not found: {markdown_path}") from exc
    start = text.find(ROWS_START)
    end = text.find(ROWS_END)
    if start == -1 or end == -1:
        raise JournalFormatError(
            f"journal {markdown_path} must keep the marker pair {ROWS_START} ... {ROWS_END}; "
            "without it the row has no defined place"
        )
    if end < start:
        raise JournalFormatError(f"journal {markdown_path} has {ROWS_END} before {ROWS_START}")
    head, tail = text[:end], text[end:]
    prefix = "" if head.endswith("\n") else "\n"
    markdown_path.write_text(f"{head}{prefix}{entry.markdown_row()}\n{tail}", encoding="utf-8")


def append_record(jsonl_path: Path, entry: JournalEntry) -> None:
    """Append the machine-readable record. Creates the parent directory if needed."""
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry.as_dict(), ensure_ascii=False)
    with jsonl_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")


def load_records(jsonl_path: Path) -> tuple[JournalEntry, ...]:
    """Read the JSONL log back. A missing file is an empty history, not an error."""
    if not jsonl_path.exists():
        return ()
    entries: list[JournalEntry] = []
    for number, line in enumerate(jsonl_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        decoded = json.loads(line)
        if not isinstance(decoded, dict):
            raise ValueError(f"{jsonl_path}:{number} is not a JSON object")
        entries.append(JournalEntry.from_dict({str(key): item for key, item in decoded.items()}))
    return tuple(entries)


def _pct(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def _cell(value: str) -> str:
    flat = " ".join(value.split())
    if len(flat) > _MAX_CELL:
        flat = f"{flat[: _MAX_CELL - 3]}..."
    return flat.replace("|", "/")


def _text(payload: dict[str, object], key: str, *, allow_empty: bool = False) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    if not value and not allow_empty:
        raise ValueError(f"{key} must not be empty")
    return value


def _optional_text(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string or null")
    return value
