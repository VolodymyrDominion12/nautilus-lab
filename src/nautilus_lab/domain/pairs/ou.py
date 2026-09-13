from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import log


@dataclass(frozen=True, slots=True)
class OuFit:
    mean: Decimal
    kappa: Decimal
    half_life_bars: Decimal
    sigma: Decimal


def fit_ou_half_life(spread: tuple[Decimal, ...]) -> OuFit:
    """Discrete OU fit: delta S = kappa*(mu - S) + noise."""
    if len(spread) < 30:
        raise ValueError("need at least 30 spread observations")
    mean = sum(spread, Decimal("0")) / Decimal(len(spread))
    deltas = tuple(spread[index] - spread[index - 1] for index in range(1, len(spread)))
    lagged = tuple(mean - spread[index - 1] for index in range(1, len(spread)))
    kappa, _ = _ols_beta_alpha(deltas, lagged)
    if kappa <= 0:
        kappa = Decimal("0.0001")
    half_life = Decimal(str(log(2))) / kappa
    residuals = tuple(delta - kappa * lag for delta, lag in zip(deltas, lagged, strict=True))
    sigma = _std(residuals)
    return OuFit(mean=mean, kappa=kappa, half_life_bars=half_life, sigma=sigma)


def z_score(value: Decimal, mean: Decimal, std: Decimal) -> Decimal:
    if std <= 0:
        return Decimal("0")
    return (value - mean) / std


def _ols_beta_alpha(y: tuple[Decimal, ...], x: tuple[Decimal, ...]) -> tuple[Decimal, Decimal]:
    n = Decimal(len(x))
    mean_x = sum(x, Decimal("0")) / n
    mean_y = sum(y, Decimal("0")) / n
    cov = sum((item_x - mean_x) * (item_y - mean_y) for item_x, item_y in zip(x, y, strict=True))
    var_x = sum((item_x - mean_x) ** 2 for item_x in x)
    if var_x == 0:
        return Decimal("0"), mean_y
    beta = cov / var_x
    alpha = mean_y - beta * mean_x
    return beta, alpha


def _std(values: tuple[Decimal, ...]) -> Decimal:
    n = Decimal(len(values))
    if n < 2:
        return Decimal("0")
    mean = sum(values, Decimal("0")) / n
    variance = sum((item - mean) ** 2 for item in values) / (n - Decimal("1"))
    return variance.sqrt()
