from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.pairs import (
    HedgeEstimator,
    KalmanHedgeFilter,
    PairsTrading,
    fit_kalman_cointegration,
)
from nautilus_lab.domain.pairs.params import PairsParams
from nautilus_lab.domain.signals import SignalSide
from nautilus_lab.infrastructure.nautilus.synthetic_pairs import synthetic_cointegrated_pair
from nautilus_lab.infrastructure.settings import Settings

_LEG_A = "ETH/USDT.SIM"
_LEG_B = "BTC/USDT.SIM"


def _bar(instrument_id: str, price: Decimal, ts_utc: datetime) -> OhlcvBar:
    spread = max(price * Decimal("0.001"), Decimal("0.01"))
    return OhlcvBar(
        instrument_id=instrument_id,
        ts_utc=ts_utc,
        open=price,
        high=price + spread,
        low=max(price - spread, Decimal("0.01")),
        close=price,
        volume=Decimal("10"),
    )


def _cointegrated_series(
    *,
    count: int,
    x_start: float,
    x_step_sigma: float,
    spread_sigma: float,
    beta_start: float,
    beta_end: float,
    seed: int,
) -> tuple[tuple[Decimal, ...], tuple[Decimal, ...]]:
    rng = random.Random(seed)
    x_vals: list[Decimal] = []
    y_vals: list[Decimal] = []
    x_price = x_start
    spread = 0.0
    for idx in range(count):
        x_price = max(10.0, x_price + rng.gauss(0.0, x_step_sigma))
        beta_t = beta_start + (beta_end - beta_start) * (idx / max(count - 1, 1))
        spread = 0.65 * spread + rng.gauss(0.0, spread_sigma)
        y_price = max(1.0, 20.0 + beta_t * x_price + spread)
        x_vals.append(Decimal(f"{x_price:.4f}"))
        y_vals.append(Decimal(f"{y_price:.4f}"))
    return tuple(y_vals), tuple(x_vals)


def test_kalman_filter_tracks_static_cointegration() -> None:
    y, x = _cointegrated_series(
        count=300,
        x_start=100.0,
        x_step_sigma=1.0,
        spread_sigma=0.4,
        beta_start=1.5,
        beta_end=1.5,
        seed=11,
    )
    result = fit_kalman_cointegration(y, x, delta=Decimal("0.005"))
    assert abs(result.hedge_ratio - Decimal("1.5")) < Decimal("0.15")
    assert result.adf_pvalue <= Decimal("0.05")
    assert result.residual_std > Decimal("0")


def test_kalman_filter_adapts_to_drifting_gold_silver_hedge_ratio() -> None:
    from nautilus_lab.domain.pairs.cointegration import fit_cointegration

    rng = random.Random(21)
    y_vals: list[Decimal] = []
    x_vals: list[Decimal] = []
    spread = 0.0
    for idx in range(500):
        x_price = 30.0 + 4.0 * math.sin(idx / 7.0) + rng.gauss(0.0, 0.5)
        beta_t = 85.0 + 10.0 * min(idx, 250) / 250.0
        spread = 0.65 * spread + rng.gauss(0.0, 1.5)
        y_price = 20.0 + beta_t * x_price + spread
        x_vals.append(Decimal(f"{x_price:.4f}"))
        y_vals.append(Decimal(f"{y_price:.4f}"))

    filt = KalmanHedgeFilter(delta=Decimal("0.02"))
    betas: list[Decimal] = []
    for item_y, item_x in zip(y_vals, x_vals, strict=True):
        step = filt.update(item_y, item_x)
        betas.append(step.beta)

    early_beta = betas[80]
    late_beta = betas[-1]
    assert abs(early_beta - Decimal("86")) < Decimal("3")
    assert abs(late_beta - Decimal("95")) < Decimal("2")
    assert late_beta > early_beta + Decimal("6")

    ols_full = fit_cointegration(tuple(y_vals), tuple(x_vals))
    kal_late = fit_kalman_cointegration(
        tuple(y_vals[-150:]), tuple(x_vals[-150:]), delta=Decimal("0.02")
    )
    assert ols_full.adf_pvalue > Decimal("0.05")
    assert kal_late.adf_pvalue <= Decimal("0.05")


@pytest.mark.parametrize("bad_delta", ["0", "-0.01", "1", "1.5"])
def test_kalman_rejects_invalid_delta(bad_delta: str) -> None:
    value = Decimal(bad_delta)
    with pytest.raises(ValueError, match=r"kalman delta must be in \(0, 1\)"):
        KalmanHedgeFilter(delta=value)
    with pytest.raises(ValueError, match=r"kalman_delta must be in \(0, 1\)"):
        PairsParams(kalman_delta=value)


def test_fit_kalman_cointegration_validates_inputs() -> None:
    short = tuple(Decimal(i) for i in range(20))
    with pytest.raises(ValueError, match="aligned observations"):
        fit_kalman_cointegration(short, short)
    flat_x = tuple(Decimal("10") for _ in range(40))
    moving_y = tuple(Decimal(i + 1) for i in range(40))
    with pytest.raises(ValueError, match="zero variance"):
        fit_kalman_cointegration(moving_y, flat_x)


