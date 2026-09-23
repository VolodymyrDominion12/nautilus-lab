from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_lab.domain.drawdown_cooldown import (
    DRAWDOWN_REASON,
    PeakState,
    advance,
    on_refusal,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_peak_follows_new_highs() -> None:
    state = advance(PeakState(peak=Decimal("100")), equity=Decimal("110"), now=T0, cooldown_days=3)
    assert state.peak == Decimal("110")


def test_without_cooldown_the_breaker_never_lifts() -> None:
    state = on_refusal(PeakState(peak=Decimal("100")), reason=DRAWDOWN_REASON, now=T0)
    later = advance(state, equity=Decimal("90"), now=T0 + timedelta(days=365), cooldown_days=0)
    assert later.peak == Decimal("100")


def test_cooldown_rebases_the_peak_after_n_days_of_refusals() -> None:
    state = on_refusal(PeakState(peak=Decimal("100")), reason=DRAWDOWN_REASON, now=T0)
    early = advance(state, equity=Decimal("90"), now=T0 + timedelta(days=2), cooldown_days=3)
    assert early.peak == Decimal("100")
    due = advance(state, equity=Decimal("90"), now=T0 + timedelta(days=3), cooldown_days=3)
    assert due == PeakState(peak=Decimal("90"), blocked_since=None)


def test_only_the_drawdown_breaker_starts_the_clock() -> None:
    state = on_refusal(PeakState(peak=Decimal("100")), reason="daily loss circuit breaker", now=T0)
    assert state.blocked_since is None
    first = on_refusal(state, reason=DRAWDOWN_REASON, now=T0)
    again = on_refusal(first, reason=DRAWDOWN_REASON, now=T0 + timedelta(days=1))
    assert again.blocked_since == T0
