"""Backtest speed (2026-10-08): timings, the parallel in-sample grid, fixed parameters.

None of these may change a result: the batch path must pick the same parameters with the
same ranking as the serial one, and `PARAM_SEARCH=false` must run the configured values.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
import time
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from nautilus_lab.api.batch_store import (
    OK,
    cell_dir,
    cell_timings,
    clear_partial_cell,
    create_batch,
    descendant_pids,
    load_batch,
)
from nautilus_lab.api.run_batch_job import BatchRun, is_workers_per_cell
from nautilus_lab.application.batch_plan import BatchRequest, plan_cells
from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    WalkForwardRequest,
    selected_from_request,
)
from nautilus_lab.application.param_grid import iter_param_grid
from nautilus_lab.application.run_walk_forward import RunWalkForward
from nautilus_lab.application.timing import (
    TIMINGS,
    PhaseTimer,
    format_phase_table,
    merge_phase_totals,
)
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.order_book import OrderBookSnapshot
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.ticks import AggTrade
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_ohlcv


def _limits() -> RiskLimits:
    return RiskLimits(
        risk_per_trade=Decimal("0.005"),
        stop_pct=Decimal("0.01"),
        max_daily_loss=Decimal("0.02"),
        max_drawdown=Decimal("0.06"),
    )


def _request(**overrides: object) -> BacktestRequest:
    base = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=600,
        starting_equity=Decimal("100000"),
        risk=_limits(),
        robot=RobotName.REGIME,
        session_id="sess",
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


BARS = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=3000, seed=5)


class _Feed:
    def load(self, request: BacktestRequest) -> list[OhlcvBar]:
        return BARS

    def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
        return {request.instrument_id: BARS}


def _balance(request: BacktestRequest, bars: Sequence[OhlcvBar]) -> Decimal:
    # Deterministic in the candidate and the window, with ties (bb_k does not matter for
    # donchian 20 and 40), so the tie-break is part of what the two paths must agree on.
    seed = request.regime.donchian_period
    if seed in (20, 40):
        return Decimal("100000") + Decimal(seed)
    return Decimal("100000") + Decimal(seed) * Decimal(len(bars) % 7 + 1) + request.regime.bb_k


class _SerialEngine:
    def __init__(self) -> None:
        self.calls: list[BacktestRequest] = []

    def run(
        self,
        request: BacktestRequest,
        bars: list[OhlcvBar],
        ticks: list[AggTrade] | None = None,
        books: list[OrderBookSnapshot] | None = None,
    ) -> BacktestReport:
        self.calls.append(request)
        return BacktestReport(
            fills=1, positions=1, ending_balance=_balance(request, bars), notes="fake"
        )

    def run_spread(self, *args: object, **kwargs: object) -> BacktestReport:
        raise AssertionError("not a spread robot")


class _BatchEngine(_SerialEngine):
    def __init__(self) -> None:
        super().__init__()
        self.batches: list[list[BacktestRequest]] = []

    def run_many(
        self,
        requests: Sequence[BacktestRequest],
        bars: list[OhlcvBar],
        ticks: list[AggTrade] | None = None,
        books: list[OrderBookSnapshot] | None = None,
    ) -> list[BacktestReport]:
        self.batches.append(list(requests))
        # Reversed execution order on purpose: only the returned order may matter.
        reports = {
            index: BacktestReport(
                fills=1, positions=1, ending_balance=_balance(request, bars), notes="fake"
            )
            for index, request in reversed(list(enumerate(requests)))
        }
        return [reports[index] for index in range(len(requests))]


def _multi(engine: object, *, scope: str = "oos", **overrides: object) -> object:
    request = WalkForwardRequest(backtest=_request(**overrides), folds=3, decision_log_scope=scope)
    return RunWalkForward(engine, _Feed()).execute_multi(request)  # type: ignore[arg-type]


# --- timer --------------------------------------------------------------------------
def test_phase_timer_accumulates_and_merges() -> None:
    timer = PhaseTimer()
    with timer.phase("a"):
        time.sleep(0.01)
    timer.add("b", 2.0, count=3)
    timer.merge({"a": {"seconds": 1.0, "count": 2}})
    snap = timer.snapshot()
    assert list(snap) == ["b", "a"]  # slowest first
    assert snap["b"] == {"seconds": 2.0, "count": 3}
    assert snap["a"]["count"] == 3
    assert float(snap["a"]["seconds"]) >= 1.01
    total = merge_phase_totals([snap, {"c": {"seconds": 0.5, "count": 1}}])
    assert total["b"]["seconds"] == 2.0
    assert "c" in total
    table = format_phase_table(total, total=10.0)
    assert "b" in table
    assert "20.0%" in table
    timer.reset()
    assert timer.snapshot() == {}


def test_walk_forward_records_its_phases() -> None:
    TIMINGS.reset()
    _multi(_SerialEngine())
    snap = TIMINGS.snapshot()
    assert snap["is_search"]["count"] == 3
    assert snap["oos_run"]["count"] == 3
    assert snap["load_bars"]["count"] == 1


# --- the batch grid path ------------------------------------------------------------
def test_batch_grid_selects_exactly_what_the_serial_grid_selects() -> None:
    serial = _multi(_SerialEngine())
    batch_engine = _BatchEngine()
    batched = _multi(batch_engine)
    assert len(batch_engine.batches) == 3  # one call per fold, the whole grid at once
    assert all(len(batch) == 15 for batch in batch_engine.batches)
    for left, right in zip(serial.folds, batched.folds, strict=True):  # type: ignore[attr-defined]
        assert left.selected == right.selected
        assert left.candidates == right.candidates
        assert left.candidates_tried == right.candidates_tried
        assert left.out_of_sample.ending_balance == right.out_of_sample.ending_balance


def test_batch_grid_keeps_the_oos_scope_rule() -> None:
    engine = _BatchEngine()
    _multi(engine, scope="oos")
    assert all(request.session_id is None for batch in engine.batches for request in batch)
    # The OOS runs still log, each under its fold's session.
    oos_sessions = [request.session_id for request in engine.calls]
    assert oos_sessions == ["sess-f0", "sess-f1", "sess-f2"]


def test_scope_all_hands_session_ids_to_the_batch() -> None:
    engine = _BatchEngine()
    _multi(engine, scope="all")
    assert all(request.session_id == "sess" for batch in engine.batches for request in batch)


# --- fixed parameters ---------------------------------------------------------------
def test_param_search_off_is_the_request_itself() -> None:
    request = _request(param_search=False)
    grid = list(iter_param_grid(request))
    assert grid == [selected_from_request(request)]
    assert len(list(iter_param_grid(_request()))) == 15


def test_param_search_off_runs_one_candidate_per_fold() -> None:
    engine = _SerialEngine()
    report = _multi(engine, param_search=False)
    folds = report.folds  # type: ignore[attr-defined]
    assert [fold.candidates_tried for fold in folds] == [1, 1, 1]
    assert len(engine.calls) == 6  # 1 in-sample + 1 out-of-sample per fold
    configured = _request().regime.donchian_period
    assert all(fold.selected.donchian_period == configured for fold in folds)


# --- worker counts ------------------------------------------------------------------
def test_is_workers_per_cell_splits_the_budget() -> None:
    assert is_workers_per_cell(7, 2) == 3
    assert is_workers_per_cell(1, 4) == 1
    assert is_workers_per_cell(64, 1) == 8  # capped


def test_resolve_is_workers() -> None:
    from nautilus_lab.infrastructure.nautilus.parallel_backtest import resolve_is_workers

    assert resolve_is_workers(1) == 1
    assert resolve_is_workers(0, cpu_count=8) == 7
    assert resolve_is_workers(0, cpu_count=1) == 1
    assert resolve_is_workers(32) == 8
    with pytest.raises(ValueError, match=">= 0"):
        resolve_is_workers(-1)


class _InnerFake(_SerialEngine):
    def __init__(self, decision_log: object | None) -> None:
        super().__init__()
        self.decision_log = decision_log


def test_parallel_engine_keeps_logged_and_tearsheet_runs_serial() -> None:
    from nautilus_lab.infrastructure.nautilus.parallel_backtest import ParallelResearchBacktest

    inner = _InnerFake(decision_log=object())
    engine = ParallelResearchBacktest(inner, workers=4)  # type: ignore[arg-type]
    try:
        logged = [_request(), _request(fast_ema=5)]
        reports = engine.run_many(logged, BARS)
        assert len(inner.calls) == 2  # ran here, not in a pool
        assert [r.ending_balance for r in reports] == [_balance(r, BARS) for r in logged]
        tearsheet = [_request(session_id=None, tearsheet_path="x.html")] * 2
        engine.run_many(tearsheet, BARS)
        assert len(inner.calls) == 4
        assert engine._pool is None  # never started
    finally:
        engine.close()


# --- batch runner -------------------------------------------------------------------
_TIMED_JOB = textwrap.dedent(
    """
    import json, os, sys
    args = sys.argv[1:]
    reports = args[args.index("--reports-dir") + 1]
    json.dump({"is_error": False, "run_type": "multi_window", "multi_window": {"folds": []},
               "env_workers": os.environ.get("BACKTEST_IS_WORKERS"),
               "env_profile": os.environ.get("RESEARCH_PROFILE")},
              open(f"{reports}/last_run.json", "w"))
    json.dump({"import_seconds": 1.5, "run_seconds": 10.0, "total_seconds": 12.0,
               "is_workers": os.environ.get("BACKTEST_IS_WORKERS"),
               "phases": {"is_search": {"seconds": 8.0, "count": 4},
                          "engine_run": {"seconds": 20.0, "count": 64}}},
              open(f"{reports}/timings.json", "w"))
    """
)


def _timed_python(tmp_path: Path) -> str:
    job = tmp_path / "timed_job.py"
    job.write_text(_TIMED_JOB, encoding="utf-8")
    wrapper = tmp_path / "timed_python"
    wrapper.write_text(f'#!/bin/sh\nshift 2\nexec "{sys.executable}" "{job}" "$@"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    return str(wrapper)


def _run_timed_batch(tmp_path: Path, **kwargs: object) -> tuple[Path, dict[str, object]]:
    reports = tmp_path / "reports"
    request = BatchRequest(robots=("ema",), symbols=("ETHUSDT", "BTCUSDT"), parallel=2)
    cells = plan_cells(request, exists=lambda _p: True, wired=["ema"])
    batch_id, path = create_batch(reports, request, cells)
    assert BatchRun(path, python=_timed_python(tmp_path), **kwargs).run() == 0  # type: ignore[arg-type]
    batch = load_batch(reports, batch_id)
    assert batch is not None
    return path, batch


def test_batch_gives_each_cell_its_share_and_sums_the_timings(tmp_path: Path) -> None:
    path, batch = _run_timed_batch(tmp_path, cpu_budget=7)
    assert batch["is_workers"] == 3
    cells: list[dict[str, Any]] = batch["cells"]  # type: ignore[assignment]
    assert all(cell["status"] == OK for cell in cells)
    for cell in cells:
        result = json.loads((cell_dir(path, cell["cell_id"]) / "last_run.json").read_text())
        assert result["env_workers"] == "3"
        assert result["env_profile"] is None
        assert cell["timings"]["total_seconds"] == 12.0
    timings = batch["timings"]
    assert timings["cells_timed"] == 2  # type: ignore[index]
    assert timings["phases"]["engine_run"] == {"seconds": 40.0, "count": 128}  # type: ignore[index]
    assert timings["import_seconds"] == 3.0  # type: ignore[index]


def test_profile_runs_the_grid_serially(tmp_path: Path) -> None:
    path, batch = _run_timed_batch(tmp_path, cpu_budget=16, profile=True)
    assert batch["is_workers"] == 1
    cell = batch["cells"][0]  # type: ignore[index]
    result = json.loads((cell_dir(path, cell["cell_id"]) / "last_run.json").read_text())
    assert result["env_workers"] == "1"
    assert result["env_profile"] == "1"


def test_cell_timings_and_resume_cleanup(tmp_path: Path) -> None:
    assert cell_timings(tmp_path) is None
    phases = {f"p{i}": {"seconds": float(20 - i), "count": 1} for i in range(12)}
    (tmp_path / "timings.json").write_text(
        json.dumps({"total_seconds": 5, "run_seconds": 4, "import_seconds": 1, "phases": phases})
    )
    (tmp_path / "profile.txt").write_text("x")
    compact = cell_timings(tmp_path)
    assert compact is not None
    assert len(compact["phases"]) == 8
    clear_partial_cell(tmp_path)
    assert not (tmp_path / "timings.json").exists()
    assert not (tmp_path / "profile.txt").exists()


@pytest.mark.skipif(not Path("/proc").is_dir(), reason="needs /proc")
def test_descendant_pids_finds_grandchildren() -> None:
    parent = subprocess.Popen(
        ["/bin/sh", "-c", "sleep 30 & sleep 30 & wait"],
    )
    try:
        found: list[int] = []
        for _ in range(50):
            found = descendant_pids(parent.pid)
            if len(found) >= 2:
                break
            time.sleep(0.05)
        assert len(found) >= 2
        assert os.getpid() not in found
    finally:
        for pid in descendant_pids(parent.pid):
            os.kill(pid, 9)
        parent.kill()
        parent.wait()
