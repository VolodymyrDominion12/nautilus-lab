"""DSR deflated by every trial ever run on the data, not just this run's grid (docs/27 R-3)."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    OverfitAuditReport,
    OverfitAuditRequest,
    WalkForwardRequest,
)
from nautilus_lab.application.run_overfitting_audit import RunOverfitAudit
from nautilus_lab.application.run_research_backtest import minimum_bars
from nautilus_lab.application.run_walk_forward import RunWalkForward
from nautilus_lab.application.trial_ledger import (
    InMemoryTrialLedger,
    dataset_key,
    record_trials,
    trial_id,
)
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.deflated_sharpe import deflated_sharpe_ratio
from nautilus_lab.domain.order_book import OrderBookSnapshot
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.ticks import AggTrade
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_ohlcv
from nautilus_lab.infrastructure.trial_ledger import JsonlTrialLedger

BAR_TYPE = "ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL"


def _request(source: BarOrigin = BarOrigin.CATALOG, bar_count: int = 200) -> BacktestRequest:
    return BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=bar_count,
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
        source=source,
        bar_type=BAR_TYPE,
    )


class _Feed:
    def __init__(self, bars: list[OhlcvBar]) -> None:
        self.bars = bars

    def load(self, request: BacktestRequest) -> list[OhlcvBar]:
        return self.bars

    def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
        return {request.instrument_id: self.bars}


class _Engine:
    """Returns that differ by configuration and by block, so every Sharpe is defined."""

    def run(
        self,
        request: BacktestRequest,
        bars: list[OhlcvBar],
        ticks: list[AggTrade] | None = None,
        books: list[OrderBookSnapshot] | None = None,
    ) -> BacktestReport:
        drift = Decimal(request.fast_ema) * Decimal("10") + Decimal(request.slow_ema)
        wobble = bars[-1].close - bars[0].close
        balance = Decimal("100000") + drift * Decimal("7") + wobble * Decimal("40")
        return BacktestReport(fills=3, positions=1, ending_balance=balance, notes="fake")

    def run_spread(
        self, request: BacktestRequest, bars_by_instrument: dict[str, list[OhlcvBar]]
    ) -> BacktestReport:
        raise AssertionError("no pairs here")


def _audit(
    ledger: InMemoryTrialLedger | None, source: BarOrigin = BarOrigin.CATALOG
) -> OverfitAuditReport:
    blocks = 8
    count = minimum_bars(RobotName.EMA) * blocks + blocks
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=count, seed=11)
    use_case = RunOverfitAudit(_Engine(), _Feed(bars), trial_ledger=ledger)
    return use_case.execute(
        OverfitAuditRequest(backtest=_request(source, bar_count=count), blocks=blocks)
    )


# ---- the ledger ------------------------------------------------------------------------


def test_jsonl_ledger_counts_distinct_trials_per_dataset(tmp_path: Path) -> None:
    ledger = JsonlTrialLedger(tmp_path / "research" / "trials.jsonl")
    assert ledger.record("A", ["ema|x", "ema|y"]) == 2
    assert ledger.record("A", ["ema|y", "ema|z"]) == 3, "a repeated trial is the same attempt"
    assert ledger.record("B", ["ema|x"]) == 1, "another dataset has its own count"
    assert ledger.record("A", []) == 3, "recording nothing changes nothing"
    lines = (tmp_path / "research" / "trials.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3, "an empty search writes no line"
    assert json.loads(lines[0])["trials"] == ["ema|x", "ema|y"]


def test_jsonl_ledger_skips_a_torn_line(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    path.write_text('{"dataset": "A", "trials": ["a"]}\n{"dataset": "A", "tri\n', encoding="utf-8")
    assert JsonlTrialLedger(path).record("A", ["b"]) == 2


def test_only_catalog_searches_are_recorded() -> None:
    ledger = InMemoryTrialLedger()
    assert record_trials(ledger, _request(BarOrigin.SYNTHETIC), ["x"]) is None
    assert ledger.trials == {}
    assert record_trials(None, _request(), ["x"]) is None
    assert record_trials(ledger, _request(), ["x"]) == 1


def test_a_pair_is_one_dataset_whatever_the_leg_order() -> None:
    single = _request()
    left = replace(single, bar_types=("B-1H", "A-1H"))
    right = replace(single, bar_types=("A-1H", "B-1H"))
    assert dataset_key(left) == dataset_key(right) == "A-1H,B-1H"
    assert dataset_key(single) == BAR_TYPE
    assert trial_id(single, "fast=5") == "ema|fast=5"


# ---- DSR -------------------------------------------------------------------------------

RETURNS = [Decimal(str(value)) for value in (0.02, 0.01, 0.03, -0.01, 0.02, 0.015, 0.025, 0.0)]
TRIAL_SHARPES = [Decimal(str(value)) for value in (0.1, 0.4, 0.9, 0.3)]


def test_more_trials_in_history_raise_the_bar() -> None:
    alone = deflated_sharpe_ratio(RETURNS, TRIAL_SHARPES)
    history = deflated_sharpe_ratio(RETURNS, TRIAL_SHARPES, total_trials=200)
    assert alone.probability is not None
    assert history.probability is not None
    assert history.threshold_sharpe is not None
    assert alone.threshold_sharpe is not None
    assert history.threshold_sharpe > alone.threshold_sharpe
    assert history.probability < alone.probability
    assert history.n_trials_total == 200
    assert "n_trials_total=200" in history.summary_line()
    assert alone.n_trials_total == 4


def test_a_lagging_ledger_cannot_shrink_the_search() -> None:
    lagging = deflated_sharpe_ratio(RETURNS, TRIAL_SHARPES, total_trials=2)
    assert lagging.n_trials_total == 4
    assert lagging.probability == deflated_sharpe_ratio(RETURNS, TRIAL_SHARPES).probability


def test_undefined_dsr_still_reports_the_total() -> None:
    result = deflated_sharpe_ratio(RETURNS[:3], TRIAL_SHARPES, total_trials=50)
    assert result.probability is None
    assert result.n_trials_total == 50


# ---- the use cases ---------------------------------------------------------------------


def test_audit_is_deflated_by_earlier_searches_on_the_same_data() -> None:
    fresh = _audit(InMemoryTrialLedger())
    ledger = InMemoryTrialLedger()
    ledger.record(BAR_TYPE, [f"regime|earlier-{index}" for index in range(96)])
    seasoned = _audit(ledger)

    assert fresh.deflated_sharpe.n_trials_total == fresh.configuration_count
    assert seasoned.deflated_sharpe.n_trials_total == 96 + seasoned.configuration_count
    assert seasoned.deflated_sharpe.threshold_sharpe is not None
    assert fresh.deflated_sharpe.threshold_sharpe is not None
    assert seasoned.deflated_sharpe.threshold_sharpe > fresh.deflated_sharpe.threshold_sharpe
    assert f"best of {96 + seasoned.configuration_count} coin-flip" in seasoned.notes


def test_repeating_an_audit_does_not_inflate_the_count() -> None:
    ledger = InMemoryTrialLedger()
    first = _audit(ledger)
    second = _audit(ledger)
    assert first.deflated_sharpe.n_trials_total == second.deflated_sharpe.n_trials_total


def test_a_synthetic_audit_leaves_the_ledger_alone() -> None:
    ledger = InMemoryTrialLedger()
    report = _audit(ledger, BarOrigin.SYNTHETIC)
    assert ledger.trials == {}
    assert report.deflated_sharpe.trials_total is None


def test_walk_forward_grid_counts_toward_the_audit() -> None:
    ledger = InMemoryTrialLedger()
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=400, seed=5)
    report = RunWalkForward(_Engine(), _Feed(bars), trial_ledger=ledger).execute(
        WalkForwardRequest(backtest=_request(bar_count=400))
    )
    assert len(ledger.trials[BAR_TYPE]) == report.candidates_tried


@pytest.mark.parametrize("path", ["research/trials.jsonl", "elsewhere/ledger.jsonl"])
def test_composition_hands_the_ledger_to_both_searches(path: str) -> None:
    from nautilus_lab.infrastructure.settings import Settings
    from nautilus_lab.interfaces import composition

    cfg = Settings(_env_file=None, trials_ledger_path=path)  # type: ignore[call-arg]
    for factory in (composition.overfit_audit_use_case, composition.walk_forward_use_case):
        ledger = factory(cfg)._trial_ledger
        assert isinstance(ledger, JsonlTrialLedger), factory.__name__
        assert ledger.path == Path(path)
