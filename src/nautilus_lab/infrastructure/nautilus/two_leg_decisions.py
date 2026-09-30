"""Decision records for the two-leg robots (pairs, funding cash-and-carry).

Until 2026-09-30 `SpreadRobot` and `FundingRobot` wrote no decision log at all: the
2026-09-29 sweep produced 0-byte journals for `pairs` and `funding`, so "why did funding
never trade" (net APY after fees below the gate) and "why does pairs lose 13% per fold"
could not be read off the log. This module gives both adapters the same
`decision_trace/1` record the single-leg `SignalRobot` writes, so the digest, the
narrative, the trade reconstruction and the dashboard read them without branching.

The record is keyed on **leg A** (pairs: leg A; funding: the spot leg): its close, its
side as the record's `signal`, its instrument as the record's instrument. The other leg
appears in the execution steps with its own quantity and price.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from nautilus_lab.application.decision_narrative import render_narrative
from nautilus_lab.application.decision_trace_codec import (
    legacy_indicators,
    legacy_states,
    record_to_dict,
)
from nautilus_lab.domain.decision_log import DecisionRecord
from nautilus_lab.domain.decision_trace import (
    Outcome,
    RecordKind,
    Stage,
    TraceStep,
    TraceValue,
    Verdict,
    blocked_by_label,
    step,
)
from nautilus_lab.domain.ports import DecisionLogPort
from nautilus_lab.domain.position_plan import Holding


class TwoLegDecisionLog:
    """Builds and writes one `DecisionRecord` per decision of a two-leg robot."""

    def __init__(
        self,
        *,
        decision_log: DecisionLogPort | None,
        session_id: str | None,
        robot: str,
        instrument_id: str,
        params: Mapping[str, object],
    ) -> None:
        self._log = decision_log
        self._session_id = session_id
        self._robot = robot
        self._instrument_id = instrument_id
        self._params = {k: str(v) for k, v in params.items()}
        payload = json.dumps(self._params, sort_keys=True, default=str)
        self._config_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    @property
    def enabled(self) -> bool:
        return self._log is not None and self._session_id is not None

    def write(
        self,
        *,
        ts: datetime,
        close: Decimal,
        outcome: Outcome,
        steps: Sequence[TraceStep],
        account: Mapping[str, TraceValue],
        signal: str | None = None,
        signal_reason: str | None = None,
        blocked_by: str | None = None,
        bar: Mapping[str, Decimal] | None = None,
        kind: RecordKind = RecordKind.BAR_DECISION,
    ) -> None:
        if self._log is None or self._session_id is None:
            return
        chain = tuple(steps)
        states: dict[str, Any] = dict(legacy_states(chain))
        record = DecisionRecord(
            bar_end_utc=ts,
            robot=self._robot,
            instrument_id=self._instrument_id,
            close_price=close,
            regime="",
            signal=signal,
            signal_reason=signal_reason,
            indicators=legacy_indicators(chain),
            states=states,
            session_id=self._session_id,
            kind=kind,
            bar=dict(bar or {}),
            account=dict(account),
            steps=chain,
            outcome=outcome.value,
            blocked_by=blocked_by,
            config_hash=self._config_hash,
            params=self._params,
        )
        record = replace(record, narrative=render_narrative(record_to_dict(record)))
        self._log.log(record)


def plan_step(held: Holding, exit_position: bool, wants_entry: bool) -> TraceStep:
    """The position-plan verdict, same shape as `SignalRobot._plan_step`."""
    if exit_position and wants_entry:
        result = "exit_and_enter"
    elif exit_position:
        result = "exit"
    elif wants_entry:
        result = "enter"
    else:
        result = "noop"
    return step(
        Stage.PLAN,
        "position_plan",
        Verdict.PASS,
        result=result,
        values={"holding": held.value, "exit": exit_position, "entry": wants_entry},
    )


def leg_step(result: str, *, leg: str, side: str, qty: Decimal | None, price: Decimal) -> TraceStep:
    """One leg of an entry or exit, as the execution step the narrative renders."""
    return step(
        Stage.EXECUTION,
        "paper_broker",
        Verdict.EMIT,
        result=result,
        values={"leg": leg, "side": side, "qty": qty, "price": price},
    )


def refusal_step(code: str, reason: str, value: object, limit: object) -> tuple[TraceStep, str]:
    """The risk-gate BLOCK step and the structured `blocked_by` label it maps to."""
    label = blocked_by_label(code)
    return (
        step(
            Stage.GATE,
            label,
            Verdict.BLOCK,
            result=reason,
            values={"value": value if isinstance(value, Decimal) else None},
            thresholds={"limit": limit if isinstance(limit, Decimal) else None},
        ),
        label,
    )


def account_marks(
    *,
    holding: Holding,
    equity: Decimal | None,
    day_start: Decimal | None,
    peak: Decimal | None,
    legs_open: int,
) -> dict[str, TraceValue]:
    """The account snapshot in the `decision_trace/1` shape the paper terminal writes."""
    day_loss = (
        (day_start - equity) / day_start * Decimal("100")
        if day_start is not None and equity is not None and day_start > 0
        else None
    )
    drawdown = (
        (peak - equity) / peak * Decimal("100")
        if peak is not None and equity is not None and peak > 0
        else None
    )
    snapshot: dict[str, TraceValue] = {
        "position": holding.value.upper(),
        "equity": equity,
        "day_loss_pct": day_loss,
        "drawdown_pct": drawdown,
        "legs_open": legs_open,
    }
    return {k: v for k, v in snapshot.items() if v is not None}
