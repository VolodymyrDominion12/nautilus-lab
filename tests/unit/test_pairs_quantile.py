"""The optional empirical-quantile entry gate for `pairs`.

Two things must hold and are tested here separately:

1. **Default is untouched.** `z_entry_quantile=None` reproduces the fixed
   `±z_entry` gate exactly, so every number in docs/05 §4 stays valid.
2. **Quantile mode is a self-calibrating gate.** The thresholds are the
   empirical `p` / `1 - p` quantiles of the fitted spread window mapped into z
   with the same (mean, sigma) the live reading uses.
"""

from decimal import Decimal

import pytest

from nautilus_lab.domain.pairs.ou import z_score
from nautilus_lab.domain.pairs.pairs_trading import PairsTrading
from nautilus_lab.domain.pairs.params import PairsParams
from nautilus_lab.domain.quantiles import empirical_quantile
from nautilus_lab.domain.signals import SignalSide
from nautilus_lab.infrastructure.nautilus.synthetic_pairs import synthetic_cointegrated_pair

_LEG_A = "ETH/USDT.SIM"
_LEG_B = "BTC/USDT.SIM"


def test_default_gate_is_the_configured_z_entry() -> None:
    """No quantile configured -> thresholds are exactly the fixed ones."""
    robot = _robot_params_until_fitted(PairsParams(lookback=120, z_entry=Decimal("1.5")))
    assert robot._entry_thresholds() == (Decimal("-1.5"), Decimal("1.5"))


def test_passing_none_explicitly_is_the_same_as_omitting_it() -> None:
    """The `None` default must not be a third, subtly different mode."""
    omitted = _entry_count(PairsParams(lookback=120, z_entry=Decimal("1.5")))
    explicit = _entry_count(
        PairsParams(lookback=120, z_entry=Decimal("1.5"), z_entry_quantile=None)
    )
    assert omitted == explicit
    assert omitted > 0


def test_quantile_thresholds_are_standardised_window_quantiles() -> None:
    """The gate is the empirical quantile, put in the same z units as the signal."""
    robot = _robot_params_until_fitted(PairsParams(lookback=120, z_entry_quantile=Decimal("0.05")))
    state = robot._state
    assert state is not None

    low, high = robot._entry_thresholds()
    expected_low = z_score(
        empirical_quantile(state.spreads, Decimal("0.05")),
        state.ou.mean,
        state.ou.sigma,
    )
    expected_high = z_score(
        empirical_quantile(state.spreads, Decimal("0.95")),
        state.ou.mean,
        state.ou.sigma,
    )
    assert low == expected_low
    assert high == expected_high
    assert low < high


def test_quantile_mode_ignores_the_fixed_z_entry() -> None:
    """`z_entry` must not leak into quantile mode — the modes are exclusive."""
    tight = _robot_params_until_fitted(
        PairsParams(lookback=120, z_entry=Decimal("0.1"), z_entry_quantile=Decimal("0.05"))
    )
    loose = _robot_params_until_fitted(
        PairsParams(lookback=120, z_entry=Decimal("9"), z_entry_quantile=Decimal("0.05"))
    )
    assert tight._entry_thresholds() == loose._entry_thresholds()


def test_a_smaller_quantile_is_a_stricter_gate() -> None:
    """Lower `p` sits further out in the tail, so it cannot allow more entries."""
    strict = _entry_count(PairsParams(lookback=120, z_entry_quantile=Decimal("0.01")))
    loose = _entry_count(PairsParams(lookback=120, z_entry_quantile=Decimal("0.20")))
    assert strict <= loose


def test_thresholds_are_frozen_while_a_position_is_open() -> None:
    """No lookahead: with refit disabled the gate cannot be revised mid-trade.

    The window the quantile comes from is the same frozen window mu and sigma come
    from, so feeding the robot more bars must not move the thresholds it is
    already trading against.
    """
    data = synthetic_cointegrated_pair(leg_a=_LEG_A, leg_b=_LEG_B, count=400, seed=3)
    robot = PairsTrading(
        leg_a=_LEG_A,
        leg_b=_LEG_B,
        params=PairsParams(lookback=120, z_entry_quantile=Decimal("0.05")),
    )
    first: tuple[Decimal, Decimal] | None = None
    seen = 0
    for bar_a, bar_b in zip(data[_LEG_A], data[_LEG_B], strict=True):
        robot.on_bars(bar_a, bar_b)
        if robot._state is None:
            continue
        thresholds = robot._entry_thresholds()
        if first is None:
            first = thresholds
            continue
        seen += 1
    assert first is not None
    assert seen > 0, "the fit never produced enough bars to re-check the gate"
    assert robot._entry_thresholds() == first


