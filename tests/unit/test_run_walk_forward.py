from datetime import datetime
from decimal import Decimal

from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    WalkForwardRequest,
    selected_from_request,
)
from nautilus_lab.application.run_walk_forward import RunWalkForward
from nautilus_lab.application.score import in_sample_score
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_ohlcv


def _limits() -> RiskLimits:
    return RiskLimits(
        risk_per_trade=Decimal("0.005"),
        stop_pct=Decimal("0.01"),
        max_daily_loss=Decimal("0.02"),
        max_drawdown=Decimal("0.06"),
    )


def test_walk_forward_selects_on_in_sample_and_reports_out_of_sample() -> None:
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=200, seed=3)
    is_start = bars[0].ts_utc

    class RecordingEngine:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int, datetime, int]] = []

        def run(self, request: BacktestRequest, folded: list[OhlcvBar]) -> BacktestReport:
            self.calls.append((request.fast_ema, request.slow_ema, folded[0].ts_utc, len(folded)))
            in_sample = folded[0].ts_utc == is_start
            if request.fast_ema == 5:
                balance = Decimal("120000") if in_sample else Decimal("90000")
            elif request.fast_ema == 10 and request.slow_ema == 20:
                balance = Decimal("110000") if in_sample else Decimal("105000")
            else:
                balance = Decimal("100000")
            return BacktestReport(fills=1, positions=1, ending_balance=balance, notes="fake")

        def run_spread(
            self,
            request: BacktestRequest,
            bars_by_instrument: dict[str, list[OhlcvBar]],
        ) -> BacktestReport:
            raise AssertionError("spread engine must not run")

    class FixedFeed:
        def load(self, request: BacktestRequest) -> list[OhlcvBar]:
            return bars

        def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
            return {request.instrument_id: bars}

    engine = RecordingEngine()
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=200,
        starting_equity=Decimal("100000"),
        risk=_limits(),
        robot=RobotName.EMA,
        fast_ema=10,
        slow_ema=20,
    )
    report = RunWalkForward(engine, FixedFeed()).execute(WalkForwardRequest(backtest=request))

    assert report.selected.fast_ema == 5
    assert report.selected.slow_ema == 20
    assert report.in_sample.ending_balance == Decimal("120000")
    assert report.out_of_sample.ending_balance == Decimal("90000")
    assert report.candidates_tried == 4
    assert "out-of-sample" in report.notes
    last = engine.calls[-1]
    assert last[0] == 5
    assert last[1] == 20
    assert last[2] != is_start


def test_in_sample_score_ranks_missing_balance_last() -> None:
    missing = BacktestReport(fills=0, positions=0, ending_balance=None, notes="")
    present = BacktestReport(fills=0, positions=0, ending_balance=Decimal("1"), notes="")
    assert in_sample_score(missing) < in_sample_score(present)


def test_selected_from_request_copies_regime_fields() -> None:
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=200,
        starting_equity=Decimal("100000"),
        risk=_limits(),
    )
    selected = selected_from_request(request)
    assert selected.donchian_period == request.regime.donchian_period
    assert selected.bb_k == request.regime.bb_k
