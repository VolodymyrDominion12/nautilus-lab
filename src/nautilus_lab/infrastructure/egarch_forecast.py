from __future__ import annotations

from decimal import Decimal
from typing import Literal

# The `vol` values the `arch` package accepts, mirroring its own stub. Naming the
# set here means a typo is a type error at the call site instead of a fit that
# silently runs a different model under the name we asked for.
ArchVolKind = Literal["GARCH", "ARCH", "EGARCH", "FIGARCH", "APARCH", "HARCH"]


def egarch_forecast_volatility(returns: tuple[float, ...]) -> Decimal | None:
    """Optional EGARCH(1,1) forecast via arch package. Returns None if unavailable."""
    return _arch_forecast_volatility(returns, vol="EGARCH", p=1, q=1)


def gjr_garch_forecast_volatility(returns: tuple[float, ...]) -> Decimal | None:
    """Optional GJR-GARCH(1,1,1) forecast via arch. Returns None if unavailable.

    GJR adds the asymmetry term (`o=1`) that plain GARCH lacks: a negative shock
    raises the next conditional variance more than a positive shock of the same
    size. That leverage effect is the reason GJR is a separate model rather than a
    reparameterisation of `egarch_forecast_volatility`, and the reason it is worth
    offering in a market whose drawdowns cluster while its rallies do not.

    Like its EGARCH sibling this returns `None` rather than raising when the
    `arch` extra is absent, so a run configured for an unavailable model degrades
    to "no vol forecast" instead of dying mid-backtest.
    """
    return _arch_forecast_volatility(returns, vol="GARCH", p=1, o=1, q=1)


def _arch_forecast_volatility(
    returns: tuple[float, ...],
    *,
    vol: ArchVolKind,
    p: int,
    q: int,
    o: int = 0,
    min_observations: int = 60,
) -> Decimal | None:
    """Shared MLE fit plus a one-step-ahead variance forecast, as a volatility.

    The specification is passed through as explicit typed arguments rather than
    `**kwargs`, so which model is being fitted is visible at each call site — the
    GJR asymmetry term is the whole difference between the two public functions
    and it should not be possible to miss it.

    `rescale=False` is deliberate and shared with the original EGARCH path: the
    package's automatic rescaling would silently change the units of the result,
    and callers compare the forecast against `vol_scaling_target`, which is a
    return-space number. One unit system, stated once.
    """
    if len(returns) < min_observations:
        return None
    try:
        import numpy as np
        from arch import arch_model
    except ImportError:
        return None
    try:
        model = arch_model(
            np.asarray(returns, dtype=np.float64),
            vol=vol,
            p=p,
            o=o,
            q=q,
            rescale=False,
        )
        fit = model.fit(disp="off")
        variance = float(fit.forecast(horizon=1).variance.values[-1][0])
    except (ValueError, ArithmeticError, IndexError, TypeError):
        # A degenerate or non-converging window must not kill the run: "no
        # forecast" is a valid answer here, a crash is not.
        return None
    if variance <= 0:
        return None
    return Decimal(str(variance**0.5))
