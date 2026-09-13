from decimal import Decimal

import pytest

from nautilus_lab.application.dtos import BacktestReport, BacktestRequest
from nautilus_lab.application.risk import evaluate_entry, require_simulated_mode, size_position
from nautilus_lab.application.run_research_backtest import RunResearchBacktest
from nautilus_lab.domain.errors import (
    InvalidRiskError,
    LiveTradingDisabledError,
    PaperTradingNotReadyError,
)
from nautilus_lab.domain.risk import AccountSnapshot, RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode


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


@pytest.mark.parametrize("mode", [TradingMode.LIVE, TradingMode.PAPER])
def test_require_simulated_mode_blocks_non_research(mode: TradingMode) -> None:
    expected = LiveTradingDisabledError if mode is TradingMode.LIVE else PaperTradingNotReadyError
    with pytest.raises(expected):
        require_simulated_mode(mode)


def test_research_use_case_delegates_to_port(limits: RiskLimits) -> None:
    class FakeEngine:
        def run(self, request: BacktestRequest) -> BacktestReport:
            return BacktestReport(
                fills=3, positions=2, ending_balance=Decimal("100100"), notes="ok"
            )

    use_case = RunResearchBacktest(FakeEngine())
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=50,
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


def test_research_use_case_rejects_short_history(limits: RiskLimits) -> None:
    class FakeEngine:
        def run(self, request: BacktestRequest) -> BacktestReport:
            raise AssertionError("engine must not run")

    use_case = RunResearchBacktest(FakeEngine())
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
        def run(self, request: BacktestRequest) -> BacktestReport:
            raise AssertionError("engine must not run")

    use_case = RunResearchBacktest(FakeEngine())
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
