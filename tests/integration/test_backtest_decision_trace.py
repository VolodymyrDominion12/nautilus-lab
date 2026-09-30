"""The research backtest writes the same `decision_trace/1` bar record as live paper.

Before 2026-09-28 `signal_strategy.py::_record_decision_log` computed the robot's
`steps` but never put them into the `DecisionRecord`, wrote `narrative=""` and no
`account`/`bar`/`config_hash`. The dashboard's Backtest Details and the decision
digest therefore lost the "why" for every research run. These tests pin the parity
with the live paper terminal (`tests/unit/test_decision_trace.py`).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from nautilus_lab.application.decision_trace_codec import record_to_dict
from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.decision_log import DecisionRecord
from nautilus_lab.domain.decision_trace import Stage
from nautilus_lab.domain.order_book import BookLevel, OrderBookSnapshot
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.risk_overlay import RiskOverlay
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.decision_log_writer import DecimalEncoder
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_ohlcv


class InMemoryDecisionLog:
    def __init__(self) -> None:
        self.records: list[DecisionRecord] = []

    def log(self, record: DecisionRecord) -> None:
        self.records.append(record)


@pytest.mark.integration
def test_backtest_records_carry_the_full_decision_trace() -> None:
    """A research run explains every bar with steps, narrative, account, bar and config."""
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=400, seed=11)
    log = InMemoryDecisionLog()
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=len(bars),
        starting_equity=Decimal("10000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.01"),
            stop_pct=Decimal("0.02"),
            max_daily_loss=Decimal("0.02"),
            max_drawdown=Decimal("0.06"),
        ),
        robot=RobotName.REGIME,
        seed=11,
        source=BarOrigin.SYNTHETIC,
        session_id="bt-decision-trace-test",
    )
    NautilusResearchBacktest(decision_log=log).run(request, bars)

    decisions = [r for r in log.records if r.kind.value == "bar_decision"]
    assert decisions, "the run must write bar_decision records"

    # The chain, the rendered text, the OHLC, the account and the config id must all be
    # present — not silently dropped like the pre-2026-09-28 backtest record.
    assert any(r.steps for r in decisions), "records must carry the decision chain"
    assert all(r.narrative for r in decisions), "records must carry a rendered narrative"
    assert all(r.bar for r in decisions), "records must carry the bar OHLC"
    assert all(r.account for r in decisions), "records must carry the account snapshot"
    assert all(r.config_hash for r in decisions), "records must carry the config hash"

    # The account snapshot uses the same shape as the paper terminal (position + equity).
    assert any(
        r.account["position"] in {"LONG", "SHORT", "FLAT"} and "equity" in r.account
        for r in decisions
    )

    # A signal bar explains plan and execution/gate steps, not only regime/strategy.
    assert any(
        any(s.stage in {Stage.PLAN, Stage.GATE, Stage.EXECUTION} for s in r.steps)
        for r in decisions
    )


@pytest.mark.integration
def test_backtest_blocked_by_uses_the_structured_vocabulary() -> None:
    """`blocked_by` on a refused entry is `risk.<code>`/`execution.*`, never raw prose.

    Whether this synthetic series refuses an entry depends on the seed; when it does,
    the record must carry the structured label (not the human sentence) so the digest
    counts one breaker. The mapping itself is unit-tested in
    `tests/unit/test_decision_trace.py::test_blocked_by_label_uses_the_structured_vocabulary`.
    """
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=400, seed=11)
    log = InMemoryDecisionLog()
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=len(bars),
        starting_equity=Decimal("10000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.01"),
            stop_pct=Decimal("0.02"),
            max_daily_loss=Decimal("0.02"),
            max_drawdown=Decimal("0.06"),
        ),
        robot=RobotName.REGIME,
        seed=11,
        source=BarOrigin.SYNTHETIC,
        session_id="bt-decision-blocked-test",
    )
    NautilusResearchBacktest(decision_log=log).run(request, bars)

    blocked = [r for r in log.records if r.outcome == "ENTRY_BLOCKED_RISK"]
    if not blocked:
        pytest.skip("this synthetic series produced no refused entry")
    for record in blocked:
        assert record.blocked_by, "a refused entry must say what refused it"
        assert record.blocked_by.startswith("risk.") or record.blocked_by.startswith(
            "execution."
        ), f"blocked_by {record.blocked_by!r} is not structured"


# --- protective-stop intrabar -------------------------------------------------


def _always_up_model(tmp_path: Path) -> str:
    """A 5-feature, 3-class booster whose labels are all "up" — the strategy never exits."""
    lgb = pytest.importorskip("lightgbm")
    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(7)
    labels = np.full(300, 2, dtype=np.int32)
    labels[:3] = (0, 1, 0)  # every class present, "up" overwhelming
    booster = lgb.train(
        {"objective": "multiclass", "num_class": 3, "verbosity": -1},
        lgb.Dataset(rng.normal(size=(300, 5)), label=labels),
        num_boost_round=20,
    )
    path = tmp_path / "always_up.txt"
    booster.save_model(str(path))
    return str(path)


def _falling_bars(count: int = 20) -> list[OhlcvBar]:
    bars: list[OhlcvBar] = []
    price = Decimal("3500")
    start = datetime(2024, 1, 1, tzinfo=UTC)
    for index in range(count):
        close = (price * Decimal("0.99")).quantize(Decimal("0.01"))
        bars.append(
            OhlcvBar(
                instrument_id="ETH/USDT.SIM",
                ts_utc=start + timedelta(minutes=index + 1),
                open=price,
                high=price,
                low=close,
                close=close,
                volume=Decimal("100"),
            )
        )
        price = close
    return bars


def _bid_heavy_books(bars: list[OhlcvBar], per_bar: int = 20) -> list[OrderBookSnapshot]:
    return [
        OrderBookSnapshot(
            instrument_id=bar.instrument_id,
            ts_utc=bar.ts_utc + timedelta(seconds=step),
            bids=tuple(
                BookLevel(price=bar.close - Decimal("0.1") * (index + 1), size=Decimal("30"))
                for index in range(10)
            ),
            asks=tuple(
                BookLevel(price=bar.close + Decimal("0.1") * (index + 1), size=Decimal("5"))
                for index in range(10)
            ),
        )
        for bar in bars
        for step in range(per_bar)
    ]


@pytest.mark.integration
def test_backtest_records_a_protective_stop_as_intrabar(tmp_path: Path) -> None:
    """A protective-stop fill is recorded as an intrabar `STOP_LOSS`, not lost.

    The fixture enters long on every book update (ml_obi always says "up") while the
    price falls 1% per bar, so the reduce-only stop is the only thing that closes the
    position. Without this record the decision log has no exit and the reconstructed
    trade is read as still-open.
    """
    model_path = _always_up_model(tmp_path)
    bars = _falling_bars()
    books = _bid_heavy_books(bars)
    log = InMemoryDecisionLog()
    request = BacktestRequest(
        mode=TradingMode.PAPER,
        instrument_id="ETH/USDT.SIM",
        bar_count=len(bars),
        starting_equity=Decimal("100000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.005"),
            stop_pct=Decimal("0.01"),
            max_daily_loss=Decimal("0.5"),
            max_drawdown=Decimal("0.5"),
            max_var_99=Decimal("1"),
        ),
        risk_overlay=replace(RiskOverlay(), use_protective_stop=True),
        robot=RobotName.ML_OBI,
        ml_obi_model_path=model_path,
        seed=7,
        source=BarOrigin.SYNTHETIC,
        session_id="bt-stop-intrabar-test",
    )
    NautilusResearchBacktest(decision_log=log).run_paper(request, bars, None, books)

    stops = [r for r in log.records if r.outcome == "STOP_LOSS"]
    assert stops, "the falling-price fixture must trip the protective stop"
    for record in stops:
        assert record.kind.value == "intrabar"
        assert record.narrative
        assert "Стоп-лос" in record.narrative
        stop_step = record.steps[0]
        assert stop_step.component == "stop_loss"
        assert "level" in stop_step.values
        # The JSONL writer, not just the in-memory record: `DecimalEncoder` refuses any
        # value that is not JSON-native, and a refusal means the exit never reaches the
        # journal at all (2026-09-29: `qty` was a Nautilus `Quantity` and 101 records of
        # one sweep run were lost to "Object of type Quantity is not JSON serializable").
        json.dumps(record_to_dict(record), cls=DecimalEncoder)
        assert isinstance(stop_step.values["qty"], Decimal)


# --- trade lifecycle (docs/30) ------------------------------------------------


def _lifecycle_run(*, use_ratchet: bool) -> list[DecisionRecord]:
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=400, seed=11)
    log = InMemoryDecisionLog()
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=len(bars),
        starting_equity=Decimal("10000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.01"),
            stop_pct=Decimal("0.02"),
            max_daily_loss=Decimal("0.5"),
            max_drawdown=Decimal("0.5"),
        ),
        risk_overlay=replace(RiskOverlay(), use_protective_stop=True, use_ratchet=use_ratchet),
        robot=RobotName.EMA,
        seed=11,
        source=BarOrigin.SYNTHETIC,
        session_id=f"bt-lifecycle-{use_ratchet}",
    )
    NautilusResearchBacktest(decision_log=log).run(request, bars)
    return log.records


@pytest.mark.integration
def test_backtest_logs_the_entry_fill_with_its_stop_level() -> None:
    """Every entry fill is an intrabar `ENTRY_FILLED` with price, size and the stop.

    Before this record a backtest trade had no stop level at all (only `stop_distance`
    on the decision bar), so the trade page drew no SL line and computed no R.
    """
    records = _lifecycle_run(use_ratchet=False)
    fills = [r for r in records if r.outcome == "ENTRY_FILLED"]
    assert fills, "an always-in-market EMA run must fill entries"
    for record in fills:
        assert record.kind.value == "intrabar"
        fill = next(s for s in record.steps if s.result == "entry_filled")
        assert fill.values["fill_price"] > 0
        assert isinstance(fill.values["qty"], Decimal)
        assert "stop_loss" in record.states
        json.dumps(record_to_dict(record), cls=DecimalEncoder)
    # While a position is open the bar records carry the stop that binds it.
    held = [
        r
        for r in records
        if r.kind.value == "bar_decision" and r.account.get("position") in ("LONG", "SHORT")
    ]
    assert held
    assert all("stop_loss" in r.states for r in held)


@pytest.mark.integration
def test_backtest_does_not_count_a_pending_entry_as_a_risk_block() -> None:
    """The bar after an entry, while its order is in flight, is `PENDING_FILL`."""
    records = _lifecycle_run(use_ratchet=False)
    assert not [r for r in records if r.blocked_by == "execution.order_working"]
    assert all(r.regime != "UNKNOWN" for r in records), "ema has no regime: ''"


@pytest.mark.integration
def test_backtest_names_a_ratchet_exit() -> None:
    records = _lifecycle_run(use_ratchet=True)
    ratchet_steps = [s for r in records for s in r.steps if s.component == "ratchet"]
    assert ratchet_steps, "a held position must show the ratchet level on each bar"
    exits = [r for r in records if r.outcome == "RATCHET_EXIT"]
    for record in exits:
        assert any(s.component == "ratchet" for s in record.steps)
    # A ratchet exit is never logged as a bare EXIT any more.
    for record in records:
        if record.outcome == "EXIT":
            assert not [s for s in record.steps if s.component == "ratchet" and s.result == "exit"]
