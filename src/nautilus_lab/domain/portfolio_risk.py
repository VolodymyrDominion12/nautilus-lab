from __future__ import annotations

from decimal import ROUND_CEILING, Decimal


def fractional_kelly_cap(
    *,
    win_rate: Decimal,
    reward_risk: Decimal,
    fraction: Decimal = Decimal("0.25"),
) -> Decimal:
    """Fractional Kelly as an upper bound on risk fraction. Returns 0 if edge <= 0."""
    if win_rate <= 0 or win_rate >= 1:
        return Decimal("0")
    if reward_risk <= 0:
        return Decimal("0")
    if fraction <= 0 or fraction > 1:
        raise ValueError("fraction must be in (0, 1]")
    lose_rate = Decimal("1") - win_rate
    full_kelly = (win_rate * reward_risk - lose_rate) / reward_risk
    if full_kelly <= 0:
        return Decimal("0")
    return full_kelly * fraction


def historical_var(
    returns: tuple[Decimal, ...],
    *,
    confidence: Decimal = Decimal("0.99"),
) -> Decimal | None:
    """Historical VaR as a positive loss fraction at the given confidence.

    The tail index is the empirical ``1 - confidence`` quantile, taken with a
    ceiling so the bucket always contains at least one observation. Truncating
    instead (``int((1 - confidence) * n)``) skipped the single worst return on a
    100-point sample and returned the *second* worst, understating exactly the loss
    the circuit breaker in ``evaluate_entry`` exists to catch.
    """
    if not returns:
        return None
    if confidence <= 0 or confidence >= 1:
        raise ValueError("confidence must be in (0, 1)")
    sorted_returns = sorted(returns)
    tail = (Decimal("1") - confidence) * Decimal(len(sorted_returns))
    index = int(tail.to_integral_value(rounding=ROUND_CEILING)) - 1
    index = max(0, min(index, len(sorted_returns) - 1))
    worst = sorted_returns[index]
    return -worst if worst < 0 else Decimal("0")


def historical_cvar(
    returns: tuple[Decimal, ...],
    *,
    confidence: Decimal = Decimal("0.99"),
) -> Decimal | None:
    """Historical CVaR (expected shortfall) for losses beyond VaR."""
    if not returns:
        return None
    var = historical_var(returns, confidence=confidence)
    if var is None:
        return None
    tail = tuple(item for item in returns if item <= -var)
    if not tail:
        return var
    mean_tail = sum(tail, Decimal("0")) / Decimal(len(tail))
    return -mean_tail if mean_tail < 0 else Decimal("0")
