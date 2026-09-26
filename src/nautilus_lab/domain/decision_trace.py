"""Why a robot did (or did not) act on a closed bar, as an ordered chain of steps.

A decision log that only says "signal = None" cannot answer the question people
actually ask of it: *why* was there no trade? Was the regime wrong, did a filter
veto it, was the price 0.2% short of the breakout, or did the risk gate refuse the
entry? This module is the vocabulary for that answer.

Every component on the path from "bar closed" to "order filled" explains its own
verdict as a `TraceStep`: the regime classifier, the flow filters, the strategy leg,
the position plan, the gates (auto-trade, pause, risk) and the execution. The steps
are data — numbers, thresholds, a verdict from a closed set — so they can be counted
and compared, and a human- or LLM-readable narrative is rendered from them
(`application/decision_narrative.py`), never written by hand next to the logic.

Pure domain: no I/O, no clock, no JSON. Values stay `Decimal`; the writer decides how
to serialise them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

#: Written into every record so a reader can tell formats apart. Records without it
#: were written before the trace existed (`v0`) and carry only a signal snapshot.
DECISION_TRACE_SCHEMA = "decision_trace/1"

TraceValue = Decimal | int | str | bool | None


class Stage(StrEnum):
    """Where on the path from closed bar to fill a step sits, in execution order."""

    WARMUP = "warmup"
    REGIME = "regime"
    FILTER = "filter"
    STRATEGY = "strategy"
    PLAN = "plan"
    GATE = "gate"
    EXECUTION = "execution"
    INTRABAR = "intrabar"


class Verdict(StrEnum):
    """What the step did to the decision. A closed set, so it can be counted."""

    PASS = "pass"  # noqa: S105 — a verdict name, not a secret; let the decision through
    BLOCK = "block"  # stopped the decision here
    MODIFY = "modify"  # changed the decision (e.g. a toxic-flow filter re-routed the regime)
    EMIT = "emit"  # produced a signal / an order
    SKIP = "skip"  # not evaluated (not ready, not applicable)
    INFO = "info"  # evaluated, nothing to act on (e.g. no breakout this bar)


class Outcome(StrEnum):
    """The one-word result of a bar or an intrabar event."""

    WARMUP = "WARMUP"
    NO_SIGNAL = "NO_SIGNAL"
    HOLD_NOOP = "HOLD_NOOP"
    ENTRY_OPENED = "ENTRY_OPENED"
    EXIT = "EXIT"
    REVERSE = "REVERSE"
    FLATTEN_REGIME_CHANGE = "FLATTEN_REGIME_CHANGE"
    ENTRY_BLOCKED_RISK = "ENTRY_BLOCKED_RISK"
    ENTRY_SKIPPED_PAUSED = "ENTRY_SKIPPED_PAUSED"
    ENTRY_SKIPPED_SIZE = "ENTRY_SKIPPED_SIZE"
    AUTO_TRADE_OFF = "AUTO_TRADE_OFF"
    SESSION_INACTIVE = "SESSION_INACTIVE"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    MANUAL_CLOSE = "MANUAL_CLOSE"
    STOPS_UPDATED = "STOPS_UPDATED"
    PAUSED = "PAUSED"
    RESUMED = "RESUMED"
    ERROR = "ERROR"


class RecordKind(StrEnum):
    BAR_DECISION = "bar_decision"
    INTRABAR = "intrabar"


@dataclass(frozen=True, slots=True)
class TraceStep:
    """One component's verdict with the numbers it decided on."""

    stage: Stage
    component: str
    verdict: Verdict
    result: str | None = None
    values: Mapping[str, TraceValue] = field(default_factory=dict)
    thresholds: Mapping[str, TraceValue] = field(default_factory=dict)
    note: str | None = None


def step(
    stage: Stage,
    component: str,
    verdict: Verdict,
    *,
    result: str | None = None,
    values: Mapping[str, TraceValue] | None = None,
    thresholds: Mapping[str, TraceValue] | None = None,
    note: str | None = None,
) -> TraceStep:
    """A `TraceStep` whose `None` values are dropped, so records stay compact."""
    return TraceStep(
        stage=stage,
        component=component,
        verdict=verdict,
        result=result,
        values={k: v for k, v in (values or {}).items() if v is not None},
        thresholds={k: v for k, v in (thresholds or {}).items() if v is not None},
        note=note,
    )


def warmup_step(component: str, *, seen: int, required: int | None = None) -> TraceStep:
    """The component cannot decide yet: its windows are still filling."""
    return step(
        Stage.WARMUP,
        component,
        Verdict.SKIP,
        values={"bars_seen": seen, "bars_required": required},
    )


def pct_distance(value: Decimal, reference: Decimal) -> Decimal | None:
    """(value - reference) / reference in percent; None when the reference is 0."""
    if reference == 0:
        return None
    return (value - reference) / reference * Decimal("100")


def is_warmup(trace: tuple[TraceStep, ...]) -> bool:
    """True when the robot could not decide because it is still warming up."""
    return bool(trace) and all(item.stage is Stage.WARMUP for item in trace)


class Explainable(Protocol):
    """A robot that explains its last `on_bar` call.

    `last_trace` is replaced on every `on_bar`, so it always describes the bar just
    processed. The signature of `on_bar` does not change: the backtest adapters and the
    research code keep using robots exactly as before.
    """

    @property
    def last_trace(self) -> tuple[TraceStep, ...]: ...
