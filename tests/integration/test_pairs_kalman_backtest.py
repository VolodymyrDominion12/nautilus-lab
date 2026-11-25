from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.pairs.params import HedgeEstimator, PairsParams
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest


def _gold_silver_bars(count: int = 360) -> dict[str, list[OhlcvBar]]:
    rng = random.Random(42)
    origin = datetime(2026, 1, 10, tzinfo=UTC)
    xag_bars: list[OhlcvBar] = []
    xau_bars: list[OhlcvBar] = []
    xag_price = 31.0
    spread = 0.0
    for idx in range(count):
        ts_utc = origin + timedelta(hours=idx)
        xag_price = max(15.0, xag_price + rng.gauss(0.0, 0.25))
        beta_t = 86.0 + 3.0 * (idx / max(count - 1, 1))
        spread = 0.65 * spread + rng.gauss(0.0, 6.0)
        xau_price = max(500.0, 25.0 + beta_t * xag_price + spread)

        xag_close = Decimal(f"{xag_price:.2f}")
        xau_close = Decimal(f"{xau_price:.2f}")
        xag_bars.append(
            OhlcvBar(
                instrument_id="XAGUSDT-PERP.SIM",
                ts_utc=ts_utc,
                open=xag_close,
                high=xag_close + Decimal("0.05"),
                low=xag_close - Decimal("0.05"),
                close=xag_close,
                volume=Decimal("500"),
            )
        )
        xau_bars.append(
            OhlcvBar(
                instrument_id="XAUUSDT-PERP.SIM",
                ts_utc=ts_utc,
                open=xau_close,
                high=xau_close + Decimal("1.00"),
                low=xau_close - Decimal("1.00"),
                close=xau_close,
                volume=Decimal("100"),
            )
        )
    return {
        "XAUUSDT-PERP.SIM": xau_bars,
        "XAGUSDT-PERP.SIM": xag_bars,
    }


@pytest.mark.integration
def test_pairs_kalman_gold_silver_backtest_is_deterministic_and_trades() -> None:
    bars = _gold_silver_bars(360)
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="XAUUSDT-PERP.SIM",
        bar_count=360,
        starting_equity=Decimal("100000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.005"),
            stop_pct=Decimal("0.01"),
            max_daily_loss=Decimal("0.5"),
            max_drawdown=Decimal("0.5"),
        ),
        robot=RobotName.PAIRS,
        source=BarOrigin.SYNTHETIC,
        pairs=PairsParams(
            leg_a="XAUUSDT-PERP.SIM",
            leg_b="XAGUSDT-PERP.SIM",
            lookback=120,
            z_entry=Decimal("1.5"),
            refit_every_bars=24,
            hedge_estimator=HedgeEstimator.KALMAN,
            kalman_delta=Decimal("0.005"),
        ),
    )

    first = NautilusResearchBacktest().run_spread(request, bars)
    second = NautilusResearchBacktest().run_spread(request, bars)

    assert first.fills > 0
    assert first.ending_balance is not None
    assert first.fills == second.fills
    assert first.ending_balance == second.ending_balance
    assert first.realized_balance == second.realized_balance
    assert first.daily_returns == second.daily_returns
