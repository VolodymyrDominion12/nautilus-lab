from __future__ import annotations

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.ports import BarCatalog
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.infrastructure.nautilus.synthetic_bars import (
    synthetic_ohlcv,
    synthetic_regime_ohlcv,
)


class ResearchBarFeed:
    """Catalog of real history, or deterministic synthetic bars for tests."""

    def __init__(self, catalog: BarCatalog) -> None:
        self._catalog = catalog

    def load(self, request: BacktestRequest) -> list[OhlcvBar]:
        if request.source is BarOrigin.SYNTHETIC:
            return _synthetic(request)
        return self._catalog.load(
            bar_type=request.bar_type,
            start=request.start,
            end=request.end,
        )


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
