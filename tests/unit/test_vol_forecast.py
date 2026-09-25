"""The `VOL_MODEL` selector: HAR stays the default, arch models are opt-in.

Two separate concerns are pinned here:

* **Wiring.** The right forecaster is chosen, the refit cadence is honoured, and a
  GJR fit really does ask for the asymmetry term (`o=1`) rather than silently
  running a symmetric GARCH under a different name.
* **Degradation.** No `arch` extra, not enough history, or a refit that fails must
  all yield "no forecast", never a dead backtest.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import InvalidRiskError
from nautilus_lab.domain.risk_overlay import RiskOverlay
from nautilus_lab.domain.volatility import VolModel
from nautilus_lab.infrastructure.egarch_forecast import (
    egarch_forecast_volatility,
    gjr_garch_forecast_volatility,
)
from nautilus_lab.infrastructure.vol_forecast import (
    ArchVolForecaster,
    HarVolForecaster,
    build_vol_forecaster,
)

_START = datetime(2024, 1, 1, tzinfo=UTC)


def test_har_is_the_default_and_needs_no_extra() -> None:
    forecaster = build_vol_forecaster(RiskOverlay(use_vol_scaling=True))
    assert isinstance(forecaster, HarVolForecaster)


@pytest.mark.parametrize("model", [VolModel.EGARCH, VolModel.GJR_GARCH])
def test_arch_models_build_the_arch_forecaster(model: VolModel) -> None:
    forecaster = build_vol_forecaster(RiskOverlay(vol_model=model))
    assert isinstance(forecaster, ArchVolForecaster)


def test_explicit_model_argument_overrides_the_overlay() -> None:
    forecaster = build_vol_forecaster(RiskOverlay(vol_model=VolModel.HAR), model=VolModel.GJR_GARCH)
    assert isinstance(forecaster, ArchVolForecaster)


def test_arch_forecaster_stays_silent_until_it_has_enough_history() -> None:
    forecaster = ArchVolForecaster(model=VolModel.GJR_GARCH, min_observations=5)
    forecasts = [forecaster.update(_bar(index), _close(index - 1)) for index in range(1, 5)]
    assert forecasts == [None, None, None, None]
    assert forecaster.refit_count == 0


def test_arch_forecaster_refits_on_the_configured_cadence() -> None:
    calls: list[tuple[float, ...]] = []

    def _stub(returns: tuple[float, ...]) -> Decimal:
        calls.append(returns)
        return Decimal("0.01")

    forecaster = ArchVolForecaster(
        model=VolModel.GJR_GARCH,
        refit_every_bars=10,
        min_observations=2,
        window=50,
        forecaster=_stub,
    )
    # 20 bars: the first observation yields no return, so 19 returns accumulate.
    for index in range(1, 21):
        forecaster.update(_bar(index), _close(index - 1))

    # First forecast as soon as history allows, then one refit per 10 bars.
    assert forecaster.refit_count == 2
    assert len(calls) == 2


def test_arch_forecaster_reuses_the_last_forecast_between_refits() -> None:
    values = iter([Decimal("0.01"), Decimal("0.09")])

    forecaster = ArchVolForecaster(
        model=VolModel.EGARCH,
        refit_every_bars=5,
        min_observations=2,
        forecaster=lambda _returns: next(values, Decimal("0.09")),
    )
    seen: list[Decimal | None] = [
        forecaster.update(_bar(index), _close(index - 1)) for index in range(1, 9)
    ]

    # `seen[0]` is the warm-up bar: no observation has been accumulated yet.
    assert seen[0] is None
    # The forecast is sticky inside a cadence window and steps at the refit.
    assert seen[1] == Decimal("0.01")
    assert seen[2] == Decimal("0.01")
    assert Decimal("0.09") in seen[2:]


def test_a_failed_refit_keeps_the_previous_forecast() -> None:
    """A non-converging window must not blank the forecast for the rest of the run."""
    results = iter([Decimal("0.01"), None, None])

    forecaster = ArchVolForecaster(
        model=VolModel.GJR_GARCH,
        refit_every_bars=2,
        min_observations=2,
        forecaster=lambda _returns: next(results, None),
    )
    seen: list[Decimal | None] = [
        forecaster.update(_bar(index), _close(index - 1)) for index in range(1, 9)
    ]

    assert seen[0] is None  # warm-up bar, no observation accumulated yet
    assert all(value == Decimal("0.01") for value in seen[1:])
    # Only the successful fit counts; the two failures did not overwrite it.
    assert forecaster.refit_count == 1


def test_arch_forecaster_rejects_the_har_model_and_a_bad_cadence() -> None:
    with pytest.raises(ValueError, match="does not implement the HAR model"):
        ArchVolForecaster(model=VolModel.HAR)
    with pytest.raises(ValueError, match="refit_every_bars"):
        ArchVolForecaster(model=VolModel.GJR_GARCH, refit_every_bars=0)
    with pytest.raises(ValueError, match="window must be"):
        ArchVolForecaster(model=VolModel.GJR_GARCH, min_observations=10, window=5)


def test_gjr_asks_for_the_asymmetry_term_and_egarch_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`o=1` is what makes GJR asymmetric. Capture the real call, do not assume it."""
    captured: list[dict[str, Any]] = []

    class _Fit:
        def forecast(self, horizon: int) -> Any:
            return SimpleNamespace(variance=SimpleNamespace(values=[[0.0004]]))

    class _Model:
        def fit(self, disp: str) -> _Fit:
            return _Fit()

    def _arch_model(_data: Any, **kwargs: Any) -> _Model:
        captured.append(kwargs)
        return _Model()

    monkeypatch.setattr("arch.arch_model", _arch_model)

    returns = tuple([0.001, -0.002] * 40)
    assert gjr_garch_forecast_volatility(returns) == Decimal("0.02")
    assert captured[-1]["vol"] == "GARCH"
    assert captured[-1]["o"] == 1
    assert captured[-1]["p"] == 1
    assert captured[-1]["q"] == 1

    assert egarch_forecast_volatility(returns) == Decimal("0.02")
    assert captured[-1]["vol"] == "EGARCH"
    # EGARCH carries its asymmetry in its own variance equation, so GJR's extra
    # term must stay switched off for it.
    assert captured[-1]["o"] == 0


