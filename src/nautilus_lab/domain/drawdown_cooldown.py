"""Let a tripped drawdown breaker recover after a cool-down, instead of never.

The max-drawdown breaker compares equity with the all-time peak. Once it trips, only a
new peak can lift it — and a robot that may not enter cannot make one. In a long
out-of-sample window that turns the run into a measurement of the breaker: the first
6% hole ends all trading and everything after it is flat by construction.

With a cool-down of N days the peak is re-based to current equity once entries have
been blocked for N days. The breaker still stops the bleeding when it trips; it just
does not stay tripped for the rest of history. `0` keeps the permanent behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

DRAWDOWN_REASON = "max drawdown circuit breaker"


@dataclass(frozen=True, slots=True)
class PeakState:
    peak: Decimal
    blocked_since: datetime | None = None


def on_refusal(state: PeakState, *, reason: str, now: datetime) -> PeakState:
    """Start the cool-down clock the first time the drawdown breaker refuses."""
    if reason != DRAWDOWN_REASON or state.blocked_since is not None:
        return state
    return PeakState(peak=state.peak, blocked_since=now)


def advance(state: PeakState, *, equity: Decimal, now: datetime, cooldown_days: int) -> PeakState:
    """New peak on a new high; re-based peak once the cool-down has run out."""
    if equity > state.peak:
        return PeakState(peak=equity, blocked_since=None)
    if (
        cooldown_days > 0
        and state.blocked_since is not None
        and now - state.blocked_since >= timedelta(days=cooldown_days)
    ):
        return PeakState(peak=equity, blocked_since=None)
    return state
