from __future__ import annotations

from datetime import datetime

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.domain.align import align_bars_inner_join
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.ports import BarCatalog
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.stress_slices import resolve_stress_slice
from nautilus_lab.infrastructure.nautilus.synthetic_bars import (
    synthetic_ohlcv,
    synthetic_regime_ohlcv,
)
from nautilus_lab.infrastructure.nautilus.synthetic_pairs import synthetic_cointegrated_pair
from nautilus_lab.infrastructure.timeframe import interval_from_bar_type, nautilus_bar_type


class ResearchBarFeed:
    """Catalog of real history, or deterministic synthetic bars for tests."""

    def __init__(self, catalog: BarCatalog) -> None:
        self._catalog = catalog

    def load(self, request: BacktestRequest) -> list[OhlcvBar]:
        if request.robot is RobotName.PAIRS:
            multi = self.load_multi(request)
            leg_a = request.pairs.leg_a
            return list(multi[leg_a])
        if request.source is BarOrigin.SYNTHETIC:
            return _synthetic(request)
        start, end = _stress_window(request)
        return self._catalog.load(
            bar_type=request.bar_type,
            start=start,
            end=end,
        )

    def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
        if request.source is BarOrigin.SYNTHETIC:
            if request.robot is RobotName.PAIRS:
                return synthetic_cointegrated_pair(
                    leg_a=request.pairs.leg_a,
                    leg_b=request.pairs.leg_b,
                    count=request.bar_count,
                    seed=request.seed,
                )
            bars = _synthetic(request)
            return {request.instrument_id: bars}
        start, end = _stress_window(request)
        interval = interval_from_bar_type(request.bar_type)
        ids = request.instrument_ids or (request.pairs.leg_a, request.pairs.leg_b)
        raw: dict[str, list[OhlcvBar]] = {}
        for instrument_id in ids:
            bar_type = nautilus_bar_type(instrument_id, interval)
            raw[instrument_id] = self._catalog.load(bar_type=bar_type, start=start, end=end)
        aligned = align_bars_inner_join(raw)
        return {key: list(value) for key, value in aligned.items()}


def _synthetic(request: BacktestRequest) -> list[OhlcvBar]:
    if request.robot is RobotName.REGIME:
        return synthetic_regime_ohlcv(
            instrument_id=request.instrument_id,
            count=request.bar_count,
            seed=request.seed,
        )
    return synthetic_ohlcv(
        instrument_id=request.instrument_id,
        count=request.bar_count,
        seed=request.seed,
    )


def _stress_window(request: BacktestRequest) -> tuple[datetime | None, datetime | None]:
    if request.stress_slice:
        slice_ = resolve_stress_slice(request.stress_slice)
        return slice_.start, slice_.end
    return request.start, request.end