def test_kalman_independent_random_walks_fail_adf_gate() -> None:
    """Two unrelated random walks must fail ADF even under adaptive Kalman filtering."""
    origin = datetime(2025, 1, 1, tzinfo=UTC)
    for seed_a, seed_b in ((1, 101), (3, 103), (7, 107), (13, 113)):
        rng_a = random.Random(seed_a)
        rng_b = random.Random(seed_b)
        price_a = 2600.0
        price_b = 30.0
        y_series: list[Decimal] = []
        x_series: list[Decimal] = []
        robot = PairsTrading(
            leg_a="XAUUSDT-PERP.SIM",
            leg_b="XAGUSDT-PERP.SIM",
            params=PairsParams(
                leg_a="XAUUSDT-PERP.SIM",
                leg_b="XAGUSDT-PERP.SIM",
                lookback=120,
                z_entry=Decimal("1.5"),
                refit_every_bars=24,
                hedge_estimator=HedgeEstimator.KALMAN,
                kalman_delta=Decimal("0.005"),
            ),
        )
        entries = 0
        for idx in range(250):
            price_a = max(100.0, price_a + rng_a.gauss(0.0, 12.0))
            price_b = max(5.0, price_b + rng_b.gauss(0.0, 0.35))
            d_a = Decimal(f"{price_a:.4f}")
            d_b = Decimal(f"{price_b:.4f}")
            y_series.append(d_a)
            x_series.append(d_b)
            ts = origin + timedelta(hours=idx)
            signal = robot.on_bars(
                _bar("XAUUSDT-PERP.SIM", d_a, ts),
                _bar("XAGUSDT-PERP.SIM", d_b, ts),
            )
            if signal is not None and signal.leg_a.side is not SignalSide.FLAT:
                entries += 1

        coint = fit_kalman_cointegration(tuple(y_series), tuple(x_series), delta=Decimal("0.005"))
        assert coint.adf_pvalue > Decimal("0.05")
        assert entries == 0


def test_pairs_trading_kalman_opens_gate_and_handles_refit_break() -> None:
    data = synthetic_cointegrated_pair(leg_a=_LEG_A, leg_b=_LEG_B, count=300, seed=5)
    robot = PairsTrading(
        leg_a=_LEG_A,
        leg_b=_LEG_B,
        params=PairsParams(
            lookback=120,
            z_entry=Decimal("1.5"),
            refit_every_bars=5,
            hedge_estimator=HedgeEstimator.KALMAN,
        ),
    )
    entries = 0
    flat_reasons: list[str] = []
    for idx, (bar_a, bar_b) in enumerate(zip(data[_LEG_A], data[_LEG_B], strict=True)):
        if idx > 220:
            shock = bar_b.close * Decimal("50")
            bar_b = OhlcvBar(
                instrument_id=bar_b.instrument_id,
                ts_utc=bar_b.ts_utc,
                open=shock,
                high=shock + Decimal("1"),
                low=shock - Decimal("1"),
                close=shock,
                volume=bar_b.volume,
            )
        signal = robot.on_bars(bar_a, bar_b)
        if signal is None:
            continue
        if signal.leg_a.side is SignalSide.FLAT:
            flat_reasons.append(signal.reason)
        else:
            entries += 1

    assert entries > 0
    assert "pairs cointegration break" in flat_reasons


def test_pairs_trading_kalman_refit_zero_freezes_thresholds() -> None:
    data = synthetic_cointegrated_pair(leg_a=_LEG_A, leg_b=_LEG_B, count=300, seed=1)
    robot = PairsTrading(
        leg_a=_LEG_A,
        leg_b=_LEG_B,
        params=PairsParams(
            lookback=120,
            z_entry=Decimal("1.5"),
            refit_every_bars=0,
            hedge_estimator=HedgeEstimator.KALMAN,
        ),
    )
    first_hedge: Decimal | None = None
    first_thresholds: tuple[Decimal, Decimal] | None = None
    checked = 0
    for bar_a, bar_b in zip(data[_LEG_A], data[_LEG_B], strict=True):
        robot.on_bars(bar_a, bar_b)
        if robot._state is None:
            continue
        if first_hedge is None:
            first_hedge = robot._state.coint.hedge_ratio
            first_thresholds = robot._entry_thresholds()
        else:
            assert robot._state.coint.hedge_ratio == first_hedge
            assert robot._entry_thresholds() == first_thresholds
            checked += 1
    assert checked > 0


def test_pairs_default_ols_unchanged_and_settings_forwarding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = synthetic_cointegrated_pair(leg_a=_LEG_A, leg_b=_LEG_B, count=220, seed=1)
    default_robot = PairsTrading(leg_a=_LEG_A, leg_b=_LEG_B, params=PairsParams())
    ols_robot = PairsTrading(
        leg_a=_LEG_A,
        leg_b=_LEG_B,
        params=PairsParams(hedge_estimator=HedgeEstimator.OLS),
    )
    for bar_a, bar_b in zip(data[_LEG_A], data[_LEG_B], strict=True):
        assert default_robot.on_bars(bar_a, bar_b) == ols_robot.on_bars(bar_a, bar_b)

    monkeypatch.setenv("PAIRS_HEDGE_ESTIMATOR", "kalman")
    monkeypatch.setenv("PAIRS_KALMAN_DELTA", "0.01")
    params = Settings(_env_file=None).pairs_params()  # type: ignore[call-arg]
    assert params.hedge_estimator is HedgeEstimator.KALMAN
    assert params.kalman_delta == Decimal("0.01")

    monkeypatch.setenv("PAIRS_HEDGE_ESTIMATOR", "bogus")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]
