from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from nautilus_lab.application.alpha.operators import (
    cs_mean,
    cs_rank,
    cs_zscore,
    delay,
    lead,
    neutralise,
    pct_change,
    rolling_beta,
    ts_max,
    ts_mean,
    ts_std,
    ts_zscore,
    unit_gross,
)
from nautilus_lab.application.alpha.panel import FloatArray

nan = np.nan


def test_ts_mean_needs_a_complete_window() -> None:
    values = np.array([[1.0], [2.0], [nan], [4.0], [5.0], [6.0]])
    out = ts_mean(values, 2)
    assert np.isnan(out[0, 0])
    assert out[1, 0] == pytest.approx(1.5)
    assert np.isnan(out[2, 0])
    assert np.isnan(out[3, 0])
    assert out[4, 0] == pytest.approx(4.5)


def test_ts_std_matches_numpy_sample_std() -> None:
    rng = np.random.default_rng(0)
    values = rng.normal(size=(50, 3))
    out = ts_std(values, 10)
    assert out[9] == pytest.approx(values[:10].std(axis=0, ddof=1))
    assert out[-1] == pytest.approx(values[-10:].std(axis=0, ddof=1))


def test_ts_zscore_of_constant_is_nan_not_inf() -> None:
    assert np.isnan(ts_zscore(np.ones((20, 1)), 5)[-1, 0])


def test_ts_max_propagates_unknowns() -> None:
    values = np.array([[1.0], [3.0], [2.0], [nan], [1.0]])
    out = ts_max(values, 2)
    assert out[1, 0] == 3.0
    assert out[2, 0] == 3.0
    assert np.isnan(out[3, 0])
    assert np.isnan(out[4, 0])


def test_delay_lead_and_pct_change_line_up() -> None:
    values = np.arange(1.0, 6.0).reshape(-1, 1)
    assert delay(values, 2)[2, 0] == 1.0
    assert lead(values, 2)[0, 0] == 3.0
    assert np.isnan(lead(values, 2)[-1, 0])
    assert pct_change(values, 1)[1, 0] == pytest.approx(1.0)


def test_signals_never_see_the_future_through_delay() -> None:
    values = np.arange(10.0).reshape(-1, 1)
    shocked = values.copy()
    shocked[7:] += 100.0
    ops: list[Callable[[FloatArray], FloatArray]] = [
        lambda v: ts_mean(v, 3),
        lambda v: delay(v, 1),
        lambda v: pct_change(v, 2),
    ]
    for op in ops:
        np.testing.assert_array_equal(op(values)[:7], op(shocked)[:7])


def test_cs_rank_averages_ties_and_centres_rows() -> None:
    row = np.array([[0.01, 0.01, 0.01, 0.03, -0.02]])
    ranks = cs_rank(row, min_names=5)
    assert ranks[0, 0] == ranks[0, 1] == ranks[0, 2]
    assert ranks[0, 3] == pytest.approx(0.5)
    assert ranks[0, 4] == pytest.approx(-0.5)
    assert np.nansum(ranks) == pytest.approx(0.0)


def test_cs_rank_needs_min_names() -> None:
    row = np.array([[1.0, 2.0, nan, nan, 3.0]])
    assert np.isnan(cs_rank(row, min_names=4)).all()
    out = cs_rank(row, min_names=3)
    assert np.isnan(out[0, 2])
    assert out[0, 4] == pytest.approx(0.5)


def test_cs_mean_and_zscore() -> None:
    row = np.array([[1.0, 2.0, 3.0, nan]])
    assert cs_mean(row, 3)[0] == pytest.approx(2.0)
    assert np.isnan(cs_mean(row, 4)[0])
    z = cs_zscore(row, 3)
    assert z[0, 0] == pytest.approx(-1.0)
    assert np.isnan(z[0, 3])


def test_rolling_beta_recovers_a_known_beta() -> None:
    rng = np.random.default_rng(3)
    market = rng.normal(0, 0.01, 2000)
    returns = np.column_stack([2.0 * market, 0.5 * market + rng.normal(0, 0.001, 2000)])
    beta = rolling_beta(returns, market, window=200)
    assert np.isnan(beta[198]).all()
    assert beta[-1, 0] == pytest.approx(2.0, abs=1e-9)
    assert beta[-1, 1] == pytest.approx(0.5, abs=0.05)


def test_neutralise_removes_dollar_and_beta_exposure() -> None:
    rng = np.random.default_rng(5)
    weights = rng.normal(size=(4, 7))
    betas = rng.uniform(0.5, 1.8, size=(4, 7))
    out = neutralise(weights, betas)
    assert np.abs(out.sum(axis=1)).max() < 1e-12
    assert np.abs((out * betas).sum(axis=1)).max() < 1e-12


def test_neutralise_falls_back_to_dollar_neutral_when_betas_are_equal() -> None:
    out = neutralise(np.array([[1.0, 2.0, 3.0]]), np.ones((1, 3)))
    np.testing.assert_allclose(out, [[-1.0, 0.0, 1.0]])


def test_unit_gross_scales_rows() -> None:
    out = unit_gross(np.array([[1.0, -3.0], [0.0, 0.0]]))
    np.testing.assert_allclose(out, [[0.25, -0.75], [0.0, 0.0]])
