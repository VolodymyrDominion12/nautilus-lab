from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

from nautilus_lab.application.dtos import BacktestRequest, SelectedParams, selected_from_request
from nautilus_lab.domain.regime import RobotName

#: `SelectedParams` field -> the `Settings` key it is read from. `None` means the field has
#: no env name at all: `pairs` keeps `z_entry`/`z_exit` inside `PairsParams`, so they can be
#: chosen by the search but never set from a batch or from the settings tab. The mapping is
#: what lets `gridded_env_names` say "the search re-selects *this key*", which is the warning
#: the batch form shows: a value typed for a key the search overwrites never reaches the run.
_FIELD_ENV: dict[str, str | None] = {
    "fast_ema": "FAST_EMA",
    "slow_ema": "SLOW_EMA",
    "donchian_period": "DONCHIAN_PERIOD",
    "bb_period": "BB_PERIOD",
    "bb_k": "BB_K",
    "enter_trend_er": "ENTER_TREND_ER",
    "exit_trend_er": "EXIT_TREND_ER",
    "z_entry": None,
    "z_exit": None,
    "vpin_ema_period": "VPIN_MOMENTUM_EMA_PERIOD",
    "vpin_atr_multiple": "VPIN_MOMENTUM_ATR_MULTIPLE",
    "vpin_quantile": "VPIN_QUANTILE",
    "formulaic_threshold": "FORMULAIC_THRESHOLD",
    "meta_label_threshold": "META_LABEL_THRESHOLD",
    "adaptive_period": "ADAPTIVE_PERIOD",
    "adaptive_selectivity": "ADAPTIVE_SELECTIVITY",
    "funding_min_net_apy": "FUNDING_MIN_NET_APY",
    "funding_holding_periods": "FUNDING_HOLDING_PERIODS",
    "ema_min_spread_pct": "EMA_MIN_SPREAD_PCT",
}

#: The value `gridded_env_names` probes the grid with. No grid point equals it, so a field
#: still holding it after the grid ran was passed through from the base — i.e. the search
#: does not re-select that field.
_PROBE = 999_001


def iter_param_grid(request: BacktestRequest) -> Iterator[SelectedParams]:
    """Small grid. Fit on in-sample only; never peek at out-of-sample."""
    yield from iter_grid(
        request.robot,
        selected_from_request(request),
        use_quantile_vpin=request.use_quantile_vpin,
    )


def iter_grid(
    robot: RobotName,
    base: SelectedParams,
    *,
    use_quantile_vpin: bool = False,
) -> Iterator[SelectedParams]:
    """The candidates of one robot's search, from a base configuration.

    Split out of `iter_param_grid` so the grid can be enumerated without a full
    `BacktestRequest` — `gridded_env_names` needs exactly that, and a test can check what
    the search varies per robot without touching the engine or the filesystem.
    """
    if robot is RobotName.PAIRS:
        for z_entry in (Decimal("1.5"), Decimal("2"), Decimal("2.5"), Decimal("3")):
            yield SelectedParams(
                fast_ema=base.fast_ema,
                slow_ema=base.slow_ema,
                donchian_period=base.donchian_period,
                bb_period=base.bb_period,
                bb_k=base.bb_k,
                enter_trend_er=base.enter_trend_er,
                exit_trend_er=base.exit_trend_er,
                z_entry=z_entry,
                z_exit=base.z_exit,
            )
        return
    if robot is RobotName.VPIN_MOMENTUM:
        quantiles = (
            (Decimal("0.85"), Decimal("0.90"), Decimal("0.95"))
            if use_quantile_vpin
            else (base.vpin_quantile,)
        )
        for ema_period in (30, 50, 80):
            for quantile in quantiles:
                yield SelectedParams(
                    fast_ema=base.fast_ema,
                    slow_ema=base.slow_ema,
                    donchian_period=base.donchian_period,
                    bb_period=base.bb_period,
                    bb_k=base.bb_k,
                    enter_trend_er=base.enter_trend_er,
                    exit_trend_er=base.exit_trend_er,
                    z_entry=base.z_entry,
                    z_exit=base.z_exit,
                    vpin_ema_period=ema_period,
                    vpin_atr_multiple=base.vpin_atr_multiple,
                    vpin_quantile=quantile,
                )
        return
    if robot is RobotName.FORMULAIC_LGBM:
        for threshold in (
            Decimal("0.50"),
            Decimal("0.55"),
            Decimal("0.60"),
            Decimal("0.65"),
            Decimal("0.70"),
        ):
            yield SelectedParams(
                fast_ema=base.fast_ema,
                slow_ema=base.slow_ema,
                donchian_period=base.donchian_period,
                bb_period=base.bb_period,
                bb_k=base.bb_k,
                enter_trend_er=base.enter_trend_er,
                exit_trend_er=base.exit_trend_er,
                z_entry=base.z_entry,
                z_exit=base.z_exit,
                vpin_ema_period=base.vpin_ema_period,
                vpin_atr_multiple=base.vpin_atr_multiple,
                formulaic_threshold=threshold,
            )
        return
    if robot is RobotName.META_LABEL:
        for threshold in (
            Decimal("0.45"),
            Decimal("0.50"),
            Decimal("0.55"),
            Decimal("0.60"),
            Decimal("0.65"),
        ):
            yield SelectedParams(
                fast_ema=base.fast_ema,
                slow_ema=base.slow_ema,
                donchian_period=base.donchian_period,
                bb_period=base.bb_period,
                bb_k=base.bb_k,
                enter_trend_er=base.enter_trend_er,
                exit_trend_er=base.exit_trend_er,
                z_entry=base.z_entry,
                z_exit=base.z_exit,
                vpin_ema_period=base.vpin_ema_period,
                vpin_atr_multiple=base.vpin_atr_multiple,
                meta_label_threshold=threshold,
            )
        return
    if robot is RobotName.ADAPTIVE_EMA:
        # selectivity=0 is the control: it keeps the step constant, i.e. the same
        # robot with a fixed-alpha filter. If the winner is the control, adaptive
        # smoothing adds nothing — see specs/strategies/adaptive_ema.yaml.
        for period in (10, 20, 40):
            for selectivity in (Decimal("0"), Decimal("0.5"), Decimal("1")):
                yield SelectedParams(
                    fast_ema=base.fast_ema,
                    slow_ema=base.slow_ema,
                    donchian_period=base.donchian_period,
                    bb_period=base.bb_period,
                    bb_k=base.bb_k,
                    enter_trend_er=base.enter_trend_er,
                    exit_trend_er=base.exit_trend_er,
                    adaptive_period=period,
                    adaptive_selectivity=selectivity,
                )
        return
    if robot is RobotName.EMA:
        for fast, slow in ((5, 20), (10, 20), (10, 40), (12, 26)):
            yield SelectedParams(
                fast_ema=fast,
                slow_ema=slow,
                donchian_period=base.donchian_period,
                bb_period=base.bb_period,
                bb_k=base.bb_k,
                enter_trend_er=base.enter_trend_er,
                exit_trend_er=base.exit_trend_er,
                ema_min_spread_pct=base.ema_min_spread_pct,
            )
        return
    if robot is RobotName.FUNDING:
        for min_apy in (Decimal("0"), Decimal("0.05"), Decimal("0.10")):
            for holding_periods in (30, 60, 90, 120):
                yield SelectedParams(
                    fast_ema=base.fast_ema,
                    slow_ema=base.slow_ema,
                    donchian_period=base.donchian_period,
                    bb_period=base.bb_period,
                    bb_k=base.bb_k,
                    enter_trend_er=base.enter_trend_er,
                    exit_trend_er=base.exit_trend_er,
                    funding_min_net_apy=min_apy,
                    funding_holding_periods=holding_periods,
                )
        return
    for donchian in (20, 40, 60, 90, 120):
        for band_k in (Decimal("2"), Decimal("2.5"), Decimal("3")):
            yield SelectedParams(
                fast_ema=base.fast_ema,
                slow_ema=base.slow_ema,
                donchian_period=donchian,
                bb_period=donchian,
                bb_k=band_k,
                enter_trend_er=base.enter_trend_er,
                exit_trend_er=base.exit_trend_er,
            )


