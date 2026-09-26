"""Volatility-matched buy & hold in the walk-forward report (docs/27 R-4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    WalkForwardRequest,
)
from nautilus_lab.application.run_walk_forward import RunWalkForward
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.funding import FundingSnapshot
from nautilus_lab.domain.metrics import (
    BacktestMetrics,
    buy_and_hold_return,
    compute_metrics,
    return_series_from_bars,
    sample_volatility,
    vol_matched_buy_and_hold_return,
    vol_matched_from_volatility,
)
from nautilus_lab.domain.order_book import OrderBookSnapshot
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.ticks import AggTrade
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_ohlcv

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _bars(closes: list[str]) -> list[OhlcvBar]:
    return [
        OhlcvBar(
            instrument_id="ETH/USDT.SIM",
            ts_utc=T0 + timedelta(hours=index),
            open=Decimal(close),
            high=Decimal(close),
            low=Decimal(close),
            close=Decimal(close),
            volume=Decimal("1"),
        )
        for index, close in enumerate(closes)
    ]


BARS = _bars(["100", "102", "101", "104", "103", "106"])
ASSET_VOL = sample_volatility(return_series_from_bars(BARS))


def test_half_the_risk_is_compared_with_half_the_move() -> None:
    assert ASSET_VOL is not None
    raw = buy_and_hold_return(BARS)
    assert raw is not None
    matched = vol_matched_from_volatility(bars=BARS, strategy_volatility=ASSET_VOL / 2)
    assert matched is not None
    assert abs(matched - raw / 2) < Decimal("1e-12")


def test_leverage_is_capped_and_no_risk_is_cash() -> None:
    assert ASSET_VOL is not None
    raw = buy_and_hold_return(BARS)
    assert raw is not None
    capped = vol_matched_from_volatility(bars=BARS, strategy_volatility=ASSET_VOL * 10)
    assert capped == raw * Decimal("2.0")
    assert vol_matched_from_volatility(bars=BARS, strategy_volatility=Decimal("0")) == 0


def test_unmeasurable_inputs_give_none_not_zero() -> None:
    assert vol_matched_from_volatility(bars=BARS, strategy_volatility=None) is None
    assert vol_matched_from_volatility(bars=BARS[:1], strategy_volatility=Decimal("0.01")) is None
    flat = _bars(["100", "100", "100"])
    assert vol_matched_from_volatility(bars=flat, strategy_volatility=Decimal("0.01")) is None


def test_the_curve_and_the_volatility_versions_agree() -> None:
    curve = (Decimal("1000"), Decimal("1010"), Decimal("1005"), Decimal("1020"))
    metrics = compute_metrics(
        starting_equity=Decimal("1000"),
        equity_curve=curve,
        fees_paid=Decimal("0"),
        turnover=Decimal("0"),
    )
    assert metrics.return_volatility is not None
    assert vol_matched_buy_and_hold_return(bars=BARS, equity_curve=curve) == (
        vol_matched_from_volatility(bars=BARS, strategy_volatility=metrics.return_volatility)
    )


def test_walk_forward_folds_carry_the_matched_baseline() -> None:
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=1200, seed=4)

    class Engine:
        def run(
            self,
            request: BacktestRequest,
            window: list[OhlcvBar],
            ticks: list[AggTrade] | None = None,
            books: list[OrderBookSnapshot] | None = None,
        ) -> BacktestReport:
            metrics = BacktestMetrics(
                fees_paid=Decimal("0"),
                max_drawdown=Decimal("0"),
                turnover=Decimal("0"),
                sharpe_like=None,
                return_volatility=Decimal("0.001"),
            )
            return BacktestReport(
                fills=2, positions=1, ending_balance=Decimal("101000"), notes="", metrics=metrics
            )

        def run_spread(
            self,
            request: BacktestRequest,
            bars_by_instrument: dict[str, list[OhlcvBar]],
            funding: list[FundingSnapshot] | None = None,
        ) -> BacktestReport:
            raise AssertionError("single instrument only")

    class Feed:
        def load(self, request: BacktestRequest) -> list[OhlcvBar]:
            return bars

        def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
            return {request.instrument_id: bars}

    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=1200,
        starting_equity=Decimal("100000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.005"),
            stop_pct=Decimal("0.01"),
            max_daily_loss=Decimal("0.02"),
            max_drawdown=Decimal("0.06"),
        ),
        robot=RobotName.EMA,
        fast_ema=10,
        slow_ema=20,
    )
    report = RunWalkForward(Engine(), Feed()).execute_multi(
        WalkForwardRequest(backtest=request, folds=2)
    )
    matched = [fold.vol_matched_buy_and_hold_return for fold in report.folds]
    assert all(value is not None for value in matched)
    assert report.mean_vol_matched_buy_and_hold_return is not None
    assert report.beats_vol_matched_buy_and_hold() is not None
    assert "mean_vol_matched_buy_hold=" in report.summary_line()
