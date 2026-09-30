"""Pairs and funding write decision records in a real engine run (docs/30).

The 2026-09-29 sweep produced 0-byte journals for both: `SpreadRobot` and `FundingRobot`
had no decision log. These runs pin that every decision now lands, with its trace, and
that the records serialise (a record the JSONL writer refuses is a record lost).
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from nautilus_lab.application.decision_trace_codec import record_to_dict
from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.domain.bars import BarOrigin
from nautilus_lab.domain.decision_log import DecisionRecord
from nautilus_lab.domain.funding import FundingParams
from nautilus_lab.domain.pairs.params import PairsParams
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.decision_log_writer import DecimalEncoder
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest
from nautilus_lab.infrastructure.nautilus.synthetic_pairs import (
    synthetic_cointegrated_pair,
    synthetic_funding_pair,
)


class _Memory:
    def __init__(self) -> None:
        self.records: list[DecisionRecord] = []

    def log(self, record: DecisionRecord) -> None:
        self.records.append(record)


def _limits() -> RiskLimits:
    return RiskLimits(
        risk_per_trade=Decimal("0.005"),
        stop_pct=Decimal("0.01"),
        max_daily_loss=Decimal("0.5"),
        max_drawdown=Decimal("0.5"),
    )


def _serialisable(records: list[DecisionRecord]) -> None:
    for record in records:
        json.dumps(record_to_dict(record), cls=DecimalEncoder)


@pytest.mark.integration
def test_pairs_run_writes_a_record_per_aligned_bar() -> None:
    bars = synthetic_cointegrated_pair(leg_a="ETH/USDT.SIM", leg_b="BTC/USDT.SIM", count=600)
    log = _Memory()
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=600,
        starting_equity=Decimal("100000"),
        risk=_limits(),
        robot=RobotName.PAIRS,
        source=BarOrigin.SYNTHETIC,
        pairs=PairsParams(lookback=120),
        session_id="pairs-log-test",
    )
    NautilusResearchBacktest(decision_log=log).run_spread(request, bars)

    assert len(log.records) >= 500, "one record per aligned bar pair"
    assert all(r.robot == "pairs" for r in log.records)
    assert all(r.narrative for r in log.records)
    components = {s.component for r in log.records for s in r.steps}
    assert "cointegration" in components
    assert "PairsTrading" in components
    opened = [r for r in log.records if r.outcome in ("ENTRY_OPENED", "REVERSE")]
    for record in opened:
        legs = [s for s in record.steps if s.result == "entry"]
        assert {s.values["leg"] for s in legs} == {"A", "B"}
    _serialisable(log.records)


@pytest.mark.integration
def test_funding_run_writes_a_record_per_settlement() -> None:
    bars, funding = synthetic_funding_pair(
        spot_id="ETH/USDT.SIM", perp_id="ETHUSDT-PERP.SIM", count=200, seed=42
    )
    log = _Memory()
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=200,
        starting_equity=Decimal("100000"),
        risk=_limits(),
        robot=RobotName.FUNDING,
        source=BarOrigin.SYNTHETIC,
        funding=FundingParams(min_net_apy=Decimal("0.10")),
        funding_spot_id="ETH/USDT.SIM",
        funding_perp_id="ETHUSDT-PERP.SIM",
        session_id="funding-log-test",
    )
    NautilusResearchBacktest(decision_log=log).run_spread(request, bars, funding=funding)

    assert log.records, "every funding settlement must be explained"
    carry = [s for r in log.records for s in r.steps if s.component == "FundingCarry"]
    assert carry
    assert all("net_apy" in s.values for s in carry)
    assert all(s.thresholds.get("min_net_apy") == Decimal("0.10") for s in carry)
    _serialisable(log.records)


@pytest.mark.integration
def test_funding_warmup_does_not_poison_oos() -> None:
    bars, funding = synthetic_funding_pair(
        spot_id="ETH/USDT.SIM", perp_id="ETHUSDT-PERP.SIM", count=200, seed=42
    )
    log = _Memory()
    trade_start = bars["ETH/USDT.SIM"][30].ts_utc
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=200,
        starting_equity=Decimal("100000"),
        risk=_limits(),
        robot=RobotName.FUNDING,
        source=BarOrigin.SYNTHETIC,
        funding=FundingParams(min_net_apy=Decimal("0.05")),
        funding_spot_id="ETH/USDT.SIM",
        funding_perp_id="ETHUSDT-PERP.SIM",
        session_id="funding-warmup-test",
        trade_start=trade_start,
    )
    report = NautilusResearchBacktest(decision_log=log).run_spread(request, bars, funding=funding)
    warmup_records = [r for r in log.records if r.outcome == "WARMUP"]
    assert warmup_records, "should have warmup records before trade_start"
    assert report.fills > 0, "robot must trade in OOS after warmup without phantom position lock"
