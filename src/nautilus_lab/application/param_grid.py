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
