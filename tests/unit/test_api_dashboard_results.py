"""Dashboard payload contracts added for the richer result panels.

These tests exist because the frontend now renders numbers that used to be dropped by
`api/serializers.py`: cost sensitivity, the PBO configuration x block matrix, per-fold
detail and the IS/OOS split of a single walk-forward. A serializer that silently stops
emitting one of them would empty a panel without failing anything, so each contract is
pinned here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nautilus_lab.api.catalog_service import (
    describe_catalog_cached,
    invalidate_catalog_cache,
    repo_root,
    resolve_catalog_path,
)
from nautilus_lab.api.paper_runner import PaperRunConfig, execute_paper
from nautilus_lab.api.research_runner import (
    ResearchJobConfig,
    _journal_entry,
    config_from_job,
)
from nautilus_lab.api.routes.library import strategy_spec_payload
from nautilus_lab.api.serializers import (
    build_job_result,
    serialize_backtest,
    serialize_costs,
    serialize_fold,
    serialize_pbo,
    serialize_walk_forward,
)
from nautilus_lab.application.dtos import (
    BacktestReport,
    MultiWindowReport,
    OverfitAuditReport,
    SelectedParams,
    WalkForwardFold,
    WalkForwardReport,
)
from nautilus_lab.domain.deflated_sharpe import DeflatedSharpeResult
from nautilus_lab.domain.metrics import BacktestMetrics
from nautilus_lab.domain.regime import BACKTEST_WIRED_ROBOTS
from nautilus_lab.domain.walk_forward import WalkForwardWindow
from nautilus_lab.infrastructure.settings import Settings


def _metrics(
    *,
    fees: str = "12.5",
    traded_notional: str = "250000",
    breakeven: str | None = "0.00073",
) -> BacktestMetrics:
    return BacktestMetrics(
        fees_paid=Decimal(fees),
        max_drawdown=Decimal("0.04"),
        turnover=Decimal("5000"),
        sharpe_like=Decimal("1.25"),
        traded_notional=Decimal(traded_notional),
        breakeven_cost=None if breakeven is None else Decimal(breakeven),
    )


def _selected() -> SelectedParams:
    return SelectedParams(
        fast_ema=10,
        slow_ema=20,
        donchian_period=20,
        bb_period=20,
        bb_k=Decimal("2"),
        enter_trend_er=Decimal("0.3"),
        exit_trend_er=Decimal("0.2"),
    )


def _window() -> WalkForwardWindow:
    return WalkForwardWindow(
        in_sample_start=datetime(2024, 1, 1, tzinfo=UTC),
        in_sample_end=datetime(2024, 6, 1, tzinfo=UTC),
        out_of_sample_start=datetime(2024, 6, 1, tzinfo=UTC),
        out_of_sample_end=datetime(2024, 7, 1, tzinfo=UTC),
    )


def _fold(index: int, oos_return: str, buy_hold: str) -> WalkForwardFold:
    return WalkForwardFold(
        index=index,
        selected=_selected(),
        candidates_tried=4,
        in_sample=BacktestReport(1, 1, Decimal("100"), "is", metrics=_metrics()),
        out_of_sample=BacktestReport(
            2, 1, Decimal("101"), "oos", metrics=_metrics(breakeven="0.00050")
        ),
        window=_window(),
        oos_return=Decimal(oos_return),
        buy_and_hold_return=Decimal(buy_hold),
    )


def test_serialize_costs_reads_paid_rate_and_headroom() -> None:
    costs = serialize_costs(_metrics())
    # paid = 12.5 / 250000 = 0.00005 (5 bps); breakeven 0.00073 (7.3 bps)
    assert costs["paid_cost_rate"] == pytest.approx(0.00005)
    assert costs["breakeven_cost"] == pytest.approx(0.00073)
    assert costs["cost_headroom"] == pytest.approx(0.00068)
    assert costs["traded_notional"] == pytest.approx(250000)


def test_serialize_costs_never_invents_a_measurement_without_trades() -> None:
    """No fills means no breakeven: None, not zero. Zero would read as "free execution saves it"."""
    costs = serialize_costs(
        BacktestMetrics(
            fees_paid=Decimal("0"),
            max_drawdown=Decimal("0"),
            turnover=Decimal("0"),
            sharpe_like=None,
            traded_notional=Decimal("0"),
            breakeven_cost=None,
        )
    )
    assert costs["breakeven_cost"] is None
    assert costs["paid_cost_rate"] is None
    assert costs["cost_headroom"] is None


def test_serialize_costs_handles_missing_metrics() -> None:
    assert serialize_costs(None) == {
        "traded_notional": None,
        "breakeven_cost": None,
        "paid_cost_rate": None,
        "cost_headroom": None,
    }


def test_serialize_backtest_hoists_cost_fields_for_the_dashboard() -> None:
    report = BacktestReport(
        fills=3, positions=2, ending_balance=Decimal("101000"), notes="n", metrics=_metrics()
    )
    payload = serialize_backtest(report)
    assert payload["breakeven_cost"] == pytest.approx(0.00073)
    assert payload["paid_cost_rate"] == pytest.approx(0.00005)
    assert payload["cost_headroom"] == pytest.approx(0.00068)
    # the nested block and the flat keys must agree, or a panel would read a stale copy
    assert payload["metrics"]["breakeven_cost"] == payload["breakeven_cost"]


def test_serialize_fold_exposes_excess_return_and_per_fold_metrics() -> None:
    payload = serialize_fold(_fold(0, "0.02", "0.01"))
    assert payload["excess_return"] == "+1.00%"
    assert payload["beats_buy_and_hold"] is True
    assert payload["fills"] == 2
    assert payload["candidates_tried"] == 4
    assert payload["oos_metrics"]["breakeven_cost"] == pytest.approx(0.00050)


def test_serialize_fold_losing_to_buy_and_hold_says_so() -> None:
    payload = serialize_fold(_fold(0, "0.01", "0.05"))
    assert payload["beats_buy_and_hold"] is False
    assert payload["excess_return"] == "-4.00%"


def test_serialize_fold_without_a_baseline_reports_no_verdict() -> None:
    """A missing buy&hold is not a win. `None` keeps the UI from claiming one."""
    fold = WalkForwardFold(
        index=0,
        selected=_selected(),
        candidates_tried=1,
        in_sample=BacktestReport(0, 0, None, "is"),
        out_of_sample=BacktestReport(0, 0, None, "oos"),
        window=_window(),
        oos_return=None,
        buy_and_hold_return=None,
    )
    payload = serialize_fold(fold)
    assert payload["beats_buy_and_hold"] is None
    assert payload["excess_return"] == "n/a"


def test_multi_window_payload_carries_spread_costs_and_fold_count() -> None:
    multi = MultiWindowReport(
        folds=(_fold(0, "0.02", "0.01"), _fold(1, "-0.01", "0.03")),
        starting_equity=Decimal("100000"),
        notes="notes",
    )
    payload = build_job_result(
        run_type="multi_window", robot="regime", source="catalog", multi_window=multi
    )["multi_window"]
    assert payload["fold_count"] == 2
    assert payload["profitable"] == "1/2"
    assert payload["spread"] == "+3.00%"
    # mean oos 0.005 vs mean buy&hold 0.020 -> -1.50%: losing to just holding it
    assert payload["mean_excess_return"] == "-1.50%"
    assert payload["beats_buy_and_hold"] is False
    # both folds' out-of-sample legs carry breakeven 0.00050
    assert payload["mean_breakeven_cost"] == pytest.approx(0.00050)
    assert payload["mean_paid_cost_rate"] == pytest.approx(0.00005)
    assert len(payload["folds"]) == 2
    assert payload["cost_headroom"] == pytest.approx(0.00045)


def test_walk_forward_split_labels_in_sample_and_out_of_sample_returns() -> None:
    report = WalkForwardReport(
        selected=_selected(),
        candidates_tried=4,
        in_sample=BacktestReport(3, 1, Decimal("110000"), "is"),
        out_of_sample=BacktestReport(2, 1, Decimal("95000"), "oos"),
        window=_window(),
        notes="n",
    )
    payload = serialize_walk_forward(report, starting_equity=Decimal("100000"))
    assert payload["in_sample_return"] == "+10.00%"
    assert payload["out_of_sample_return"] == "-5.00%"


def test_walk_forward_split_without_starting_equity_stays_unmeasured() -> None:
    report = WalkForwardReport(
        selected=_selected(),
        candidates_tried=1,
        in_sample=BacktestReport(1, 1, Decimal("110000"), "is"),
        out_of_sample=BacktestReport(1, 1, Decimal("95000"), "oos"),
        window=_window(),
        notes="n",
    )
    payload = serialize_walk_forward(report)
    assert payload["out_of_sample_return"] is None
    assert payload["in_sample_return"] is None


def _pbo_report() -> OverfitAuditReport:
    return OverfitAuditReport(
        pbo=Decimal("0.25"),
        split_count=6,
        configuration_count=3,
        blocks=4,
        block_returns=(
            (Decimal("0.01"), Decimal("0.02"), Decimal("0.03")),
            (Decimal("0.02"), Decimal("0.01"), Decimal("-0.01")),
            (None, Decimal("0.04"), Decimal("0.00")),
            (Decimal("0.03"), Decimal("0.02"), Decimal("0.01")),
        ),
        labels=("a=1", "a=2", "a=3"),
        notes="notes",
        deflated_sharpe=DeflatedSharpeResult(
            probability=Decimal("0.81"),
            sharpe=Decimal("1.1"),
            threshold_sharpe=Decimal("0.4"),
            observations=4,
            trials=3,
            note="",
        ),
    )


def test_pbo_payload_ships_the_matrix_the_heatmap_needs() -> None:
    payload = serialize_pbo(_pbo_report())
    assert payload["blocks"] == 4
    assert payload["configuration_count"] == 3
    assert len(payload["block_returns"]) == 4
    assert all(len(row) == 3 for row in payload["block_returns"])
    assert payload["labels"] == ["a=1", "a=2", "a=3"]
    # a missing balance stays None: flattening it to 0 would look like a measured loss
    assert payload["block_returns"][2][0] is None


def test_pbo_payload_marks_the_best_configuration() -> None:
    payload = serialize_pbo(_pbo_report())
    # column sums: a=1 0.06, a=2 0.09, a=3 0.03 -> index 1
    assert payload["best_configuration_index"] == 1
    assert payload["best_configuration_label"] == "a=2"
    assert payload["deflated_sharpe"]["probability"] == "0.81"


def test_pbo_without_enough_configurations_reports_no_winner() -> None:
    report = OverfitAuditReport(
        pbo=Decimal("0"),
        split_count=0,
        configuration_count=1,
        blocks=4,
        block_returns=((Decimal("0.01"),), (Decimal("0.02"),)),
        labels=("only",),
        notes="notes",
        deflated_sharpe=DeflatedSharpeResult(
            probability=None,
            sharpe=None,
            threshold_sharpe=None,
            observations=2,
            trials=1,
            note="fewer than two trials",
        ),
    )
    payload = serialize_pbo(report)
    assert payload["is_meaningful"] is False
    assert payload["best_configuration_index"] is None
    assert payload["best_configuration_label"] is None


def test_archived_config_reproduces_every_research_argument() -> None:
    """`Load config` must replay the same experiment, so no field may be dropped."""
    job = ResearchJobConfig(
        robot="regime",
        source="catalog",
        bars=2500,
        folds=4,
        is_fraction=Decimal("0.6"),
        embargo_bars=7,
        use_optuna=False,
        optuna_trials=33,
        pbo=True,
        pbo_blocks=6,
        bar_vpin=True,
        stress_slice="ftx2022",
        generate_tearsheet=False,
        journal=True,
        notify=True,
        full_sample=False,
        catalog_path="catalog",
        instrument_id="ETH/USDT.SIM",
        bar_interval="1h",
        is_start="2025-01-01",
        is_end="2025-06-01",
        oos_start="2025-06-11",
        oos_end="2025-07-01",
        param_overrides={"FAST_EMA": "12"},
    )
    config = config_from_job(job)
    assert config["config_version"] == 2
    assert config["stress_slice"] == "ftx2022"
    assert config["embargo_bars"] == 7
    assert config["pbo"] is True
    assert config["pbo_blocks"] == 6
    assert config["bar_vpin"] is True
    assert config["optuna_trials"] == 33
    assert config["is_fraction"] == "0.6"
    assert config["param_overrides"] == {"FAST_EMA": "12"}
    assert config["instrument_id"] == "ETH/USDT.SIM"
    assert config["bar_interval"] == "1h"


def test_paper_refuses_robots_it_cannot_build() -> None:
    """A robot without a paper path is refused; substituting one would misreport the run."""
    result, _ = execute_paper(PaperRunConfig(robot="funding", bars=10, source="synthetic"))
    assert result["is_error"] is True
    assert "funding" in str(result["error_message"])
    assert "regime" in str(result["error_message"])


def test_catalog_description_cache_returns_and_drops_payload(tmp_path: Path) -> None:
    invalidate_catalog_cache()
    missing = tmp_path / "not-a-catalog"
    first = describe_catalog_cached(str(missing))
    assert first["exists"] is False
    # a second call must not need the filesystem to answer
    assert describe_catalog_cached(str(missing)) == first
    invalidate_catalog_cache(str(missing))
    assert describe_catalog_cached(str(missing)) == first
    invalidate_catalog_cache()


def test_relative_catalog_path_does_not_depend_on_the_launch_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Starting the server from `frontend/` must not describe `frontend/catalog`.

    `CATALOG_PATH=catalog` is relative, so resolving it against the cwd turned a full catalog
    at the repo root into an empty one: the chart asked the API for bars and got
    "no bars in catalog /.../frontend/catalog for ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL. Run
    `lab ingest` first." — with `lab ingest` already done.
    """
    from_root = resolve_catalog_path("catalog")
    assert from_root == (repo_root() / "catalog").resolve()
    monkeypatch.chdir(tmp_path)
    assert resolve_catalog_path("catalog") == from_root
    # an absolute path is still taken at its word
    assert resolve_catalog_path(str(tmp_path / "other")) == (tmp_path / "other").resolve()