@pytest.mark.parametrize("forecast", [egarch_forecast_volatility, gjr_garch_forecast_volatility])
def test_arch_models_return_none_without_enough_history(forecast: Any) -> None:
    assert forecast((0.01, -0.01)) is None


def test_gjr_estimates_a_positive_asymmetry_term_on_a_leverage_series() -> None:
    """The economic claim behind GJR, checked against a real fit.

    The series is simulated with a leverage effect — a negative shock raises the
    next variance by `gamma` more than a positive one of the same size. If GJR
    really models that, the fitted asymmetry parameter must come out positive.
    """
    arch = pytest.importorskip("arch")
    np = pytest.importorskip("numpy")

    returns = _simulate_leverage_returns(np, size=600, seed=11)
    fit = arch.arch_model(np.asarray(returns), vol="GARCH", p=1, o=1, q=1, rescale=False).fit(
        disp="off"
    )
    gamma = float(fit.params["gamma[1]"])
    assert gamma > 0, "GJR did not detect the leverage effect it exists to model"


def test_risk_overlay_rejects_a_zero_refit_cadence() -> None:
    with pytest.raises(InvalidRiskError, match="vol_refit_every"):
        RiskOverlay(vol_refit_every=0)


def test_settings_defaults_to_har(monkeypatch: pytest.MonkeyPatch) -> None:
    from nautilus_lab.infrastructure.settings import Settings

    monkeypatch.delenv("VOL_MODEL", raising=False)
    overlay = Settings().risk_overlay()
    assert overlay.vol_model is VolModel.HAR
    assert overlay.vol_refit_every == 24


def test_settings_parses_the_model_and_cadence(monkeypatch: pytest.MonkeyPatch) -> None:
    from nautilus_lab.infrastructure.settings import Settings

    monkeypatch.setenv("VOL_MODEL", "gjr_garch")
    monkeypatch.setenv("VOL_REFIT_EVERY", "48")
    overlay = Settings().risk_overlay()
    assert overlay.vol_model is VolModel.GJR_GARCH
    assert overlay.vol_refit_every == 48


def _close(index: int) -> Decimal:
    """A deterministic, gently varying price path — no randomness needed here."""
    return Decimal("100") + Decimal(index % 7) / Decimal("10")


def _bar(index: int) -> OhlcvBar:
    close = _close(index)
    return OhlcvBar(
        instrument_id="ETH/USDT.SIM",
        ts_utc=_START + timedelta(hours=index),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=Decimal("1"),
    )


def _simulate_leverage_returns(np: Any, *, size: int, seed: int) -> list[float]:
    """GARCH(1,1) with a leverage term: negative shocks scale variance more."""
    rng = np.random.default_rng(seed)
    omega, alpha, gamma, beta = 2e-6, 0.02, 0.14, 0.9
    shocks = rng.standard_normal(size)
    returns = np.zeros(size)
    variance = np.zeros(size)
    variance[0] = omega / max(1.0 - alpha - beta - gamma / 2.0, 1e-6)
    for index in range(1, size):
        previous = returns[index - 1]
        leverage = gamma if previous < 0 else 0.0
        variance[index] = omega + (alpha + leverage) * previous**2 + beta * variance[index - 1]
        returns[index] = float(np.sqrt(variance[index]) * shocks[index])
    return [float(item) for item in returns]
