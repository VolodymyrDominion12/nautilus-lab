"""Tests for the residual-based cointegration (Engle-Granger) ADF gate.

History: the gate compared the *raw* lagged-level coefficient against hard-coded
bands (``gamma < -2.9`` for the 5% level). For an AR(1) series ``gamma = rho - 1``,
so for any stationary series it is confined to ``(-2, 0)`` and that band was
unreachable. ``pairs`` therefore never traded on any input, and the vacuous
``assert signals >= 0`` in the neighbouring test kept it looking covered. These
tests pin the corrected behaviour.
"""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from nautilus_lab.domain.pairs.cointegration import (
    _adf_test,
    _max_lags,
    critical_values,
    fit_cointegration,
    p_value_from_statistic,
)

_COUNT = 300
_LOOKBACK = 120


def _ar1(phi: float, count: int = _COUNT, seed: int = 1) -> tuple[Decimal, ...]:
    rng = random.Random(seed)
    value = 0.0
    values: list[Decimal] = []
    for _ in range(count):
        value = phi * value + rng.gauss(0.0, 1.0)
        values.append(Decimal(repr(round(value, 10))))
    return tuple(values)


def _random_walk(count: int = _COUNT, seed: int = 2) -> tuple[Decimal, ...]:
    return _ar1(1.0, count, seed)


def _cointegrated_pair(
    *,
    count: int = _COUNT,
    seed: int = 3,
    beta: float = 1.5,
    noise: float = 1.0,
) -> tuple[tuple[Decimal, ...], tuple[Decimal, ...]]:
    """y = 2 + beta * x + white noise, with x a random walk: residuals are stationary."""
    x = _random_walk(count, seed)
    rng = random.Random(seed + 500)
    step = Decimal(repr(beta))
    y = tuple(
        Decimal("2") + step * value + Decimal(repr(round(rng.gauss(0.0, noise), 10))) for value in x
    )
    return y, x


# --- the regression test for the unreachable gate ---------------------------------


def test_cointegrated_pair_passes_the_five_percent_gate() -> None:
    """The gate must be able to open at all.

    Under the old coefficient-based bands this returned p = 0.5 for every input, so
    ``PairsTrading._fit_state`` always returned None and the robot never traded.
    """
    y, x = _cointegrated_pair()
    result = fit_cointegration(y, x)
    assert result.adf_pvalue < Decimal("0.05"), result
    assert result.adf_statistic < critical_values(len(y))[0]


def test_independent_random_walks_fail_the_gate() -> None:
    """Two unrelated random walks must not be declared cointegrated."""
    result = fit_cointegration(_random_walk(seed=11), _random_walk(seed=12))
    assert result.adf_pvalue > Decimal("0.05"), result


def test_statistic_is_a_t_ratio_not_the_raw_coefficient() -> None:
    """Strongly mean-reverting residuals give a statistic far below -2.

    ``gamma = rho - 1`` cannot leave ``(-2, 0)``, so no coefficient-based band below
    -2 could ever be reached. The t-ratio has no such ceiling.
    """
    y, x = _cointegrated_pair(noise=0.1)
    result = fit_cointegration(y, x)
    assert result.adf_statistic < Decimal("-5")


# --- MacKinnon reference values ---------------------------------------------------


def test_critical_values_match_mackinnon_2010() -> None:
    """Reference values come from ``statsmodels`` for N=2 variables, regression "c"."""
    one, five, ten = critical_values(_LOOKBACK)
    assert float(one) == pytest.approx(-3.99003, abs=1e-4)
    assert float(five) == pytest.approx(-3.38752, abs=1e-4)
    assert float(ten) == pytest.approx(-3.07998, abs=1e-4)


def test_critical_values_are_ordered_and_loosen_with_sample_size() -> None:
    one, five, ten = critical_values(_LOOKBACK)
    assert one < five < ten
    assert critical_values(60)[1] < critical_values(600)[1]


def test_p_value_is_exactly_five_percent_at_the_five_percent_point() -> None:
    """The gate compares against this anchor, so it has to be exact."""
    for nobs in (60, _LOOKBACK, 500):
        five = critical_values(nobs)[1]
        assert float(p_value_from_statistic(five, nobs)) == pytest.approx(0.05, abs=1e-9)


def test_p_value_falls_as_the_statistic_falls() -> None:
    """Higher p means *less* evidence against a unit root."""
    strong = p_value_from_statistic(Decimal("-6"), _LOOKBACK)
    weak = p_value_from_statistic(Decimal("-1"), _LOOKBACK)
    assert strong < weak
    assert strong < Decimal("0.05") <= weak


# --- pinning to the reference implementation ---------------------------------------


@pytest.mark.filterwarnings("ignore::FutureWarning")
def test_matches_the_statsmodels_reference_implementation() -> None:
    """Lock the statistic and the lag choice to statsmodels, the reference that exposed
    both original bugs: the unreachable coefficient bands and the wrong N.

    statsmodels is a test-time reference only — the domain keeps its own ``Decimal``
    implementation and never imports it at runtime, so this skips when the `research`
    extra is absent. Without this test the manual cross-check that justified the rewrite
    would have to be redone by hand after every change.
    """
    stattools = pytest.importorskip("statsmodels.tsa.stattools")

    for phi in (0.5, 0.9, 0.99, 1.0):
        series = [float(value) for value in _ar1(phi, count=240, seed=int(phi * 100))]
        reference = stattools.adfuller(
            series,
            maxlag=_max_lags(len(series)),
            regression="n",
            autolag="bic",
        )
        statistic, _, lags = _adf_test(tuple(Decimal(repr(value)) for value in series))

        assert lags == reference[2], f"lag choice diverged at phi={phi}"
        assert float(statistic) == pytest.approx(float(reference[0]), abs=1e-9)


@pytest.mark.filterwarnings("ignore::FutureWarning")
def test_end_to_end_fit_matches_statsmodels_coint() -> None:
    """``coint`` is the canonical Engle-Granger implementation for a bivariate pair."""
    stattools = pytest.importorskip("statsmodels.tsa.stattools")
    y, x = _cointegrated_pair(count=_COUNT, seed=3)

    result = fit_cointegration(y, x)
    reference = stattools.coint(
        [float(value) for value in y],
        [float(value) for value in x],
        trend="c",
        autolag="bic",
    )

    assert float(result.adf_statistic) == pytest.approx(float(reference.coint_t), abs=1e-5)
    assert result.adf_pvalue < Decimal("0.05")


# --- lag selection and input validation -------------------------------------------


def test_white_noise_residuals_select_no_augmentation_lags() -> None:
    """BIC on a common sample must not pad pure noise with lagged differences.

    Choosing each candidate lag on its own shorter sample made BIC fall
    monotonically, so the maximum lag won even on white noise and the test lost power.
    """
    result = fit_cointegration(_cointegrated_pair(noise=1.0)[0], _cointegrated_pair()[1])
    assert result.adf_lags == 0


def test_fit_is_deterministic() -> None:
    y, x = _cointegrated_pair()
    assert fit_cointegration(y, x) == fit_cointegration(y, x)


def test_rejects_short_series() -> None:
    with pytest.raises(ValueError, match="aligned observations"):
        fit_cointegration(_ar1(0.5, 10), _ar1(0.5, 10))


def test_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="aligned observations"):
        fit_cointegration(_ar1(0.5, 60), _ar1(0.5, 61))


def test_rejects_zero_variance_regressor() -> None:
    flat = tuple(Decimal("100") for _ in range(60))
    with pytest.raises(ValueError, match="zero variance"):
        fit_cointegration(_ar1(0.5, 60), flat)
