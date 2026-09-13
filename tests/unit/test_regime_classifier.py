from decimal import Decimal

import pytest

from nautilus_lab.domain.errors import InvalidRiskError
from nautilus_lab.domain.regime import MarketRegime, RegimeClassifier, RegimeParams


def _params() -> RegimeParams:
    return RegimeParams(
        er_period=5,
        trend_ema_period=5,
        slope_lookback=3,
        enter_trend_er=Decimal("0.40"),
        exit_trend_er=Decimal("0.20"),
        donchian_period=3,
        bb_period=5,
        bb_k=Decimal("1.5"),
    )


def test_monotonic_rise_is_uptrend() -> None:
    classifier = RegimeClassifier(_params())
    snapshot = None
    for index in range(1, 25):
        snapshot = classifier.update(Decimal(100 + index))

    assert snapshot is not None
    assert snapshot.regime is MarketRegime.UPTREND
    assert snapshot.efficiency_ratio > Decimal("0.40")
    assert snapshot.slope > 0


def test_monotonic_fall_is_downtrend() -> None:
    classifier = RegimeClassifier(_params())
    snapshot = None
    for index in range(25):
        snapshot = classifier.update(Decimal(200 - index))

    assert snapshot is not None
    assert snapshot.regime is MarketRegime.DOWNTREND
    assert snapshot.slope < 0


def test_alternating_closes_are_range() -> None:
    classifier = RegimeClassifier(_params())
    snapshot = None
    for index in range(30):
        close = Decimal("100") if index % 2 == 0 else Decimal("101")
        snapshot = classifier.update(close)

    assert snapshot is not None
    assert snapshot.regime is MarketRegime.RANGE
    assert snapshot.efficiency_ratio < Decimal("0.40")


def test_invalid_regime_params_are_rejected() -> None:
    with pytest.raises(InvalidRiskError, match="enter_trend_er"):
        RegimeParams(enter_trend_er=Decimal("0.10"), exit_trend_er=Decimal("0.20"))


def test_classifier_does_not_look_ahead() -> None:
    params = _params()

    def regimes(count: int) -> list[MarketRegime]:
        classifier = RegimeClassifier(params)
        seen: list[MarketRegime] = []
        prices = [Decimal(100 + index) for index in range(count)]
        if count > 20:
            prices[-1] = Decimal("1")
        for price in prices:
            snapshot = classifier.update(price)
            if snapshot is not None:
                seen.append(snapshot.regime)
        return seen

    prefix = regimes(18)
    with_future = regimes(19)[: len(prefix)]

    assert prefix == with_future