def _probe_params() -> SelectedParams:
    """A base configuration no grid point can produce (see `_PROBE`)."""
    probe = Decimal(_PROBE)
    return SelectedParams(
        fast_ema=_PROBE,
        slow_ema=_PROBE,
        donchian_period=_PROBE,
        bb_period=_PROBE,
        bb_k=probe,
        enter_trend_er=probe,
        exit_trend_er=probe,
        z_entry=probe,
        z_exit=probe,
        vpin_ema_period=_PROBE,
        vpin_atr_multiple=probe,
        vpin_quantile=probe,
        formulaic_threshold=probe,
        meta_label_threshold=probe,
        adaptive_period=_PROBE,
        adaptive_selectivity=probe,
        funding_min_net_apy=probe,
        funding_holding_periods=_PROBE,
        ema_min_spread_pct=probe,
    )


def gridded_env_names(robot: RobotName) -> frozenset[str]:
    """The `Settings` keys this robot's in-sample search varies — and therefore overwrites.

    Why this is a function and not a list in a doc: a value put into a batch's `env` only
    survives the walk-forward when the grid does not vary that key. Setting
    `DONCHIAN_PERIOD=40` for `regime` changes nothing at all, because the search replaces it
    with whatever it liked best on the in-sample block (`apply_selected`). That silence cost
    a researcher an afternoon of "the parameter does nothing", so the batch form names these
    keys instead of letting the value disappear.

    The answer is read from the grid itself (`iter_grid`) rather than from a spec, so it
    cannot describe a search that no longer exists; `specs/_validator.py` goes the other way
    and checks that each spec declares exactly these keys under `params[].grid`.

    `vpin_momentum` is the one robot whose grid depends on a flag (`USE_QUANTILE_VPIN`, which
    a batch turns on for that robot by default): the union of both modes is reported, so a key
    is named when *any* mode the batch can create would re-select it. The warning errs towards
    naming the key — the honest direction, because a silently ignored value is the failure
    mode this exists to prevent.

    A key can also fail to reach a run without being varied: the grid builds its candidates
    as fresh `SelectedParams`, so a field it never passes falls back to the dataclass default
    instead of the run's own value (`tests/unit/test_param_grid.py` pins which keys do that,
    per robot — today they all belong to other robots' parameters).
    """
    probe = _probe_params()
    varied: set[str] = set()
    for use_quantile in (False, True):
        candidates = list(iter_grid(robot, probe, use_quantile_vpin=use_quantile))
        for field, env_key in _FIELD_ENV.items():
            if env_key is None:
                continue
            values = {getattr(candidate, field) for candidate in candidates}
            if len(values) > 1:
                varied.add(env_key)
    return frozenset(varied)
