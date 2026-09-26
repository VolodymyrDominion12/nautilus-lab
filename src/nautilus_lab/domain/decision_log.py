"""One line of the decision log: what the robot saw, why it decided, and what happened.

`decision_trace/1` (docs: the decision-trace plan) extends the original snapshot record
instead of replacing it, so everything that already reads `signal`, `regime`,
`indicators` and `states` keeps working:

* `steps` — the ordered chain of verdicts (`domain/decision_trace.py`);
* `outcome` / `blocked_by` / `fill_ids` — what the bar turned into after the gates and
  the execution, which the old record (written before execution) could not know;
* `account` — the position and risk marks the gates decided on;
* `narrative` — the same chain rendered as text for people and for an LLM.

`kind` separates the one-per-closed-bar record from intrabar events (stop, target,
manual close, pause), which used to exist only in the trade journal.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from nautilus_lab.domain.decision_trace import DECISION_TRACE_SCHEMA, RecordKind, TraceStep


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    bar_end_utc: datetime
    robot: str
    instrument_id: str
    close_price: Decimal
    regime: str
    signal: str | None
    signal_reason: str | None
    indicators: dict[str, str]
    states: dict[str, Any]
    session_id: str | None = None
    # --- decision_trace/1 -----------------------------------------------------------
    kind: RecordKind = RecordKind.BAR_DECISION
    schema: str = DECISION_TRACE_SCHEMA
    bar_seq: int | None = None
    bar: Mapping[str, Decimal] = field(default_factory=dict)
    account: Mapping[str, Any] = field(default_factory=dict)
    steps: tuple[TraceStep, ...] = ()
    outcome: str | None = None
    blocked_by: str | None = None
    fill_ids: tuple[str, ...] = ()
    config_hash: str | None = None
    narrative: str | None = None
