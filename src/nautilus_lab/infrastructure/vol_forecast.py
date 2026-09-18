from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Protocol

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.risk_overlay import RiskOverlay
from nautilus_lab.domain.volatility import HarRealizedVolatility, VolModel
from nautilus_lab.infrastructure.egarch_forecast import (
    egarch_forecast_volatility,
    gjr_garch_forecast_volatility,
)


class VolForecaster(Protocol):
    """One-step volatility forecast, fed one closed bar at a time.

    The same shape as `HarRealizedVolatility.update`, so the strategy does not
    care which model it was handed.
    """

    def update(self, bar: OhlcvBar, previous_close: Decimal | None) -> Decimal | None: ...


class HarVolForecaster:
    """HAR-RV, recomputed on every bar. No optional dependency, no fit."""

    def __init__(self) -> None:
        self._model = HarRealizedVolatility()

    def update(self, bar: OhlcvBar, previous_close: Decimal | None) -> Decimal | None:
        return self._model.update(bar, previous_close)


class ArchVolForecaster:
    """EGARCH / GJR-GARCH with an explicit refit cadence.

    A GARCH-family fit is maximum likelihood over the whole window. Doing that on
    every bar would turn a 3000-bar smoke run into hours, so the model is refitted
    once every `refit_every_bars` and the previous forecast is reused in between.

    That cadence is a real modelling trade-off — stale parameters between refits —
    so it is a named, tunable parameter rather than something buried in the
    implementation. Between refits the last forecast is returned, which is exactly
    what the fitted model would predict if its parameters had not moved.

    Returns `None` until `min_observations` returns have accumulated, and keeps
    returning the last good value if a refit fails, so a single non-converging
    window cannot blank out the forecast mid-run.
    """

    def __init__(
        self,
        *,
        model: VolModel,
        refit_every_bars: int = 24,
        min_observations: int = 60,
        window: int = 500,
        forecaster: Callable[[tuple[float, ...]], Decimal | None] | None = None,
    ) -> None:
        if model is VolModel.HAR:
            raise ValueError("ArchVolForecaster does not implement the HAR model")
        if refit_every_bars < 1:
            raise ValueError("refit_every_bars must be >= 1")
        if min_observations < 1:
            raise ValueError("min_observations must be >= 1")
        if window < min_observations:
            raise ValueError("window must be >= min_observations")
        self._model = model
        self._refit_every_bars = refit_every_bars
        self._min_observations = min_observations
        self._window = window
        self._forecaster = forecaster or _default_forecaster(model)
        self._returns: list[float] = []
        self._forecast: Decimal | None = None
        self._bars_since_refit = 0
        self.refit_count = 0

    @property
    def forecast(self) -> Decimal | None:
        return self._forecast

    def update(self, bar: OhlcvBar, previous_close: Decimal | None) -> Decimal | None:
        if previous_close is not None and previous_close > 0:
            self._returns.append(float((bar.close - previous_close) / previous_close))
        if len(self._returns) < self._min_observations:
            return None
        self._bars_since_refit += 1
        if self._forecast is None or self._bars_since_refit >= self._refit_every_bars:
            self._bars_since_refit = 0
            candidate = self._forecaster(tuple(self._returns[-self._window :]))
            if candidate is not None:
                self._forecast = candidate
                self.refit_count += 1
        return self._forecast


def build_vol_forecaster(
    overlay: RiskOverlay,
    *,
    model: VolModel | None = None,
    refit_every_bars: int | None = None,
) -> VolForecaster:
    """Pick the forecaster named by the overlay, defaulting to the config's values."""
    resolved = model if model is not None else overlay.vol_model
    if resolved is VolModel.HAR:
        return HarVolForecaster()
    return ArchVolForecaster(
        model=resolved,
        refit_every_bars=(
            refit_every_bars if refit_every_bars is not None else overlay.vol_refit_every
        ),
    )


def _default_forecaster(model: VolModel) -> Callable[[tuple[float, ...]], Decimal | None]:
    if model is VolModel.EGARCH:
        return egarch_forecast_volatility
    if model is VolModel.GJR_GARCH:
        return gjr_garch_forecast_volatility
    raise ValueError(f"no arch-backed forecaster for model {model!r}")
