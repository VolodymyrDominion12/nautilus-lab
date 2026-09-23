"""What a signal means for the position we already hold — before any risk gate runs.

The risk layer guards *new exposure*. It must never be able to keep an old one alive.
Before this module existed the Nautilus adapters asked `evaluate_entry` first and
returned on a refusal, so an opposite signal that should have closed a position was
dropped together with the entry it would have opened. On an always-in-market robot
(ema) that froze a losing short for weeks once the drawdown breaker had tripped:
946 refusals in one paper session, the position open to the last bar.

Splitting the decision in two makes the rule explicit and testable without an engine:

* `exit_position` — the signal disagrees with what we hold. This never depends on risk.
* `wants_entry` — the signal asks for new exposure. Only this goes through the gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from nautilus_lab.domain.signals import SignalSide


class Holding(StrEnum):
    FLAT = "flat"
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True, slots=True)
class PositionPlan:
    exit_position: bool
    wants_entry: bool

    @property
    def is_noop(self) -> bool:
        return not self.exit_position and not self.wants_entry


def holding_from_signed_qty(signed_qty: Decimal) -> Holding:
    if signed_qty > 0:
        return Holding.LONG
    if signed_qty < 0:
        return Holding.SHORT
    return Holding.FLAT


def plan_for_signal(held: Holding, desired: SignalSide) -> PositionPlan:
    """Exit/entry intent for one signal. Risk, sizing and order state are the caller's job.

    | held  | desired | exit | entry |
    |-------|---------|------|-------|
    | any   | FLAT    | held != FLAT | no |
    | FLAT  | BUY/SELL| no   | yes   |
    | LONG  | BUY     | no   | no    |
    | LONG  | SELL    | yes  | yes   |
    | SHORT | SELL    | no   | no    |
    | SHORT | BUY     | yes  | yes   |
    """
    if desired is SignalSide.FLAT:
        return PositionPlan(exit_position=held is not Holding.FLAT, wants_entry=False)
    target = Holding.LONG if desired is SignalSide.BUY else Holding.SHORT
    if held is target:
        return PositionPlan(exit_position=False, wants_entry=False)
    return PositionPlan(exit_position=held is not Holding.FLAT, wants_entry=True)
