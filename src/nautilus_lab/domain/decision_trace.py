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

from collections.abc import Mapping, Sequence
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
    #: The entry order was submitted on an earlier bar and has not filled yet. Not a
    #: refusal: the robot already has what it asked for, the venue just has not answered.
    PENDING_FILL = "PENDING_FILL"
    #: A filter inside the robot (e.g. the meta-label classifier) rejected the signal.
    SIGNAL_VETOED = "SIGNAL_VETOED"
    EXIT = "EXIT"
    REVERSE = "REVERSE"
    FLATTEN_REGIME_CHANGE = "FLATTEN_REGIME_CHANGE"
    ENTRY_BLOCKED_RISK = "ENTRY_BLOCKED_RISK"
    ENTRY_SKIPPED_PAUSED = "ENTRY_SKIPPED_PAUSED"
    ENTRY_SKIPPED_SIZE = "ENTRY_SKIPPED_SIZE"
    AUTO_TRADE_OFF = "AUTO_TRADE_OFF"
    SESSION_INACTIVE = "SESSION_INACTIVE"
    STOP_LOSS = "STOP_LOSS"
    #: The ratchet (trailing) overlay closed the position on a closed bar.
    RATCHET_EXIT = "RATCHET_EXIT"
    #: The entry order filled: actual price, size, slippage and the protective stop level.
    ENTRY_FILLED = "ENTRY_FILLED"
    TAKE_PROFIT = "TAKE_PROFIT"
    MANUAL_CLOSE = "MANUAL_CLOSE"
    STOPS_UPDATED = "STOPS_UPDATED"
    PAUSED = "PAUSED"
    RESUMED = "RESUMED"
    ERROR = "ERROR"
    RUN_HEADER = "RUN_HEADER"


class RecordKind(StrEnum):
    BAR_DECISION = "bar_decision"
    INTRABAR = "intrabar"
    #: Once per run, before its first record: the full parameters and config hash. Every
    #: later record carries only `config_hash`, which halves a record's size (docs/30).
    RUN_HEADER = "run_header"


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


def margin_pct(value: Decimal | None, threshold: Decimal | None) -> Decimal | None:
    """How far `value` is past (+) or short of (-) `threshold`, in percent of the threshold.

    The one number that makes near-misses comparable across robots: a VPIN of 0.62 against
    a 0.70 trigger is -11.4%, a breakout 0.2% below the channel is -0.2%. None when either
    side is missing — including a threshold of 0, where the scale does not exist: there is
    no percentage of zero to be short of, and "5% softer" would still be zero.

    That is a limit of the measure, not a hole in the log. A caller whose threshold may be
    zero still has to write the raw pair (`domain/funding.py` logs `net_apy` beside
    `min_net_apy`), so a reader that finds no `*_margin_pct` can see the two numbers the
    percent would have been derived from. The 2026-10 corpus has 11 223 funding records
    with `min_net_apy=0` and therefore no `apy_margin_pct` — every one of them still
    carries the rate, the amortised fee and the annualised net (docs/35 §7, L-11).
    """
    if value is None or threshold is None or threshold == 0:
        return None
    return (value - threshold) / abs(threshold) * Decimal("100")


def is_warmup(trace: tuple[TraceStep, ...]) -> bool:
    """True when the robot could not decide because it is still warming up."""
    return bool(trace) and all(item.stage is Stage.WARMUP for item in trace)


def veto_reason(trace: Sequence[TraceStep]) -> str | None:
    """`<stage>.<component>` of the step that blocked the robot's own signal, if any.

    A robot that refuses inside itself — a meta-label veto, an entry filter, a disabled
    `REGIME_LEGS` leg, `min_hold_bars`, a closed cointegration gate — leaves a
    `Verdict.BLOCK` step and no signal. Both writers (single-leg `signal_strategy` and the
    two-leg `spread_strategy`) turn that into `Outcome.SIGNAL_VETOED` carrying this label,
    because a veto with no reason is invisible in exactly the place a reader looks for it:
    the batch table's blocked column and the digest's blocked tally count `blocked_by`, not
    steps. The corpus that motivated it: 54 964 `SIGNAL_VETOED` records, every one with no
    reason (docs/35 §7, L-8). The label is the vocabulary the entry filters already
    document (`filter.htf_trend`, `filter.vol_expansion`).
    """
    for item in trace:
        if item.verdict is Verdict.BLOCK and item.stage in (Stage.FILTER, Stage.STRATEGY):
            return f"{item.stage.value}.{item.component}"
    return None


def blocked_by_label(code: str) -> str:
    """The `blocked_by` string a decision record carries for an entry that did not open.

    Risk breakers are namespaced `risk.<code>` so a digest can count them apart from the
    execution-state guard and the zero-size skip, which map to their own labels. The live
    paper terminal and the research backtest share this vocabulary (`code` comes from
    `RiskDecision.code`), so one reader serves both.
    """
    if code == "order_working":
        return "execution.order_working"
    if code == "sizing":
        return "sizing"
    return f"risk.{code}"


class Explainable(Protocol):
    """A robot that explains its last `on_bar` call.

    `last_trace` is replaced on every `on_bar`, so it always describes the bar just
    processed. The signature of `on_bar` does not change: the backtest adapters and the
    research code keep using robots exactly as before.
    """

    @property
    def last_trace(self) -> tuple[TraceStep, ...]: ...
