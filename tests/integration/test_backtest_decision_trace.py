"""The research backtest writes the same `decision_trace/1` bar record as live paper.

Before 2026-09-28 `signal_strategy.py::_record_decision_log` computed the robot's
`steps` but never put them into the `DecisionRecord`, wrote `narrative=""` and no
`account`/`bar`/`config_hash`. The dashboard's Backtest Details and the decision
digest therefore lost the "why" for every research run. These tests pin the parity
with the live paper terminal (`tests/unit/test_decision_trace.py`).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.domain.bars import BarOrigin
from nautilus_lab.domain.decision_log import DecisionRecord
from nautilus_lab.domain.decision_trace import Stage
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
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
