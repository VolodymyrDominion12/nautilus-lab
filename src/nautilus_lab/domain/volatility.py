from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from nautilus_lab.domain.bars import OhlcvBar


class VolModel(StrEnum):
    """Which volatility forecaster feeds `use_vol_scaling`.

    `HAR` is the default because it is the only one with no optional dependency
    and it is the model every already-documented vol-scaled run used. The two
    `arch`-backed models are opt-in: they need the `research` extra, and they fit
    by maximum likelihood, which is far too slow to redo on every bar — see the
    refit cadence in `infrastructure/vol_forecast.py`.
    """

    HAR = "har"
    EGARCH = "egarch"
    GJR_GARCH = "gjr_garch"


class HarRealizedVolatility:
    """HAR-RV style realized volatility from bar returns."""

    def __init__(
        self,
        *,
        daily_bars: int = 24,
        weekly_bars: int = 24 * 7,
        monthly_bars: int = 24 * 30,
    ) -> None:
        self._daily = daily_bars
        self._weekly = weekly_bars
        self._monthly = monthly_bars
        self._returns: list[Decimal] = []
        self._forecast: Decimal | None = None

    @property
    def forecast(self) -> Decimal | None:
        return self._forecast

    def update(self, bar: OhlcvBar, previous_close: Decimal | None) -> Decimal | None:
        if previous_close is not None and previous_close > 0:
            ret = (bar.close - previous_close) / previous_close
            self._returns.append(ret)
        if len(self._returns) < self._daily:
            return None
        rv_d = _realized_vol(self._returns[-self._daily :])
        rv_w = (
            _realized_vol(self._returns[-self._weekly :])
            if len(self._returns) >= self._weekly
            else rv_d
        )
        rv_m = (
            _realized_vol(self._returns[-self._monthly :])
            if len(self._returns) >= self._monthly
            else rv_w
        )
        self._forecast = Decimal("0.4") * rv_d + Decimal("0.35") * rv_w + Decimal("0.25") * rv_m
        return self._forecast


def vol_scaled_risk_fraction(base: Decimal, forecast_vol: Decimal, target_vol: Decimal) -> Decimal:
    if forecast_vol <= 0 or target_vol <= 0:
        return base
    scaled = base * (target_vol / forecast_vol)
    return min(base, scaled)


def _realized_vol(returns: list[Decimal]) -> Decimal:
    if len(returns) < 2:
        return Decimal("0")
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = sum((item - mean) ** 2 for item in returns) / Decimal(len(returns) - 1)
    return variance.sqrt()