def test_strategy_payload_reads_the_nested_implementation_block() -> None:
    """The spec schema puts wiring under `implementation:`.

    Reading it from the top level made every robot report `wired_in_backtest: false` and
    `minimum_bars: 100`, which labelled working robots as fail-closed and would have made
    the research preflight block every run.
    """
    spec = {
        "kind": "strategy",
        "name": "regime",
        "status": "candidate",
        "title": "Regime router",
        "hypothesis": "trend vs range",
        "implementation": {
            "domain_module": "src/nautilus_lab/domain/regime_router.py",
            "strategy_class": "RegimeRouter",
            "backtest_adapter": "signal_strategy",
            "wired_in_backtest": True,
            "minimum_bars": 150,
            "grid_source": "default_branch",
            "signal_kind": "direction",
        },
        "params": [{"env": "DONCHIAN_PERIOD", "default": 20}],
    }
    payload = strategy_spec_payload(spec)
    assert payload["wired_in_backtest"] is True
    assert payload["minimum_bars"] == 150
    assert payload["grid_source"] == "default_branch"
    assert payload["strategy_class"] == "RegimeRouter"
    assert payload["domain_module"].endswith("regime_router.py")
    assert payload["backtest_adapter"] == "signal_strategy"
    assert payload["summary"] == "Regime router"
    assert payload["params"] == [{"env": "DONCHIAN_PERIOD", "default": 20}]


