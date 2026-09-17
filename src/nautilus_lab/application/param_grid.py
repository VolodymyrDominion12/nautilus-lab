from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

from nautilus_lab.application.dtos import BacktestRequest, SelectedParams, selected_from_request
from nautilus_lab.domain.regime import RobotName


def iter_param_grid(request: BacktestRequest) -> Iterator[SelectedParams]:
    """Small grid. Fit on in-sample only; never peek at out-of-sample."""
    base = selected_from_request(request)
    if request.robot is RobotName.PAIRS:
        for z_entry in (Decimal("1.5"), Decimal("2"), Decimal("2.5")):
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
    if request.robot is RobotName.VPIN_MOMENTUM:
        for ema_period in (30, 50, 80):
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
            )
        return
    if request.robot is RobotName.FORMULAIC_LGBM:
        for threshold in (Decimal("0.50"), Decimal("0.55"), Decimal("0.60")):
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
    if request.robot is RobotName.META_LABEL:
        for threshold in (Decimal("0.50"), Decimal("0.55"), Decimal("0.60")):
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
    if request.robot is RobotName.ADAPTIVE_EMA:
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
    if request.robot is RobotName.EMA:
        for fast, slow in ((5, 20), (10, 20), (10, 40), (12, 26)):
            yield SelectedParams(
                fast_ema=fast,
                slow_ema=slow,
                donchian_period=base.donchian_period,
                bb_period=base.bb_period,
                bb_k=base.bb_k,
                enter_trend_er=base.enter_trend_er,
                exit_trend_er=base.exit_trend_er,
            )
        return
    for donchian in (10, 20, 40):
        for band_k in (Decimal("2"), Decimal("2.5")):
            yield SelectedParams(
                fast_ema=base.fast_ema,
                slow_ema=base.slow_ema,
                donchian_period=donchian,
                bb_period=donchian,
                bb_k=band_k,
                enter_trend_er=base.enter_trend_er,
                exit_trend_er=base.exit_trend_er,
            )
