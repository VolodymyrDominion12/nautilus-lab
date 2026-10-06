from decimal import Decimal

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.application.param_grid import iter_param_grid
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode


def _request(robot: RobotName) -> BacktestRequest:
    return BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=200,
        starting_equity=Decimal("100000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.005"),
            stop_pct=Decimal("0.01"),
            max_daily_loss=Decimal("0.02"),
            max_drawdown=Decimal("0.06"),
        ),
        robot=robot,
    )


def test_ema_grid_varies_periods_only() -> None:
    grid = list(iter_param_grid(_request(RobotName.EMA)))
    pairs = {(item.fast_ema, item.slow_ema) for item in grid}
    assert pairs == {(5, 20), (10, 20), (10, 40), (12, 26)}


def test_regime_grid_varies_donchian_and_bands() -> None:
    grid = list(iter_param_grid(_request(RobotName.REGIME)))
    assert len(grid) == 15
    assert {item.donchian_period for item in grid} == {20, 40, 60, 90, 120}
    assert {item.bb_k for item in grid} == {Decimal("2"), Decimal("2.5"), Decimal("3")}


def test_formulaic_grid_varies_threshold_only() -> None:
    grid = list(iter_param_grid(_request(RobotName.FORMULAIC_LGBM)))
    assert len(grid) == 5
    assert {item.formulaic_threshold for item in grid} == {
        Decimal("0.50"),
        Decimal("0.55"),
        Decimal("0.60"),
        Decimal("0.65"),
        Decimal("0.70"),
    }


def test_meta_label_grid_varies_threshold_only() -> None:
    grid = list(iter_param_grid(_request(RobotName.META_LABEL)))
    assert len(grid) == 5
    assert {item.meta_label_threshold for item in grid} == {
        Decimal("0.45"),
        Decimal("0.50"),
        Decimal("0.55"),
        Decimal("0.60"),
        Decimal("0.65"),
    }


def test_adaptive_ema_grid_contains_the_fixed_alpha_control() -> None:
    grid = list(iter_param_grid(_request(RobotName.ADAPTIVE_EMA)))
    pairs = {(item.adaptive_period, item.adaptive_selectivity) for item in grid}
    assert pairs == {
        (10, Decimal("0")),
        (10, Decimal("0.5")),
        (10, Decimal("1")),
        (20, Decimal("0")),
        (20, Decimal("0.5")),
        (20, Decimal("1")),
        (40, Decimal("0")),
        (40, Decimal("0.5")),
        (40, Decimal("1")),
    }
    # Without this zero column the grid could not falsify "selectivity adds nothing".
    assert any(selectivity == Decimal("0") for _, selectivity in pairs)


def test_pairs_grid_varies_z_entry() -> None:
    grid = list(iter_param_grid(_request(RobotName.PAIRS)))
    assert len(grid) == 4
    assert {item.z_entry for item in grid} == {
        Decimal("1.5"),
        Decimal("2"),
        Decimal("2.5"),
        Decimal("3"),
    }


def test_every_grid_point_has_its_own_trial_label() -> None:
    """Audit B5: the three vpin_momentum points shared one label (1 trial, not 3)."""
    for robot in RobotName:
        grid = list(iter_param_grid(_request(robot)))
        labels = [item.label() for item in grid]
        assert len(set(labels)) == len(labels), robot


def test_default_extras_keep_recorded_labels_unchanged() -> None:
    """Labels already in research/trials.jsonl must still match their configurations."""
    grid = list(iter_param_grid(_request(RobotName.VPIN_MOMENTUM)))
    default = next(item for item in grid if item.vpin_ema_period == 50)
    assert "vpin_ema_period" not in default.label()
    assert "vpin_ema_period=30" in next(i for i in grid if i.vpin_ema_period == 30).label()


def test_vpin_momentum_grid_ignores_quantile_by_default() -> None:
    grid = list(iter_param_grid(_request(RobotName.VPIN_MOMENTUM)))
    assert len(grid) == 3
    assert {item.vpin_quantile for item in grid} == {Decimal("0.90")}


def test_vpin_momentum_grid_varies_quantile_when_enabled() -> None:
    from dataclasses import replace

    request = replace(_request(RobotName.VPIN_MOMENTUM), use_quantile_vpin=True)
    grid = list(iter_param_grid(request))
    assert len(grid) == 9
    assert {item.vpin_quantile for item in grid} == {
        Decimal("0.85"),
        Decimal("0.90"),
        Decimal("0.95"),
    }
    assert len({item.label() for item in grid}) == 9


# ---- what the search re-selects (the batch form's warning) ------------------------------


