"""Pre-registration of walk-forward tests (docs/27 R-2)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from nautilus_lab.application.dtos import BacktestReport, BacktestRequest, WalkForwardRequest
from nautilus_lab.application.preregistration import register, research_terms, verdict_for
from nautilus_lab.application.promotion_gate import GateCriteria
from nautilus_lab.application.run_walk_forward import RunWalkForward
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.funding import FundingSnapshot
from nautilus_lab.domain.order_book import OrderBookSnapshot
from nautilus_lab.domain.preregistration import (
    Preregistration,
    PreregistrationStatus,
    ResearchTerms,
    check_preregistration,
)
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.ticks import AggTrade
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_ohlcv
from nautilus_lab.infrastructure.preregistration_store import JsonPreregistrationStore

T0 = datetime(2026, 9, 1, tzinfo=UTC)
BARS = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=1200, seed=9)


def _request(folds: int = 3, **changes: object) -> WalkForwardRequest:
    backtest = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=len(BARS),
        starting_equity=Decimal("100000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.005"),
            stop_pct=Decimal("0.01"),
            max_daily_loss=Decimal("0.02"),
            max_drawdown=Decimal("0.06"),
        ),
        robot=RobotName.EMA,
        source=BarOrigin.CATALOG,
        bar_type="ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL",
    )
    return WalkForwardRequest(backtest=replace(backtest, **changes), folds=folds)  # type: ignore[arg-type]


class _Feed:
    def load(self, request: BacktestRequest) -> list[OhlcvBar]:
        return BARS

    def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
        return {request.instrument_id: BARS}


class _Engine:
    def run(
        self,
        request: BacktestRequest,
        bars: list[OhlcvBar],
        ticks: list[AggTrade] | None = None,
        books: list[OrderBookSnapshot] | None = None,
    ) -> BacktestReport:
        return BacktestReport(fills=2, positions=1, ending_balance=Decimal("100500"), notes="")

    def run_spread(
        self,
        request: BacktestRequest,
        bars_by_instrument: dict[str, list[OhlcvBar]],
        funding: list[FundingSnapshot] | None = None,
    ) -> BacktestReport:
        raise AssertionError("single instrument only")


def _terms(request: WalkForwardRequest | None = None) -> ResearchTerms:
    request = request or _request()
    windows = RunWalkForward(_Engine(), _Feed()).plan_multi(request)
    return research_terms(request, windows)


def _registered(terms: ResearchTerms, at: datetime = T0) -> Preregistration:
    return Preregistration(
        terms=terms, hypothesis="h", registered_at=at, terms_sha256=terms.sha256()
    )


# ---- terms ------------------------------------------------------------------------------


def test_the_plan_is_exactly_the_windows_the_run_uses() -> None:
    use_case = RunWalkForward(_Engine(), _Feed())
    request = _request()
    planned = use_case.plan_multi(request)
    ran = use_case.execute_multi(request)
    assert planned == tuple(fold.window for fold in ran.folds)


def test_the_same_setup_gives_the_same_hash() -> None:
    assert _terms().sha256() == _terms().sha256()


@pytest.mark.parametrize(
    "changed",
    [
        _request(folds=4),
        _request(use_tick_vpin=True),
        _request(robot=RobotName.ADAPTIVE_EMA),
        replace(_request(), in_sample_fraction=Decimal("0.6")),
        replace(_request(), use_optuna=True),
    ],
)
def test_changing_any_term_changes_the_hash(changed: WalkForwardRequest) -> None:
    assert _terms(changed).sha256() != _terms().sha256()


def test_easing_the_gate_changes_the_hash() -> None:
    request = _request()
    windows = RunWalkForward(_Engine(), _Feed()).plan_multi(request)
    eased = research_terms(request, windows, GateCriteria(max_pbo=Decimal("0.5")))
    assert eased.sha256() != research_terms(request, windows).sha256()


def test_one_more_bar_is_a_new_test() -> None:
    request = _request()
    grown = research_terms(request, RunWalkForward(_Engine(), _GrownFeed()).plan_multi(request))
    assert grown.sha256() != _terms().sha256()


class _GrownFeed(_Feed):
    def load(self, request: BacktestRequest) -> list[OhlcvBar]:
        return synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=1201, seed=9)


# ---- the check --------------------------------------------------------------------------


def test_matching_terms_registered_before_the_run_match() -> None:
    terms = _terms()
    verdict = check_preregistration(terms, [_registered(terms)], run_started_at=T0 + timedelta(1))
    assert verdict.status is PreregistrationStatus.MATCHED
    assert verdict.passed is True


def test_no_registration_is_not_measured_not_a_failure() -> None:
    verdict = check_preregistration(_terms(), [], run_started_at=T0)
    assert verdict.status is PreregistrationStatus.NOT_REGISTERED
    assert verdict.passed is None


def test_a_different_run_says_which_terms_moved() -> None:
    registered = _registered(_terms())
    verdict = check_preregistration(
        _terms(_request(folds=4)), [registered], run_started_at=T0 + timedelta(1)
    )
    assert verdict.status is PreregistrationStatus.MISMATCH
    assert verdict.passed is False
    assert "folds" in verdict.detail
    assert "oos_windows" in verdict.detail


def test_a_registration_dated_after_the_run_does_not_count() -> None:
    terms = _terms()
    verdict = check_preregistration(terms, [_registered(terms)], run_started_at=T0)
    assert verdict.status is PreregistrationStatus.LATE
    assert verdict.passed is False


def test_an_edited_registration_is_not_a_registration() -> None:
    terms = _terms()
    tampered = replace(_registered(terms), terms=replace(terms, folds=9))
    assert not tampered.intact
    verdict = check_preregistration(terms, [tampered], run_started_at=T0 + timedelta(1))
    assert verdict.status is PreregistrationStatus.MISMATCH


def test_registrations_for_other_robots_or_data_are_ignored() -> None:
    other = _registered(_terms(_request(robot=RobotName.ADAPTIVE_EMA)))
    verdict = check_preregistration(_terms(), [other], run_started_at=T0 + timedelta(1))
    assert verdict.status is PreregistrationStatus.NOT_REGISTERED


# ---- the store and the round trip -------------------------------------------------------


def test_register_then_run_matches_through_the_file_store(tmp_path: Path) -> None:
    store = JsonPreregistrationStore(tmp_path / "preregistrations")
    request = _request()
    use_case = RunWalkForward(_Engine(), _Feed())
    registration, where = register(
        _terms(request), hypothesis="EMA beats holding in trends", registered_at=T0, store=store
    )
    assert Path(where).is_file()
    payload = json.loads(Path(where).read_text(encoding="utf-8"))
    assert payload["terms_sha256"] == registration.terms_sha256
    assert payload["hypothesis"] == "EMA beats holding in trends"

    report = use_case.execute_multi(request)
    verdict = verdict_for(
        request,
        [fold.window for fold in report.folds],
        store,
        run_started_at=T0 + timedelta(hours=1),
    )
    assert verdict.status is PreregistrationStatus.MATCHED
    assert verdict.run_sha256 == registration.terms_sha256


def test_a_registration_is_never_overwritten(tmp_path: Path) -> None:
    store = JsonPreregistrationStore(tmp_path)
    terms = _terms()
    register(terms, hypothesis="h", registered_at=T0, store=store)
    with pytest.raises(FileExistsError):
        register(terms, hypothesis="h2", registered_at=T0, store=store)


def test_an_empty_hypothesis_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="hypothesis"):
        register(
            _terms(), hypothesis="  ", registered_at=T0, store=JsonPreregistrationStore(tmp_path)
        )


def test_a_hand_edited_file_is_loaded_but_not_trusted(tmp_path: Path) -> None:
    store = JsonPreregistrationStore(tmp_path)
    terms = _terms()
    _, where = register(terms, hypothesis="h", registered_at=T0, store=store)
    payload = json.loads(Path(where).read_text(encoding="utf-8"))
    payload["terms"]["folds"] = 7
    Path(where).write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    loaded = store.load_all()
    assert len(loaded) == 1
    assert not loaded[0].intact
    verdict = check_preregistration(terms, loaded, run_started_at=T0 + timedelta(1))
    assert verdict.status is PreregistrationStatus.MISMATCH