def test_strategy_payload_still_reads_a_flat_spec() -> None:
    """An older flat spec must stay readable rather than turning into blank fields."""
    payload = strategy_spec_payload(
        {
            "name": "ema",
            "wired_in_backtest": True,
            "minimum_bars": 50,
            "grid_source": "explicit",
            "strategy_class": "EmaCrossover",
        }
    )
    assert payload["wired_in_backtest"] is True
    assert payload["minimum_bars"] == 50
    assert payload["grid_source"] == "explicit"
    assert payload["strategy_class"] == "EmaCrossover"


def test_strategy_payload_defaults_do_not_leak_none() -> None:
    """A blocked spec without a declared warm-up still needs a usable number."""
    payload = strategy_spec_payload({"name": "funding", "implementation": {}})
    assert payload["minimum_bars"] == 100
    assert payload["wired_in_backtest"] is False
    assert payload["grid_source"] is None
    assert payload["params"] == []


def test_journal_entry_records_the_gates_not_just_a_number() -> None:
    entry = _journal_entry(
        subject="regime ETH/USDT.SIM",
        gates="walk-forward catalog folds=4",
        oos_return=Decimal("0.021"),
        buy_and_hold=Decimal("0.05"),
        fills=42,
        reason="auto: profitable 1/4 folds",
        artifact="reports/ts.html",
    )
    payload = entry.as_dict()
    assert payload["gates"] == "walk-forward catalog folds=4"
    assert payload["subject"] == "regime ETH/USDT.SIM"
    assert payload["oos_return"] == "0.021"
    assert payload["buy_and_hold_return"] == "0.05"
    assert payload["fills"] == 42
    assert payload["artifact"] == "reports/ts.html"
    # a run that is journaled starts as pending: a human decides, the machine does not
    assert payload["decision"] == "pending"
    assert payload["source"] == "lab api research"


