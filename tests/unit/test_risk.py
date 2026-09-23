from decimal import Decimal

import pytest

from nautilus_lab.application.dtos import BacktestReport, BacktestRequest
from nautilus_lab.application.risk import (
    TradeStats,
    evaluate_entry,
    require_simulated_mode,
    resolve_risk_fraction,
    size_position,
)
from nautilus_lab.application.run_research_backtest import RunResearchBacktest
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import (
    InvalidRiskError,
    LiveTradingDisabledError,
)
from nautilus_lab.domain.order_book import OrderBookSnapshot
from nautilus_lab.domain.risk import AccountSnapshot, RiskLimits
from nautilus_lab.domain.risk_overlay import RiskOverlay
from nautilus_lab.domain.ticks import AggTrade
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_ohlcv


@pytest.fixture
def limits() -> RiskLimits:
    return RiskLimits(
        risk_per_trade=Decimal("0.005"),
        stop_pct=Decimal("0.01"),
        max_daily_loss=Decimal("0.02"),
        max_drawdown=Decimal("0.06"),
    )


def test_size_position_risks_fraction_of_equity_capped_at_1x() -> None:
    qty = size_position(
        equity=Decimal("100000"),
        price=Decimal("2000"),
        stop_distance=Decimal("20"),
        risk_fraction=Decimal("0.005"),
        qty_step=Decimal("0.001"),
    )

    assert qty == Decimal("25.000")


def test_size_position_caps_notional_at_equity() -> None:
    qty = size_position(
        equity=Decimal("1000"),
        price=Decimal("100"),
        stop_distance=Decimal("1"),
        risk_fraction=Decimal("1"),
        qty_step=Decimal("0.001"),
    )

    assert qty == Decimal("10.000")


@pytest.mark.parametrize(
    ("equity", "price", "stop", "risk"),
    [
        (Decimal("0"), Decimal("10"), Decimal("1"), Decimal("0.01")),
        (Decimal("100"), Decimal("0"), Decimal("1"), Decimal("0.01")),
        (Decimal("100"), Decimal("10"), Decimal("0"), Decimal("0.01")),
        (Decimal("100"), Decimal("10"), Decimal("1"), Decimal("0")),
        (Decimal("100"), Decimal("10"), Decimal("1"), Decimal("1.5")),
    ],
)
def test_size_position_rejects_invalid_inputs(
    equity: Decimal,
    price: Decimal,
    stop: Decimal,
    risk: Decimal,
) -> None:
    with pytest.raises(InvalidRiskError):
        size_position(
            equity=equity,
            price=price,
            stop_distance=stop,
            risk_fraction=risk,
            qty_step=Decimal("0.001"),
        )


def test_size_position_rejects_invalid_qty_step() -> None:
    with pytest.raises(InvalidRiskError, match="qty_step"):
        size_position(
            equity=Decimal("100"),
            price=Decimal("10"),
            stop_distance=Decimal("1"),
            risk_fraction=Decimal("0.01"),
            qty_step=Decimal("0"),
        )


def test_evaluate_entry_allows_healthy_account(limits: RiskLimits) -> None:
    snapshot = AccountSnapshot(
        equity=Decimal("100000"),
        peak_equity=Decimal("100000"),
        day_start_equity=Decimal("100000"),
        open_positions=0,
    )

    decision = evaluate_entry(snapshot, limits)

    assert decision.allowed is True
    assert decision.reason == "ok"


def test_evaluate_entry_trips_daily_loss(limits: RiskLimits) -> None:
    snapshot = AccountSnapshot(
        equity=Decimal("97000"),
        peak_equity=Decimal("100000"),
        day_start_equity=Decimal("100000"),
        open_positions=0,
    )

    decision = evaluate_entry(snapshot, limits)

    assert decision.allowed is False
    assert "daily loss" in decision.reason


def test_evaluate_entry_trips_drawdown(limits: RiskLimits) -> None:
    snapshot = AccountSnapshot(
        equity=Decimal("93000"),
        peak_equity=Decimal("100000"),
        day_start_equity=Decimal("93000"),
        open_positions=0,
    )

    decision = evaluate_entry(snapshot, limits)

    assert decision.allowed is False
    assert "drawdown" in decision.reason


@pytest.mark.parametrize(
    "snapshot",
    [
        AccountSnapshot(
            equity=Decimal("0"),
            peak_equity=Decimal("1"),
            day_start_equity=Decimal("1"),
            open_positions=0,
        ),
        AccountSnapshot(
            equity=Decimal("1"),
            peak_equity=Decimal("0"),
            day_start_equity=Decimal("1"),
            open_positions=0,
        ),
        AccountSnapshot(
            equity=Decimal("1"),
            peak_equity=Decimal("1"),
            day_start_equity=Decimal("0"),
            open_positions=0,
        ),
        AccountSnapshot(
            equity=Decimal("1"),
            peak_equity=Decimal("1"),
            day_start_equity=Decimal("1"),
            open_positions=2,
        ),
    ],
)
def test_evaluate_entry_rejects_broken_account(
    snapshot: AccountSnapshot,
    limits: RiskLimits,
) -> None:
    assert evaluate_entry(snapshot, limits).allowed is False


