"""Pairs and funding explain their decisions; walk-forward can log only OOS (docs/30).

The 2026-09-29 sweep wrote 0-byte journals for `pairs` and `funding`: neither adapter
had a decision log. And a walk-forward with the journal on logged every in-sample grid
candidate, which is why the sweep needed a second pass per robot.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_lab.application.decision_narrative import render_narrative
from nautilus_lab.application.dtos import BacktestReport, BacktestRequest, WalkForwardRequest
from nautilus_lab.application.run_walk_forward import RunWalkForward
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.decision_trace import Stage, Verdict
from nautilus_lab.domain.funding import FundingCashAndCarry, FundingParams, FundingSnapshot
from nautilus_lab.domain.order_book import OrderBookSnapshot
from nautilus_lab.domain.pairs.pairs_trading import PairsTrading
from nautilus_lab.domain.pairs.params import PairsParams
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.ticks import AggTrade
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_ohlcv

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _bar(instrument: str, index: int, close: Decimal) -> OhlcvBar:
    return OhlcvBar(
        instrument_id=instrument,
        ts_utc=T0 + timedelta(hours=index),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=Decimal("10"),
    )


def _snapshot(rate: str, *, index: Decimal | None = Decimal("100")) -> FundingSnapshot:
    return FundingSnapshot(
        instrument="ETHUSDT-PERP.SIM",
        funding_rate=Decimal(rate),
        mark_price=Decimal("100"),
        index_price=index,
        ts_utc=T0,
    )


# --- funding ------------------------------------------------------------------------


def test_funding_names_the_apy_gate_it_fails() -> None:
    robot = FundingCashAndCarry(
        spot_id="ETH/USDT.SIM", perp_id="ETHUSDT-PERP.SIM", params=FundingParams()
    )
    assert robot.on_funding(_snapshot("0.00005")) is None
    (item,) = robot.last_trace
    assert item.component == "FundingCarry"
    assert item.verdict is Verdict.INFO
    assert item.values["net_apy"] < item.thresholds["min_net_apy"]
    assert item.values["apy_margin_pct"] < 0
    assert "min_net_apy" in (item.note or "")


def test_funding_open_and_close_are_explained() -> None:
    robot = FundingCashAndCarry(
        spot_id="ETH/USDT.SIM", perp_id="ETHUSDT-PERP.SIM", params=FundingParams()
    )
    assert robot.on_funding(_snapshot("0.001")) is not None
    assert robot.last_trace[0].verdict is Verdict.EMIT
    assert robot.last_trace[0].result == "buy"
    closed = robot.on_funding(_snapshot("-0.0001"))
    assert closed is not None
    assert robot.last_trace[0].result == "flat"


def test_funding_without_index_is_a_skip_not_a_zero_basis() -> None:
    robot = FundingCashAndCarry(
        spot_id="ETH/USDT.SIM", perp_id="ETHUSDT-PERP.SIM", params=FundingParams()
    )
    assert robot.on_funding(_snapshot("0.001", index=None)) is None
    assert robot.last_trace[0].verdict is Verdict.SKIP


# --- pairs --------------------------------------------------------------------------


def _pairs(count: int, *, lookback: int = 30) -> tuple[PairsTrading, list]:
    robot = PairsTrading(
        leg_a="ETH/USDT.SIM",
        leg_b="BTC/USDT.SIM",
        params=PairsParams(lookback=lookback, max_half_life_bars=1000),
    )
    traces = []
    for index in range(count):
        # B trends; A = 2·B + a mean-reverting wiggle: cointegrated by construction.
        price_b = Decimal("100") + Decimal(index) / Decimal("10")
        wiggle = Decimal("3") * (Decimal(1) if index % 4 < 2 else Decimal(-1))
        price_a = Decimal("2") * price_b + wiggle
        robot.on_bars(_bar("ETH/USDT.SIM", index, price_a), _bar("BTC/USDT.SIM", index, price_b))
        traces.append(robot.last_trace)
    return robot, traces


def test_pairs_warmup_then_fit_gate_then_z_leg() -> None:
    _robot, traces = _pairs(60)
    assert traces[0][0].stage is Stage.WARMUP
    after = traces[-1]
    assert after[0].component == "cointegration"
    assert "adf_pvalue" in after[0].values
    assert after[0].thresholds["adf_pvalue_max"] == Decimal("0.05")
    assert after[0].verdict is Verdict.PASS, "the fixture is cointegrated by construction"
    z_step = after[1]
    assert z_step.component == "PairsTrading"
    assert "z" in z_step.values
    assert "z_margin_pct" in z_step.values
    assert {"z_low", "z_high", "z_exit"} <= set(z_step.thresholds)


def test_pairs_fit_failure_is_explained() -> None:
    robot = PairsTrading(
        leg_a="ETH/USDT.SIM",
        leg_b="BTC/USDT.SIM",
        params=PairsParams(lookback=30, adf_pvalue_max=Decimal("0.0000001")),
    )
    for index in range(40):
        robot.on_bars(
            _bar("ETH/USDT.SIM", index, Decimal(100 + index % 7)),
            _bar("BTC/USDT.SIM", index, Decimal(50 + index % 5)),
        )
    fit = robot.last_trace[0]
    assert fit.component == "cointegration"
    assert fit.verdict is Verdict.INFO
    assert fit.result == "not_cointegrated"
    assert "adf_pvalue" in fit.values


def test_narrative_renders_pairs_and_funding_steps() -> None:
    robot = FundingCashAndCarry(
        spot_id="ETH/USDT.SIM", perp_id="ETHUSDT-PERP.SIM", params=FundingParams()
    )
    robot.on_funding(_snapshot("0.00005"))
    step_ = robot.last_trace[0]
    row = {
        "ts": T0.isoformat(),
        "instrument": "ETH/USDT.SIM",
        "close": 100,
        "outcome": "NO_SIGNAL",
        "steps": [
            {
                "stage": step_.stage.value,
                "component": step_.component,
                "verdict": step_.verdict.value,
                "result": step_.result,
                "values": {k: float(v) for k, v in step_.values.items() if isinstance(v, Decimal)},
                "thresholds": {
                    k: float(v) for k, v in step_.thresholds.items() if isinstance(v, Decimal)
                },
                "note": step_.note,
            }
        ],
    }
    text = render_narrative(row)
    assert "Funding" in text
    assert "APY" in text


# --- walk-forward decision_log_scope ------------------------------------------------


def _limits() -> RiskLimits:
    return RiskLimits(
        risk_per_trade=Decimal("0.005"),
        stop_pct=Decimal("0.01"),
        max_daily_loss=Decimal("0.02"),
        max_drawdown=Decimal("0.06"),
    )


class _SessionEngine:
    def __init__(self) -> None:
        self.sessions: list[str | None] = []

    def run(
        self,
        request: BacktestRequest,
        folded: list[OhlcvBar],
        ticks: list[AggTrade] | None = None,
        books: list[OrderBookSnapshot] | None = None,
    ) -> BacktestReport:
        self.sessions.append(request.session_id)
        return BacktestReport(
            fills=1,
            positions=1,
            ending_balance=Decimal("100000"),
            notes="fake",
            session_id=request.session_id,
        )

    def run_spread(self, *args: object, **kwargs: object) -> BacktestReport:
        raise AssertionError("spread engine must not run")


class _Feed:
    def __init__(self, bars: list[OhlcvBar]) -> None:
        self._bars = bars

    def load(self, request: BacktestRequest) -> list[OhlcvBar]:
        return self._bars

    def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
        return {request.instrument_id: self._bars}


def _wf(scope: str) -> tuple[_SessionEngine, object]:
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=800, seed=5)
    engine = _SessionEngine()
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=len(bars),
        starting_equity=Decimal("100000"),
        risk=_limits(),
        robot=RobotName.EMA,
        session_id="batch-cell",
    )
    report = RunWalkForward(engine, _Feed(bars)).execute_multi(
        WalkForwardRequest(backtest=request, folds=2, decision_log_scope=scope)
    )
    return engine, report


def test_oos_scope_keeps_the_grid_out_of_the_journal() -> None:
    engine, report = _wf("oos")
    logged = [s for s in engine.sessions if s is not None]
    assert logged == ["batch-cell-f0", "batch-cell-f1"]
    assert [fold.out_of_sample.session_id for fold in report.folds] == logged


def test_all_scope_is_the_legacy_behaviour() -> None:
    engine, _report = _wf("all")
    assert set(engine.sessions) == {"batch-cell"}