def test_journal_write_never_fails_a_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bookkeeping must not turn a successful backtest into a failed job."""
    from nautilus_lab.api import research_runner
    from nautilus_lab.domain.provenance import RunManifest

    def _explode(*args: object, **kwargs: object) -> None:
        raise OSError("disk is read-only")

    monkeypatch.setattr(research_runner, "record_run", _explode)
    monkeypatch.setattr(
        research_runner, "journal_paths", lambda cfg: (tmp_path / "j.md", tmp_path / "j.jsonl")
    )
    entry = research_runner._journal_entry(subject="s", gates="g")
    manifest = RunManifest()
    # No exception escapes: the caller keeps its result and the failure is printed.
    research_runner._record_journal(_settings_stub(), manifest, entry)


def _settings_stub() -> Settings:
    """A Settings snapshot for tests that patch `journal_paths` and never read it."""
    return Settings()


def _client() -> TestClient:
    from fastapi.testclient import TestClient as _TestClient

    from nautilus_lab.api.app import app

    return _TestClient(app)


def test_research_route_rejects_impossible_combinations_before_spawning() -> None:
    """A request that cannot mean anything must not cost a process launch.

    These combinations used to be caught inside the job, which meant the API answered
    "started", spawned a subprocess, cleared the previous run's artifacts, and only then
    reported the error — blanking the dashboard's last result on the way.
    """
    client = _client()
    cases = [
        (
            {"robot": "regime", "source": "catalog", "full_sample": True, "use_optuna": True},
            "mutually exclusive",
        ),
        (
            {"robot": "regime", "source": "catalog", "folds": 4, "is_start": "2025-01-01"},
            "derive their own windows",
        ),
        (
            {"robot": "regime", "source": "catalog", "pbo": True, "generate_tearsheet": True},
            "tearsheet",
        ),
    ]
    for payload, expected in cases:
        response = client.post("/api/research", json=payload)
        assert response.status_code == 400, (payload, response.status_code)
        assert expected in response.json()["detail"]


def test_paper_route_rejects_a_robot_without_an_adapter() -> None:
    client = _client()
    response = client.post(
        "/api/paper/run", json={"robot": "funding", "bars": 10, "source": "synthetic"}
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "funding" in detail
    # the supported set must be named, or the user cannot pick a working robot
    assert "regime" in detail and "ema" in detail


def test_status_reports_every_job_and_the_selected_catalog() -> None:
    client = _client()
    body = client.get("/api/status", params={"catalog_path": "catalog"}).json()
    assert set(body["jobs"]) == {"research", "ingest", "ml_train", "paper"}
    for job in body["jobs"].values():
        assert job["running"] is False
        assert job["elapsed_seconds"] is None
    assert body["live_safe_mode"] == "FAIL_CLOSED"
    assert body["is_live"] is False
    assert body["bar_interval"]
    # The advertised set is the engine's wired set: paper runs the real engine now,
    # so any robot it cannot build must be absent from this list.
    assert body["paper_robots"] == sorted(item.value for item in BACKTEST_WIRED_ROBOTS)
    assert "pairs" in body["paper_robots"]