def test_the_search_varies_exactly_the_keys_its_spec_declares() -> None:
    """`gridded_env_names` is what the batch form warns about; pin it per robot.

    Measured 2026-10-05. `regime` and the other robots without their own branch
    (`ml_obi`, `glft`, `tri_scan`) fall into the default branch, i.e. they are searched with
    the regime grid — the trap `implementation.grid_source: default_branch` names.
    """
    from nautilus_lab.application.param_grid import gridded_env_names

    expected = {
        RobotName.REGIME: {"DONCHIAN_PERIOD", "BB_PERIOD", "BB_K"},
        RobotName.EMA: {"FAST_EMA", "SLOW_EMA"},
        RobotName.ADAPTIVE_EMA: {"ADAPTIVE_PERIOD", "ADAPTIVE_SELECTIVITY"},
        RobotName.VPIN_MOMENTUM: {"VPIN_MOMENTUM_EMA_PERIOD", "VPIN_QUANTILE"},
        RobotName.FORMULAIC_LGBM: {"FORMULAIC_THRESHOLD"},
        RobotName.META_LABEL: {"META_LABEL_THRESHOLD"},
        RobotName.FUNDING: {"FUNDING_MIN_NET_APY", "FUNDING_HOLDING_PERIODS"},
        # The pairs grid moves `z_entry`, and `z_entry` has no env name at all (it lives in
        # `PairsParams`), so no key can be warned about — and none can be set from a batch.
        RobotName.PAIRS: set(),
        RobotName.ML_OBI: {"DONCHIAN_PERIOD", "BB_PERIOD", "BB_K"},
        RobotName.GLFT: {"DONCHIAN_PERIOD", "BB_PERIOD", "BB_K"},
        RobotName.TRI_SCAN: {"DONCHIAN_PERIOD", "BB_PERIOD", "BB_K"},
    }
    for robot, keys in expected.items():
        assert set(gridded_env_names(robot)) == keys, robot


def test_a_key_the_search_varies_is_replaced_and_a_free_key_is_kept() -> None:
    """Why the warning exists: `DONCHIAN_PERIOD=999` never reaches an OOS run.

    The grid builds its candidates from constants and `apply_selected` overwrites the run's
    own values with the winner's, so for `regime` the in-sample choice replaces whatever the
    batch was told. `ENTER_TREND_ER` is not in the grid, and survives every candidate.
    """
    from dataclasses import replace

    from nautilus_lab.application.dtos import SelectedParams
    from nautilus_lab.application.param_grid import iter_grid

    base = replace(
        SelectedParams(
            fast_ema=10,
            slow_ema=20,
            donchian_period=20,
            bb_period=20,
            bb_k=Decimal("2"),
            enter_trend_er=Decimal("0.30"),
            exit_trend_er=Decimal("0.20"),
        ),
        donchian_period=999,
        enter_trend_er=Decimal("0.42"),
    )
    grid = list(iter_grid(RobotName.REGIME, base))
    assert 999 not in {item.donchian_period for item in grid}
    assert {item.enter_trend_er for item in grid} == {Decimal("0.42")}