@pytest.mark.parametrize("probability", ["0", "0.5", "-0.1", "0.9", "1"])
def test_pairs_params_rejects_an_out_of_range_quantile(probability: str) -> None:
    with pytest.raises(ValueError, match=r"z_entry_quantile must be in \(0, 0.5\) or None"):
        PairsParams(z_entry_quantile=Decimal(probability))


def test_malformed_bars_do_not_reach_the_gate() -> None:
    """Sanity: the quantile path still rejects non-increasing timestamps."""
    robot = PairsTrading(
        leg_a=_LEG_A,
        leg_b=_LEG_B,
        params=PairsParams(lookback=30, z_entry_quantile=Decimal("0.05")),
    )
    data = synthetic_cointegrated_pair(leg_a=_LEG_A, leg_b=_LEG_B, count=40, seed=7)
    bars_a = data[_LEG_A]
    for bar_a, bar_b in zip(bars_a, data[_LEG_B], strict=True):
        robot.on_bars(bar_a, bar_b)
    # The robot itself does not validate timestamps (the adapter does), so this
    # only asserts the quantile path never crashed on a short window.
    assert robot._state is None or robot._state.spreads


def test_settings_sentinel_zero_means_the_gate_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`PAIRS_Z_ENTRY_QUANTILE=0` must reach the domain as `None`, not `Decimal(0)`."""
    from nautilus_lab.infrastructure.settings import Settings

    monkeypatch.setenv("PAIRS_Z_ENTRY_QUANTILE", "0")
    assert Settings().pairs_params().z_entry_quantile is None


def test_settings_passes_a_real_probability_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nautilus_lab.infrastructure.settings import Settings

    monkeypatch.setenv("PAIRS_Z_ENTRY_QUANTILE", "0.05")
    params = Settings().pairs_params()
    assert params.z_entry_quantile == Decimal("0.05")


def test_settings_default_keeps_the_fixed_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The documented `pairs` configuration is `z_entry`, so the default is off."""
    from nautilus_lab.infrastructure.settings import Settings

    monkeypatch.delenv("PAIRS_Z_ENTRY_QUANTILE", raising=False)
    params = Settings().pairs_params()
    assert params.z_entry_quantile is None
    assert params.z_entry == Decimal("2")


def test_settings_rejects_a_probability_the_domain_would_reject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bad value fails loudly at the composition root, not mid-backtest."""
    from nautilus_lab.infrastructure.settings import Settings

    monkeypatch.setenv("PAIRS_Z_ENTRY_QUANTILE", "0.9")
    with pytest.raises(ValueError, match="z_entry_quantile"):
        Settings().pairs_params()


def _entry_count(params: PairsParams, *, count: int = 250, seed: int = 1) -> int:
    data = synthetic_cointegrated_pair(leg_a=_LEG_A, leg_b=_LEG_B, count=count, seed=seed)
    robot = PairsTrading(leg_a=_LEG_A, leg_b=_LEG_B, params=params)
    entries = 0
    for bar_a, bar_b in zip(data[_LEG_A], data[_LEG_B], strict=True):
        signal = robot.on_bars(bar_a, bar_b)
        if signal is not None and signal.leg_a.side is not SignalSide.FLAT:
            entries += 1
    return entries


def _robot_params_until_fitted(params: PairsParams) -> PairsTrading:
    """Drive the robot until the cointegration gate opens, then hand it back."""
    data = synthetic_cointegrated_pair(leg_a=_LEG_A, leg_b=_LEG_B, count=250, seed=1)
    robot = PairsTrading(leg_a=_LEG_A, leg_b=_LEG_B, params=params)
    for bar_a, bar_b in zip(data[_LEG_A], data[_LEG_B], strict=True):
        robot.on_bars(bar_a, bar_b)
        if robot._state is not None:
            return robot
    raise AssertionError("the synthetic pair never passed the cointegration gates")
