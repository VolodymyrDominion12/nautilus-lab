"""DecisionRecord <-> the JSON row written to `data/paper/decisions/*.jsonl`.

Numbers in the trace are diagnostics, not accounting: they are written as JSON numbers
rounded to 8 significant digits, so a person, `jq` or an LLM reads `0.3412` instead of
`"0.34123456789012345678"`. The trade journal keeps exact decimals for money.

The top-level `close` stays a string as before (the dashboard and old readers parse it),
and `indicators` / `states` keep their v0 shape, now derived from the steps so the regime
robot no longer writes them empty.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from nautilus_lab.domain.decision_log import DecisionRecord
from nautilus_lab.domain.decision_trace import Stage, TraceStep

_SIGNIFICANT = 8


def plain_number(value: object) -> object:
    """Decimal -> float (8 significant digits); datetimes -> ISO; the rest unchanged."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            return str(value)
        return float(f"{value:.{_SIGNIFICANT}g}")
    if isinstance(value, float):
        return float(f"{value:.{_SIGNIFICANT}g}")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): plain_number(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain_number(v) for v in value]
    return value


def step_to_dict(item: TraceStep) -> dict[str, Any]:
    row: dict[str, Any] = {
        "stage": item.stage.value,
        "component": item.component,
        "verdict": item.verdict.value,
    }
    if item.result is not None:
        row["result"] = item.result
    if item.values:
        row["values"] = plain_number(item.values)
    if item.thresholds:
        row["thresholds"] = plain_number(item.thresholds)
    if item.note:
        row["note"] = item.note
    return row


def legacy_indicators(steps: tuple[TraceStep, ...]) -> dict[str, str]:
    """v0 `indicators`: the numbers the regime and strategy steps decided on."""
    out: dict[str, str] = {}
    for item in steps:
        if item.stage in (Stage.REGIME, Stage.STRATEGY):
            for key, value in item.values.items():
                if value is not None and key not in out:
                    out[key] = str(plain_number(value))
    return out


def legacy_states(steps: tuple[TraceStep, ...]) -> dict[str, Any]:
    """v0 `states`: filter readings, keyed `<filter>` and `<filter>_toxic`."""
    out: dict[str, Any] = {}
    for item in steps:
        if item.stage is Stage.FILTER and item.result is not None:
            first = next(iter(item.values.values()), None)
            if first is not None:
                out[item.component] = str(plain_number(first))
            out[f"{item.component}_toxic"] = str(item.result == "toxic")
    return out


def record_to_dict(record: DecisionRecord) -> dict[str, Any]:
    """The JSONL row. Keys of the v0 record come first and keep their meaning."""
    row: dict[str, Any] = {
        "schema": record.schema,
        "kind": record.kind.value,
        "ts": record.bar_end_utc.isoformat(),
        "session_id": record.session_id,
        "robot": record.robot,
        "instrument": record.instrument_id,
        "close": str(record.close_price),
        "regime": record.regime,
        "signal": record.signal,
        "signal_reason": record.signal_reason,
        "indicators": record.indicators,
        "states": record.states,
        "outcome": record.outcome,
        "blocked_by": record.blocked_by,
        "fill_ids": list(record.fill_ids),
    }
    if record.bar_seq is not None:
        row["bar_seq"] = record.bar_seq
    if record.bar:
        row["bar"] = plain_number(record.bar)
    if record.account:
        row["account"] = plain_number(record.account)
    row["steps"] = [step_to_dict(item) for item in record.steps]
    if record.config_hash:
        row["config_hash"] = record.config_hash
    if record.narrative:
        row["narrative"] = record.narrative
    return row


def is_v0(row: Mapping[str, Any]) -> bool:
    """Rows written before the trace existed: a signal snapshot, no steps, no outcome."""
    return "schema" not in row


def upgrade_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """A v0 row in the v1 shape, so one reader handles both (outcome unknown for v0)."""
    if not is_v0(row):
        return dict(row)
    upgraded = dict(row)
    upgraded["schema"] = "decision_trace/0"
    upgraded.setdefault("kind", "bar_decision")
    upgraded.setdefault("steps", [])
    upgraded.setdefault("outcome", "UNKNOWN_V0")
    upgraded.setdefault("blocked_by", None)
    upgraded.setdefault("fill_ids", [])
    return upgraded
