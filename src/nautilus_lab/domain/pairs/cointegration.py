from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CointegrationResult:
    hedge_ratio: Decimal
    intercept: Decimal
    adf_statistic: Decimal
    adf_pvalue: Decimal
    residual_std: Decimal


def fit_cointegration(
    y: tuple[Decimal, ...],
    x: tuple[Decimal, ...],
) -> CointegrationResult:
    """OLS hedge ratio y ~ alpha + beta*x, then ADF on residuals (simplified)."""
    if len(y) != len(x) or len(y) < 30:
        raise ValueError("need at least 30 aligned observations")
    beta, alpha = _ols_beta_alpha(y, x)
    residuals = tuple(item_y - alpha - beta * item_x for item_y, item_x in zip(y, x, strict=True))
    adf_stat, adf_p = _adf_test(residuals)
    std = _std(residuals)
    return CointegrationResult(
        hedge_ratio=beta,
        intercept=alpha,
        adf_statistic=adf_stat,
        adf_pvalue=adf_p,
        residual_std=std,
    )


def _ols_beta_alpha(y: tuple[Decimal, ...], x: tuple[Decimal, ...]) -> tuple[Decimal, Decimal]:
    n = Decimal(len(x))
    mean_x = sum(x, Decimal("0")) / n
    mean_y = sum(y, Decimal("0")) / n
    cov = sum((item_x - mean_x) * (item_y - mean_y) for item_x, item_y in zip(x, y, strict=True))
    var_x = sum((item_x - mean_x) ** 2 for item_x in x)
    if var_x == 0:
        raise ValueError("x has zero variance")
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


def _adf_test(residuals: tuple[Decimal, ...]) -> tuple[Decimal, Decimal]:
    """Augmented Dickey-Fuller without constant on first difference (research-grade simplified)."""
    if len(residuals) < 20:
        return Decimal("0"), Decimal("1")
    diffs = tuple(residuals[index] - residuals[index - 1] for index in range(1, len(residuals)))
    lagged = residuals[:-1]
    beta, _ = _ols_beta_alpha(diffs, lagged)
    # MacKinnon-style rough p-value bands for crypto research (not production econometrics).
    if beta < Decimal("-3.5"):
        pvalue = Decimal("0.01")
    elif beta < Decimal("-2.9"):
        pvalue = Decimal("0.05")
    elif beta < Decimal("-2.0"):
        pvalue = Decimal("0.10")
    else:
        pvalue = Decimal("0.50")
    return beta, pvalue
