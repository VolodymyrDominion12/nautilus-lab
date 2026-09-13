from __future__ import annotations

from decimal import Decimal


def egarch_forecast_volatility(returns: tuple[float, ...]) -> Decimal | None:
    """Optional EGARCH(1,1) forecast via arch package. Returns None if unavailable."""
    if len(returns) < 60:
        return None
    try:
        from arch import arch_model  # type: ignore[import-not-found]
    except ImportError:
        return None
    model = arch_model(list(returns), vol="EGARCH", p=1, q=1, rescale=False)
    fit = model.fit(disp="off")
    forecast = fit.forecast(horizon=1)
    variance = float(forecast.variance.values[-1][0])
    if variance <= 0:
        return None
    return Decimal(str(variance**0.5))
