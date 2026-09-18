from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal


def empirical_quantile(values: tuple[Decimal, ...], probability: Decimal) -> Decimal:
    """Linear-interpolated empirical quantile of `values` at `probability`.

    Uses the standard "type 7" definition (the one numpy defaults to):
    ``h = (n - 1) * p``, then interpolate between the two neighbouring order
    statistics.

    Chosen deliberately over the nearest-rank convention that `historical_var`
    uses in `domain/portfolio_risk.py`: VaR wants its bucket to contain at least
    one observation, which is a tail-safety property. An entry threshold wants
    the opposite trade-off — the quantile should sit where the distribution
    actually puts it, so that a single extreme spread observation cannot move the
    gate by a whole data point and silently redefine the signal.

    Pure `Decimal`, like the rest of `domain/`: no numpy, no floats.
    """
    if not values:
        raise ValueError("need at least one observation")
    if probability <= 0 or probability >= 1:
        raise ValueError("probability must be in (0, 1)")

    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]

    position = Decimal(len(ordered) - 1) * probability
    lower_index = int(position.to_integral_value(rounding=ROUND_FLOOR))
    upper_index = int(position.to_integral_value(rounding=ROUND_CEILING))
    if lower_index == upper_index:
        return ordered[lower_index]

    lower = ordered[lower_index]
    upper = ordered[upper_index]
    weight = position - Decimal(lower_index)
    return lower + (upper - lower) * weight