def test_a_field_the_grid_never_passes_falls_back_to_its_default() -> None:
    """The other way a value fails to reach a run, pinned so a change is not silent.

    Candidates are built as fresh `SelectedParams`, so a field a branch never passes takes the
    dataclass default instead of the run's value — for `regime` that is the parameters of the
    *other* robots, which the regime strategy does not read. Harmless today; if a robot starts
    reading one of these keys, the value a researcher set would be dropped, and this is where
    that shows up. A key that is *varied* is not listed here: `gridded_env_names` reports it,
    and that is the warning the batch form shows.
    """
    from nautilus_lab.application.param_grid import _FIELD_ENV, _probe_params, iter_grid

    # Measured 2026-10-05, robot by robot: the keys each branch does NOT pass from the base.
    # Written out rather than derived: this is a pin, and a derived expectation would move
    # with the code it is supposed to notice.
    default_branch = {
        "ADAPTIVE_PERIOD",
        "ADAPTIVE_SELECTIVITY",
        "EMA_MIN_SPREAD_PCT",
        "FORMULAIC_THRESHOLD",
        "FUNDING_HOLDING_PERIODS",
        "FUNDING_MIN_NET_APY",
        "META_LABEL_THRESHOLD",
        "VPIN_MOMENTUM_ATR_MULTIPLE",
        "VPIN_MOMENTUM_EMA_PERIOD",
        "VPIN_QUANTILE",
    }
    expected: dict[RobotName, set[str]] = {
        RobotName.VPIN_MOMENTUM: {
            "ADAPTIVE_PERIOD",
            "ADAPTIVE_SELECTIVITY",
            "EMA_MIN_SPREAD_PCT",
            "FORMULAIC_THRESHOLD",
            "FUNDING_HOLDING_PERIODS",
            "FUNDING_MIN_NET_APY",
            "META_LABEL_THRESHOLD",
        },
        RobotName.FORMULAIC_LGBM: {
            "ADAPTIVE_PERIOD",
            "ADAPTIVE_SELECTIVITY",
            "EMA_MIN_SPREAD_PCT",
            "FUNDING_HOLDING_PERIODS",
            "FUNDING_MIN_NET_APY",
            "META_LABEL_THRESHOLD",
            "VPIN_QUANTILE",
        },
        RobotName.META_LABEL: {
            "ADAPTIVE_PERIOD",
            "ADAPTIVE_SELECTIVITY",
            "EMA_MIN_SPREAD_PCT",
            "FORMULAIC_THRESHOLD",
            "FUNDING_HOLDING_PERIODS",
            "FUNDING_MIN_NET_APY",
            "VPIN_QUANTILE",
        },
        RobotName.FUNDING: {
            "ADAPTIVE_PERIOD",
            "ADAPTIVE_SELECTIVITY",
            "EMA_MIN_SPREAD_PCT",
            "FORMULAIC_THRESHOLD",
            "META_LABEL_THRESHOLD",
            "VPIN_MOMENTUM_ATR_MULTIPLE",
            "VPIN_MOMENTUM_EMA_PERIOD",
            "VPIN_QUANTILE",
        },
        RobotName.ADAPTIVE_EMA: {
            "EMA_MIN_SPREAD_PCT",
            "FORMULAIC_THRESHOLD",
            "FUNDING_HOLDING_PERIODS",
            "FUNDING_MIN_NET_APY",
            "META_LABEL_THRESHOLD",
            "VPIN_MOMENTUM_ATR_MULTIPLE",
            "VPIN_MOMENTUM_EMA_PERIOD",
            "VPIN_QUANTILE",
        },
        # The `ema` branch is the only one that passes `ema_min_spread_pct` through.
        RobotName.EMA: default_branch - {"EMA_MIN_SPREAD_PCT"},
    }
    for robot in (
        RobotName.REGIME,
        RobotName.PAIRS,
        RobotName.ML_OBI,
        RobotName.GLFT,
        RobotName.TRI_SCAN,
    ):
        expected[robot] = default_branch

    probe = _probe_params()
    dropped: dict[RobotName, set[str]] = {}
    for robot in RobotName:
        grid = list(iter_grid(robot, probe))
        for field, key in _FIELD_ENV.items():
            if key is None:
                continue
            values = {getattr(item, field) for item in grid}
            base_value = getattr(probe, field)
            if len(values) == 1 and next(iter(values)) != base_value:
                dropped.setdefault(robot, set()).add(key)
    assert dropped == expected


def test_every_mapped_env_key_is_a_settings_field() -> None:
    """The map says "this SelectedParams field comes from that env var" — so it must exist."""
    from nautilus_lab.application.param_grid import _FIELD_ENV
    from nautilus_lab.infrastructure.settings import Settings

    fields = {name.upper() for name in Settings.model_fields}
    for field, env_key in _FIELD_ENV.items():
        if env_key is None:
            continue
        assert env_key in fields, f"{field} -> {env_key} is not a Settings field"


def test_the_spec_validator_reads_the_same_grid_out_of_the_source() -> None:
    """`specs/_validator.py` must not import the project, so it parses param_grid.py with ast.

    Two readers of the same truth is exactly how a warning starts lying; this pins that the
    import-free reader and the runtime function agree for every robot.
    """
    import importlib.util
    import sys
    from pathlib import Path

    from nautilus_lab.application.param_grid import gridded_env_names

    spec = importlib.util.spec_from_file_location(
        "_spec_validator", Path(__file__).resolve().parents[2] / "specs" / "_validator.py"
    )
    assert spec is not None
    assert spec.loader is not None
    validator = importlib.util.module_from_spec(spec)
    # Registered before exec: the module defines a dataclass, and `dataclasses` looks the
    # defining module up in `sys.modules` while resolving its annotations.
    sys.modules[spec.name] = validator
    try:
        spec.loader.exec_module(validator)

        facts = validator.CodeFacts()
        validator.collect_grid_varied(facts)
        assert facts.problems == []
        for robot in RobotName:
            from_source = facts.grid_varied.get(robot.value, facts.grid_varied_default)
            assert from_source == set(gridded_env_names(robot)), robot
    finally:
        del sys.modules[spec.name]
