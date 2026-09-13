from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from nautilus_lab.domain.ema import ExponentialMovingAverage
from nautilus_lab.domain.errors import InvalidRiskError, RobotNotWiredError
from nautilus_lab.domain.windows import RollingWindow


class MarketRegime(StrEnum):
    UPTREND = "uptrend"
    DOWNTREND = "downtrend"
    RANGE = "range"


class RobotName(StrEnum):
    REGIME = "regime"
    EMA = "ema"
    PAIRS = "pairs"
    FUNDING = "funding"
    ML_OBI = "ml_obi"
    GLFT = "glft"
    TRI_SCAN = "tri_scan"


# Robots with a real execution adapter in the backtest engine. The others exist only
# as domain building blocks, so they must fail closed instead of silently running
# a different strategy (see docs/08-mft-2026-vidpovidnist.md).
BACKTEST_WIRED_ROBOTS: frozenset[RobotName] = frozenset(
    {RobotName.REGIME, RobotName.EMA, RobotName.PAIRS}
)


def require_backtest_support(robot: RobotName) -> None:
    """Reject robots that have no backtest adapter yet."""
    if robot not in BACKTEST_WIRED_ROBOTS:
        wired = ", ".join(sorted(item.value for item in BACKTEST_WIRED_ROBOTS))
        raise RobotNotWiredError(
            f"robot {robot.value!r} has no backtest adapter yet; use one of: {wired}. "
            "Its module is a domain building block only and is not wired to the engine."
        )


@dataclass(frozen=True, slots=True)
class RegimeParams:
    """Kaufman ER + EMA slope with hysteresis. All windows use closed bars."""

    er_period: int = 20
    trend_ema_period: int = 40
    slope_lookback: int = 10
    enter_trend_er: Decimal = Decimal("0.30")
    exit_trend_er: Decimal = Decimal("0.20")
    donchian_period: int = 20
    bb_period: int = 20
    bb_k: Decimal = Decimal("2")

    def __post_init__(self) -> None:
        if self.er_period < 2:
            raise InvalidRiskError("er_period must be >= 2")
        if self.trend_ema_period < 2:
            raise InvalidRiskError("trend_ema_period must be >= 2")
        if self.slope_lookback < 1:
            raise InvalidRiskError("slope_lookback must be >= 1")
        if self.donchian_period < 2:
            raise InvalidRiskError("donchian_period must be >= 2")
        if self.bb_period < 2:
            raise InvalidRiskError("bb_period must be >= 2")
        if self.bb_k <= 0:
            raise InvalidRiskError("bb_k must be > 0")
        if self.enter_trend_er <= self.exit_trend_er:
            raise InvalidRiskError("enter_trend_er must be > exit_trend_er")
        if self.enter_trend_er > 1 or self.exit_trend_er < 0:
            raise InvalidRiskError("ER thresholds must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class RegimeSnapshot:
    regime: MarketRegime
    efficiency_ratio: Decimal
    slope: Decimal


class RegimeClassifier:
    """Trend vs range from Kaufman efficiency ratio and EMA slope. No look-ahead."""

    def __init__(self, params: RegimeParams) -> None:
        self._params = params
        self._closes = RollingWindow(params.er_period + 1)
        self._ema = ExponentialMovingAverage(params.trend_ema_period)
        self._ema_history = RollingWindow(params.slope_lookback + 1)
        self._regime: MarketRegime = MarketRegime.RANGE

    @property
    def initialized(self) -> bool:
        return self._closes.full and self._ema.initialized and self._ema_history.full

    @property
    def regime(self) -> MarketRegime | None:
        if not self.initialized:
            return None
        return self._regime

    def update(self, close: Decimal) -> RegimeSnapshot | None:
        self._ema.update(close)
        ema_value = self._ema.value
        if ema_value is not None:
            self._ema_history.push(ema_value)
        self._closes.push(close)
        if not self.initialized:
            return None
        er = _efficiency_ratio(self._closes.values())
        slope = _slope(self._ema_history.values())
        self._regime = self._next_regime(er, slope)
        return RegimeSnapshot(regime=self._regime, efficiency_ratio=er, slope=slope)

    def _next_regime(self, er: Decimal, slope: Decimal) -> MarketRegime:
        trending = (
            er >= self._params.enter_trend_er
            if self._regime is MarketRegime.RANGE
            else er > self._params.exit_trend_er
        )
        if not trending or slope == 0:
            return MarketRegime.RANGE
        if slope > 0:
            return MarketRegime.UPTREND
        return MarketRegime.DOWNTREND


def _efficiency_ratio(closes: tuple[Decimal, ...]) -> Decimal:
    if len(closes) < 2:
        return Decimal("0")
    net = abs(closes[-1] - closes[0])
    path = sum(
        (abs(closes[index] - closes[index - 1]) for index in range(1, len(closes))), Decimal("0")
    )
    if path == 0:
        return Decimal("0")
    return net / path


def _slope(ema_values: tuple[Decimal, ...]) -> Decimal:
    if len(ema_values) < 2:
        return Decimal("0")
    return ema_values[-1] - ema_values[0]