def test_invalid_risk_limits_are_rejected() -> None:
    with pytest.raises(InvalidRiskError):
        RiskLimits(
            risk_per_trade=Decimal("0"),
            stop_pct=Decimal("0.01"),
            max_daily_loss=Decimal("0.02"),
            max_drawdown=Decimal("0.06"),
        )
    with pytest.raises(InvalidRiskError, match="max_open_positions"):
        RiskLimits(
            risk_per_trade=Decimal("0.01"),
            stop_pct=Decimal("0.01"),
            max_daily_loss=Decimal("0.02"),
            max_drawdown=Decimal("0.06"),
            max_open_positions=0,
        )


def test_require_simulated_mode_blocks_live() -> None:
    with pytest.raises(LiveTradingDisabledError):
        require_simulated_mode(TradingMode.LIVE)


def test_require_simulated_mode_allows_paper() -> None:
    require_simulated_mode(TradingMode.PAPER)


def test_research_use_case_delegates_to_port(limits: RiskLimits) -> None:
    class FakeEngine:
        def run(
            self,
            request: BacktestRequest,
            bars: list[OhlcvBar],
            ticks: list[AggTrade] | None = None,
            books: list[OrderBookSnapshot] | None = None,
        ) -> BacktestReport:
            assert len(bars) == 150
            return BacktestReport(
                fills=3, positions=2, ending_balance=Decimal("100100"), notes="ok"
            )

        def run_spread(
            self,
            request: BacktestRequest,
            bars_by_instrument: dict[str, list[OhlcvBar]],
        ) -> BacktestReport:
            raise AssertionError("spread engine must not run")

    use_case = RunResearchBacktest(FakeEngine(), _CountFeed())
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=150,
        starting_equity=Decimal("100000"),
        risk=limits,
        fast_ema=10,
        slow_ema=20,
    )

    report = use_case.execute(request)

    assert report.fills == 3
    assert report.ending_balance == Decimal("100100")


def test_require_simulated_mode_allows_research() -> None:
    require_simulated_mode(TradingMode.RESEARCH)


def test_resolve_risk_fraction_applies_vol_scaling_when_enabled(limits: RiskLimits) -> None:
    overlay = RiskOverlay(use_vol_scaling=True, vol_scaling_target=Decimal("0.02"))
    scaled = resolve_risk_fraction(
        limits,
        overlay,
        forecast_vol=Decimal("0.04"),
    )
    assert scaled < limits.risk_per_trade


def test_resolve_risk_fraction_kelly_requires_min_trades(limits: RiskLimits) -> None:
    overlay = RiskOverlay(use_fractional_kelly=True, kelly_min_trades=30)
    stats = TradeStats(wins=20, losses=5, gross_profit=Decimal("1000"), gross_loss=Decimal("200"))
    unchanged = resolve_risk_fraction(limits, overlay, stats=stats)
    assert unchanged == limits.risk_per_trade


def test_evaluate_entry_trips_cvar_breaker(limits: RiskLimits) -> None:
    overlay = RiskOverlay(use_cvar_breaker=True, max_cvar_99=Decimal("0.02"))
    snapshot = AccountSnapshot(
        equity=Decimal("99500"),
        peak_equity=Decimal("100000"),
        day_start_equity=Decimal("100000"),
        open_positions=0,
        recent_returns=tuple(Decimal(x) for x in ("-0.025", "-0.024", "-0.023", "0.01")),
    )
    decision = evaluate_entry(snapshot, limits, overlay)
    assert decision.allowed is False
    assert "CVaR" in decision.reason


def test_research_use_case_rejects_short_history(limits: RiskLimits) -> None:
    class FakeEngine:
        def run(
            self,
            request: BacktestRequest,
            bars: list[OhlcvBar],
            ticks: list[AggTrade] | None = None,
            books: list[OrderBookSnapshot] | None = None,
        ) -> BacktestReport:
            raise AssertionError("engine must not run")

        def run_spread(
            self,
            request: BacktestRequest,
            bars_by_instrument: dict[str, list[OhlcvBar]],
        ) -> BacktestReport:
            raise AssertionError("engine must not run")

    use_case = RunResearchBacktest(FakeEngine(), _CountFeed())
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=10,
        starting_equity=Decimal("100000"),
        risk=limits,
        fast_ema=10,
        slow_ema=20,
    )

    with pytest.raises(ValueError, match="bar_count"):
        use_case.execute(request)


def test_research_use_case_rejects_live(limits: RiskLimits) -> None:
    class FakeEngine:
        def run(
            self,
            request: BacktestRequest,
            bars: list[OhlcvBar],
            ticks: list[AggTrade] | None = None,
            books: list[OrderBookSnapshot] | None = None,
        ) -> BacktestReport:
            raise AssertionError("engine must not run")

        def run_spread(
            self,
            request: BacktestRequest,
            bars_by_instrument: dict[str, list[OhlcvBar]],
        ) -> BacktestReport:
            raise AssertionError("engine must not run")

    use_case = RunResearchBacktest(FakeEngine(), _CountFeed())
    request = BacktestRequest(
        mode=TradingMode.LIVE,
        instrument_id="ETH/USDT.SIM",
        bar_count=50,
        starting_equity=Decimal("100000"),
        risk=limits,
        fast_ema=10,
        slow_ema=20,
    )

    with pytest.raises(LiveTradingDisabledError):
        use_case.execute(request)


class _CountFeed:
    def load(self, request: BacktestRequest) -> list[OhlcvBar]:
        return synthetic_ohlcv(
            instrument_id=request.instrument_id,
            count=max(request.bar_count, 1),
            seed=1,
        )

    def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
        return {request.instrument_id: self.load(request)}
