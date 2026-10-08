"""The parallel in-sample grid gives the serial grid's numbers, on the real engine.

`ParallelResearchBacktest.run_many` runs every candidate in a spawned worker with its own
`BacktestEngine`; nothing about a run may depend on which process ran it or in what order.
The bar-conversion cache (`_cached_engine_bars`) is exercised on the way: the serial pass
converts the series once and reuses it for every candidate.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytest.importorskip("nautilus_trader")

from nautilus_lab.application.dtos import BacktestRequest, apply_selected
from nautilus_lab.application.param_grid import iter_param_grid
from nautilus_lab.application.timing import TIMINGS
from nautilus_lab.domain.bars import BarOrigin
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus import backtest_runner
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest
from nautilus_lab.infrastructure.nautilus.parallel_backtest import (
    ParallelResearchBacktest,
)
from nautilus_lab.infrastructure.nautilus.synthetic_bars import (
    synthetic_regime_ohlcv,
)


@pytest.mark.integration
def test_parallel_grid_matches_serial_grid() -> None:
    base = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=900,
        starting_equity=Decimal("100000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.005"),
            stop_pct=Decimal("0.01"),
            max_daily_loss=Decimal("0.02"),
            max_drawdown=Decimal("0.06"),
        ),
        robot=RobotName.REGIME,
        seed=7,
        source=BarOrigin.SYNTHETIC,
    )
    bars = synthetic_regime_ohlcv(instrument_id="ETH/USDT.SIM", count=900, seed=7)
    candidates = [apply_selected(base, params) for params in iter_param_grid(base)][:4]

    inner = NautilusResearchBacktest()
    backtest_runner._ENGINE_BARS_CACHE.clear()  # another test may have converted this series
    TIMINGS.reset()
    serial = [inner.run(candidate, bars) for candidate in candidates]
    phases = TIMINGS.snapshot()
    assert phases["convert_bars"]["count"] == 1  # converted once, reused 3 times
    assert phases["convert_bars_cached"]["count"] == len(candidates) - 1

    engine = ParallelResearchBacktest(inner, workers=2)
    try:
        parallel = engine.run_many(candidates, bars)
    finally:
        engine.close()

    assert [r.ending_balance for r in parallel] == [r.ending_balance for r in serial]
    assert [r.fills for r in parallel] == [r.fills for r in serial]
    assert [r.risk_breaches for r in parallel] == [r.risk_breaches for r in serial]
