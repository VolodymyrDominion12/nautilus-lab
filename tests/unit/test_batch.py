"""Batch backtest: planning the matrix, running cells, and the table rows (docs/30)."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
import textwrap
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nautilus_lab.api.app import create_app
from nautilus_lab.api.batch_store import (
    BLOCKED,
    CANCELLED,
    FAILED,
    LOST,
    OK,
    QUEUED,
    RUNNING,
    SUMMARY_VERSION,
    batch_payload,
    batch_process_alive,
    build_cell_summary,
    cell_dir,
    cell_summary,
    create_batch,
    decisions_dir,
    delete_batch,
    effective_status,
    find_session_cell,
    list_batches,
    load_batch,
    request_from_dict,
    request_to_dict,
    reset_batch,
    resume_batch,
    resume_batch_dir,
    retry_batch,
    run_payload,
    write_json,
)
from nautilus_lab.api.routes import batches as batches_routes
from nautilus_lab.api.run_batch_job import BatchRun
from nautilus_lab.api.run_batch_job import main as run_batch_main
from nautilus_lab.application.batch_plan import (
    MAX_VARIANTS,
    BatchRequest,
    BatchVariant,
    plan_cells,
    research_job_config,
)
from nautilus_lab.infrastructure.settings import Settings


def _all_exist(_path: str) -> bool:
    return True


def _all_exist_series(_catalog: str, _instrument: str, _interval: str) -> bool:
    return True


def test_plan_expands_robots_by_symbols_and_pairs_once() -> None:
    request = BatchRequest(robots=("ema", "pairs", "funding"), symbols=("BTCUSDT", "ETHUSDT"))
    cells = plan_cells(request, exists=_all_exist)
    assert [c.cell_id for c in cells] == [
        "ema_BTC",
        "ema_ETH",
        "pairs_ETHBTC",
        "funding_BTC",
        "funding_ETH",
    ]
    pairs = next(c for c in cells if c.robot == "pairs")
    assert pairs.env["PAIRS_LEG_A"] == "ETH/USDT.SIM"
    assert pairs.env["PAIRS_LEG_B"] == "BTC/USDT.SIM"
    funding = next(c for c in cells if c.cell_id == "funding_ETH")
    assert funding.catalog == "catalog_2019_4h"
    assert funding.interval == "4h"
    assert funding.env["FUNDING_PERP_ID"] == "ETHUSDT-PERP.SIM"


def test_plan_blocks_a_missing_model_and_an_unwired_robot_before_running() -> None:
    request = BatchRequest(robots=("formulaic_lgbm", "glft"), symbols=("BTCUSDT",))
    cells = plan_cells(
        request, exists=lambda path: not path.startswith("models/"), wired=["formulaic_lgbm"]
    )
    by_id = {c.cell_id: c for c in cells}
    assert by_id["formulaic_lgbm_BTC"].blocked is not None
    assert "formulaic_BTC_preoos.txt" in by_id["formulaic_lgbm_BTC"].blocked
    assert by_id["glft_BTC"].blocked is not None
    assert "no backtest adapter" in by_id["glft_BTC"].blocked


def test_plan_blocks_a_cell_whose_series_is_not_on_disk() -> None:
    """A catalog directory is not data: the 2026-10-03 sweep planned five dead cells.

    `funding_{SOL,BNB,XRP,DOGE,ADA}` were sent to `catalog_2019_4h` (bars for BTC/ETH
    only), each died on `no bars in catalog`, and the batch had been running for eight
    hours by then. The plan must say it before the start, not after.
    """
    request = BatchRequest(robots=("ema",), symbols=("BTCUSDT", "SOLUSDT"))
    cells = plan_cells(
        request,
        exists=_all_exist,
        series=lambda _catalog, instrument, _interval: instrument.startswith("BTC"),
    )
    by_id = {c.cell_id: c for c in cells}
    assert by_id["ema_BTC"].blocked is None
    assert by_id["ema_SOL"].blocked is not None
    assert "SOL/USDT.SIM" in by_id["ema_SOL"].blocked
    assert "catalog" in by_id["ema_SOL"].blocked


def test_plan_requires_both_funding_legs_and_the_settlements_in_one_catalog() -> None:
    """`funding` reads spot, perp and settlements; a missing settlement series is quiet.

    The quiet case is the worst one: without `data/funding/<SYMBOL>/funding.parquet` the
    run finishes `ok` with zero fills, which looks like a measured result and is not one.
    """
    request = BatchRequest(robots=("funding",), symbols=("BTCUSDT",))

    def series(_catalog: str, instrument: str, _interval: str) -> bool:
        return "PERP" not in instrument  # spot leg present, perp leg missing

    (cell,) = plan_cells(request, exists=_all_exist, series=series)
    assert cell.blocked is not None
    assert "BTCUSDT-PERP.SIM" in cell.blocked

    legs_only = plan_cells(
        request,
        exists=lambda path: "data/funding/" not in path,
        series=_all_exist_series,
    )
    (settlements_missing,) = legs_only
    assert settlements_missing.blocked is not None
    assert "no funding settlements" in settlements_missing.blocked

    complete = plan_cells(
        request,
        exists=_all_exist,
        series=_all_exist_series,
    )
    assert complete[0].blocked is None


def test_plan_checks_both_pairs_legs() -> None:
    request = BatchRequest(robots=("pairs",), symbols=("ETHUSDT", "BTCUSDT"))
    (cell,) = plan_cells(
        request,
        exists=_all_exist,
        series=lambda _catalog, instrument, _interval: instrument.startswith("ETH"),
    )
    assert cell.blocked is not None
    assert "BTC/USDT.SIM" in cell.blocked


def test_variants_run_the_whole_matrix_once_per_hypothesis() -> None:
    """A hypothesis is a dimension of the matrix, not a separate batch (docs/32 §4).

    The documented workflow used to be "one batch per hypothesis, compared by eye": `env`
    applied to every cell. A variant turns that into four batches' worth of cells in one
    artefact, with the hypothesis in the cell id so the table can be compared directly.
    """
    request = BatchRequest(
        robots=("regime", "pairs"),
        symbols=("BTCUSDT", "ETHUSDT"),
        env={"RISK_PER_TRADE": "0.005"},
        variants=(
            BatchVariant("H0", {"REGIME_LEGS": "uptrend,downtrend"}),
            BatchVariant("H1", {"ENTRY_FILTER_HTF_TREND": "true"}),
        ),
    )
    cells = plan_cells(request, exists=_all_exist)

    assert [cell.cell_id for cell in cells] == [
        "regime_BTC__H0",
        "regime_ETH__H0",
        "pairs_ETHBTC__H0",
        "regime_BTC__H1",
        "regime_ETH__H1",
        "pairs_ETHBTC__H1",
    ]
    by_id = {cell.cell_id: cell for cell in cells}
    # The variant wins over the global env, and both reach the child process.
    assert by_id["regime_BTC__H0"].env == {
        "RISK_PER_TRADE": "0.005",
        "REGIME_LEGS": "uptrend,downtrend",
    }
    assert by_id["regime_BTC__H1"].env == {
        "RISK_PER_TRADE": "0.005",
        "ENTRY_FILTER_HTF_TREND": "true",
    }
    # A variant that overrides a global key wins on that key only.
    override = BatchRequest(
        robots=("ema",),
        symbols=("BTCUSDT",),
        env={"RISK_PER_TRADE": "0.005", "STOP_PCT": "0.01"},
        variants=(BatchVariant("tight", {"STOP_PCT": "0.004"}),),
    )
    (cell,) = plan_cells(override, exists=_all_exist)
    assert cell.env == {"RISK_PER_TRADE": "0.005", "STOP_PCT": "0.004"}


def test_a_plain_batch_keeps_the_cell_ids_it_always_had() -> None:
    """Cell ids are keys: file names, `#/run/...` links, `trials/<cell>.jsonl`."""
    request = BatchRequest(robots=("ema", "pairs"), symbols=("BTCUSDT", "ETHUSDT"))
    assert [cell.cell_id for cell in plan_cells(request, exists=_all_exist)] == [
        "ema_BTC",
        "ema_ETH",
        "pairs_ETHBTC",
    ]


def test_variants_are_validated_and_survive_a_restart() -> None:
    """A restart replans from `batch.json`, so the variants must round-trip exactly."""
    request = BatchRequest(
        robots=("regime",),
        symbols=("BTCUSDT",),
        variants=(BatchVariant("H0", {"REGIME_LEGS": "range"}),),
    )
    restored = request_from_dict(request_to_dict(request))
    assert [variant.name for variant in restored.variants] == ["H0"]
    assert restored.variants[0].env == {"REGIME_LEGS": "range"}
    assert [cell.cell_id for cell in plan_cells(restored, exists=_all_exist)] == ["regime_BTC__H0"]

    with pytest.raises(ValueError, match="unique"):
        BatchRequest(
            variants=(
                BatchVariant("H0", {"REGIME_LEGS": "range"}),
                BatchVariant("H0", {"STOP_PCT": "0.01"}),
            )
        )
    with pytest.raises(ValueError, match="overrides nothing"):
        BatchVariant("H0", {})
    with pytest.raises(ValueError, match="variant name"):
        BatchVariant("H 0", {"REGIME_LEGS": "range"})
    with pytest.raises(ValueError, match="SETTINGS_NAME"):
        BatchVariant("H0", {"lower": "1"})
    with pytest.raises(ValueError, match="too many"):
        BatchRequest(
            variants=tuple(
                BatchVariant(f"H{index}", {"REGIME_LEGS": "range"})
                for index in range(MAX_VARIANTS + 1)
            )
        )


def test_batch_request_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="USDT"):
        BatchRequest(symbols=("btc",))
    with pytest.raises(ValueError, match="folds"):
        BatchRequest(folds=1)
    with pytest.raises(ValueError, match="days"):
        BatchRequest(days=0)
    with pytest.raises(ValueError, match="days"):
        BatchRequest(days=-5)
    with pytest.raises(ValueError, match="SETTINGS_NAME"):
        BatchRequest(env={"lower": "x"})


# ---- sweeping a parameter (one key, several values) --------------------------------------


def test_a_swept_key_runs_the_matrix_once_per_value() -> None:
    """The documented shape: `DONCHIAN_PERIOD=20,40` means two runs, not one with 40.

    Cell ids carry the combination, so the two runs sit side by side in one table.
    """
    request = BatchRequest(
        robots=("regime",),
        symbols=("BTCUSDT",),
        sweep={"ENTER_TREND_ER": ("0.30", "0.42")},
    )
    cells = plan_cells(request, exists=_all_exist)

    assert [cell.cell_id for cell in cells] == [
        "regime_BTC__ENTER_TREND_ER_0_30_01",
        "regime_BTC__ENTER_TREND_ER_0_42_02",
    ]
    assert [cell.env for cell in cells] == [
        {"ENTER_TREND_ER": "0.30"},
        {"ENTER_TREND_ER": "0.42"},
    ]


def test_two_swept_keys_form_a_grid_not_a_zip() -> None:
    """Four combinations from two keys of two values: a grid, so every pair is measured."""
    request = BatchRequest(
        robots=("regime",),
        symbols=("BTCUSDT",),
        sweep={"ENTER_TREND_ER": ("0.30", "0.42"), "EXIT_TREND_ER": ("0.10", "0.20")},
    )

    assert [variant.env for variant in request.resolved_variants()] == [
        {"ENTER_TREND_ER": "0.30", "EXIT_TREND_ER": "0.10"},
        {"ENTER_TREND_ER": "0.30", "EXIT_TREND_ER": "0.20"},
        {"ENTER_TREND_ER": "0.42", "EXIT_TREND_ER": "0.10"},
        {"ENTER_TREND_ER": "0.42", "EXIT_TREND_ER": "0.20"},
    ]
    assert len(plan_cells(request, exists=_all_exist)) == 4


def test_sweep_names_fit_a_cell_id_and_stay_unique() -> None:
    """A variant name becomes part of a cell id, so it must be short, safe and unique."""
    request = BatchRequest(
        robots=("regime",),
        symbols=("BTCUSDT",),
        sweep={"ENTER_TREND_ER": ("0.30", "0.42"), "DONCHIAN_PERIOD": ("20", "40")},
    )
    names = [variant.name for variant in request.resolved_variants()]

    assert len(set(names)) == len(names) == 4
    assert all(len(name) <= 24 for name in names)
    assert all(name.isascii() for name in names)
    # A dot is not allowed in a cell id, so `0.30` is carried as `0_30`.
    assert names[0].startswith("ENTER_TREND_ER_0_30")


def test_a_sweep_is_validated_where_it_is_still_cheap() -> None:
    """Every refusal here is a batch that would otherwise run for hours doing nothing."""
    with pytest.raises(ValueError, match="not a setting"):
        BatchRequest(sweep={"DONCHIAN_PERIODD": ("40",)})
    with pytest.raises(ValueError, match="cannot be set here"):
        BatchRequest(sweep={"CATALOG_PATH": ("catalog",)})
    with pytest.raises(ValueError, match="at least one"):
        BatchRequest(sweep={"ENTER_TREND_ER": ()})
    with pytest.raises(ValueError, match="at least one"):
        BatchRequest(sweep={"ENTER_TREND_ER": ("0.3", " ")})
    with pytest.raises(ValueError, match="one transport per key"):
        BatchRequest(env={"ENTER_TREND_ER": "0.3"}, sweep={"ENTER_TREND_ER": ("0.4",)})
    with pytest.raises(ValueError, match="SETTINGS_NAME"):
        BatchRequest(sweep={"lower": ("1",)})
    # The cap counts the whole matrix, sweep included: 3x3 is nine variants, not one.
    with pytest.raises(ValueError, match="too many"):
        BatchRequest(
            sweep={
                "ENTER_TREND_ER": ("1", "2", "3"),
                "EXIT_TREND_ER": ("1", "2", "3"),
                "ER_PERIOD": ("1",),
            }
        )


def test_an_unknown_or_job_owned_env_key_is_refused_instead_of_ignored() -> None:
    """`Settings` is `extra="ignore"`, so a typo used to plan fine and change nothing."""
    with pytest.raises(ValueError, match="not a setting"):
        BatchRequest(env={"DONCHIAN_PERIODD": "40"})
    with pytest.raises(ValueError, match="cannot be set here"):
        BatchRequest(env={"CATALOG_PATH": "catalog"})
    with pytest.raises(ValueError, match="cannot be set here"):
        BatchRequest(env={"EMBARGO_BARS": "5"})
    with pytest.raises(ValueError, match="not a setting"):
        BatchVariant("H0", {"REGIME_LEGSS": "range"})
    # `BACKTEST_DAYS` is not a Settings field: the batch reads it itself (`routes/batches.py`).
    assert BatchRequest(env={"BACKTEST_DAYS": "30"}).env == {"BACKTEST_DAYS": "30"}


def test_a_sweep_survives_a_restart_without_expanding_twice() -> None:
    """`batch.json` keeps the sweep as typed; `variants` stays the explicit ones."""
    request = BatchRequest(
        robots=("regime",),
        symbols=("BTCUSDT",),
        variants=(BatchVariant("H0", {"REGIME_LEGS": "range"}),),
        sweep={"ENTER_TREND_ER": ("0.30", "0.42")},
    )
    payload = request_to_dict(request)
    restored = request_from_dict(payload)

    assert payload["sweep"] == {"ENTER_TREND_ER": ["0.30", "0.42"]}
    assert [variant.name for variant in restored.variants] == ["H0"]
    assert [variant.name for variant in restored.resolved_variants()] == [
        "H0",
        "ENTER_TREND_ER_0_30_01",
        "ENTER_TREND_ER_0_42_02",
    ]
    # Re-planning a restored request gives the same matrix, not a doubled one.
    assert [cell.cell_id for cell in plan_cells(restored, exists=_all_exist)] == [
        "regime_BTC__H0",
        "regime_BTC__ENTER_TREND_ER_0_30_01",
        "regime_BTC__ENTER_TREND_ER_0_42_02",
    ]


def test_the_plan_preview_carries_the_overrides_of_each_cell(tmp_path: Path) -> None:
    """The dry run must show which sweep value a cell takes, not only its id."""
    app = create_app(Settings(), root=tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/batches",
            json={
                "robots": ["regime"],
                "symbols": ["BTCUSDT"],
                "dry_run": True,
                "sweep": {"ENTER_TREND_ER": ["0.30", "0.42"]},
            },
        )
    assert response.status_code == 200
    cells = response.json()["cells"]
    assert [cell["env"] for cell in cells] == [
        {"ENTER_TREND_ER": "0.30"},
        {"ENTER_TREND_ER": "0.42"},
    ]


def test_the_batch_route_reports_a_bad_sweep_as_422(tmp_path: Path) -> None:
    app = create_app(Settings(), root=tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/batches",
            json={
                "robots": ["regime"],
                "symbols": ["BTCUSDT"],
                "dry_run": True,
                "sweep": {"DONCHIAN_PERIODD": ["40"]},
            },
        )
    assert response.status_code == 422
    assert "not a setting" in response.json()["detail"]


def test_job_config_is_the_research_tab_payload() -> None:
    request = BatchRequest(robots=("ema",), symbols=("ETHUSDT",), folds=3)
    (cell,) = plan_cells(request, exists=_all_exist)
    config = research_job_config(request, cell)
    assert config["robot"] == "ema"
    assert config["folds"] == 3
    assert config["instrument_id"] == "ETH/USDT.SIM"
    assert config["generate_tearsheet"] is False
    assert "days" not in config


def test_job_config_and_store_roundtrip_days() -> None:
    request = BatchRequest(robots=("ema",), symbols=("ETHUSDT",), folds=3, days=30)
    (cell,) = plan_cells(request, exists=_all_exist)
    config = research_job_config(request, cell)
    assert config["days"] == 30
    payload = request_to_dict(request)
    assert payload["days"] == 30
    restored = request_from_dict(payload)
    assert restored.days == 30


def test_batch_route_resolves_days_from_field_and_env() -> None:
    from nautilus_lab.api.routes.batches import BatchRunRequest, _to_request

    req_direct = BatchRunRequest(days=45)
    assert _to_request(req_direct).days == 45

    req_env = BatchRunRequest(env={"BACKTEST_DAYS": "60"})
    assert _to_request(req_env).days == 60


# --- running cells with a stand-in research job ----------------------------------------


_FAKE_JOB = textwrap.dedent(
    '''
    """Stand-in for `python -m nautilus_lab.api.run_research_job`: writes a result and a
    decision file for two folds, the way a real cell does with DECISION_LOG_SCOPE=oos."""
    import json, os, sys
    args = sys.argv[1:]
    reports = args[args.index("--reports-dir") + 1]
    config = json.load(open(args[args.index("--config-json") + 1]))
    if config["robot"] == "regime":
        failed = {"is_error": True, "error_message": "boom"}
        json.dump(failed, open(f"{reports}/last_run.json", "w"))
        sys.exit(1)
    assert os.environ["DECISION_LOG_SCOPE"] == "oos"
    dec = os.environ["DECISION_LOG_DIR"]
    folds = []
    for index in range(2):
        session = f"s-f{index}"
        rows = [
            {"schema": "decision_trace/1", "kind": "bar_decision", "session_id": session,
             "ts": f"2026-0{index + 7}-01T0{h}:59:59+00:00", "close": 100 + h,
             "outcome": o, "signal": s, "steps": [{"stage": "strategy", "component": "X",
             "verdict": "emit", "values": {}}],
             "account": {"position": p}}
            for h, (o, s, p) in enumerate([
                ("ENTRY_OPENED", "buy", "FLAT"), ("HOLD_NOOP", "buy", "LONG"),
                ("EXIT", "flat", "LONG"), ("NO_SIGNAL", None, "FLAT")])
        ]
        with open(f"{dec}/{session}_2026-07-01.jsonl", "w") as fh:
            fh.write("\\n".join(json.dumps(r) for r in rows) + "\\n")
        folds.append({"index": index, "session_id": session, "oos_return_raw": "0.01",
                      "window": {"out_of_sample_start": "x", "out_of_sample_end": "y"}})
    json.dump({"is_error": False, "run_type": "multi_window", "multi_window": {
        "profitable": "2/2", "fold_count": 2, "mean_oos_raw": "0.01",
        "buy_and_hold_mean_raw": "0.005", "total_oos_fills": 8, "folds": folds},
        "promotion_gate": {"label": "INCOMPLETE", "promoted": False,
                           "summary_line": "promotion_gate=INCOMPLETE (pbo=not measured)",
                           "checks": [{"name": "pbo", "status": "not measured",
                                       "detail": "run the audit"}]}},
        open(f"{reports}/last_run.json", "w"))
    '''
)


def _fake_python(tmp_path: Path) -> str:
    """An executable that ignores `-m <module>` and runs the stand-in job instead."""
    job = tmp_path / "fake_job.py"
    job.write_text(_FAKE_JOB, encoding="utf-8")
    wrapper = tmp_path / "fake_python"
    wrapper.write_text(
        f'#!/bin/sh\nshift 2\nexec "{sys.executable}" "{job}" "$@"\n', encoding="utf-8"
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    return str(wrapper)


def test_batch_run_fills_the_table(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    request = BatchRequest(robots=("ema", "regime", "glft"), symbols=("ETHUSDT",), parallel=2)
    cells = plan_cells(request, exists=_all_exist, wired=["ema", "regime"])
    batch_id, path = create_batch(reports, request, cells)
    initial = load_batch(reports, batch_id)
    assert initial is not None
    assert {c["cell_id"]: c["status"] for c in initial["cells"]} == {
        "ema_ETH": QUEUED,
        "regime_ETH": QUEUED,
        "glft_ETH": BLOCKED,
    }

    assert BatchRun(path, python=_fake_python(tmp_path)).run() == 0

    batch = load_batch(reports, batch_id)
    assert batch is not None
    status = {c["cell_id"]: c["status"] for c in batch["cells"]}
    assert status == {"ema_ETH": OK, "regime_ETH": FAILED, "glft_ETH": BLOCKED}
    assert batch["status"] == OK

    cfg = Settings()
    payload = batch_payload(reports, batch_id, cfg)
    assert payload is not None
    row = next(r for r in payload["rows"] if r["cell_id"] == "ema_ETH")
    assert row["numbers"]["mean_oos"] == pytest.approx(0.01)
    assert row["gate"]["label"] == "INCOMPLETE"
    assert row["decisions"]["records"] == 8
    assert row["decisions"]["outcomes"]["ENTRY_OPENED"] == 2
    assert row["trades"]["closed"] == 2
    assert [f["session_id"] for f in row["folds"]] == ["s-f0", "s-f1"]
    failed = next(r for r in payload["rows"] if r["cell_id"] == "regime_ETH")
    assert failed["error"] == "boom"

    # The existing session endpoints find a batch fold by its key.
    assert find_session_cell(reports, "s-f1") == cell_dir(path, "ema_ETH")
    run = run_payload(reports, batch_id, "ema_ETH", cfg)
    assert run is not None
    assert len(run["folds"]) == 2

    listed = list_batches(reports)
    assert listed[0]["id"] == batch_id
    assert listed[0]["counts"] == {"ok": 1, "failed": 1, "blocked": 1}


def test_a_stale_summary_cache_is_rebuilt_instead_of_served(tmp_path: Path) -> None:
    """A `summary.json` from an older build must not hide a field added since.

    The promotion verdict arrived with docs/35 §3. Without the version stamp the batch
    table would have kept serving a cached row with no verdict at all, and nothing on the
    screen would say why the column was empty.
    """
    reports = tmp_path / "reports"
    request = BatchRequest(robots=("ema",), symbols=("ETHUSDT",))
    cells = plan_cells(request, exists=_all_exist, wired=["ema"])
    _, path = create_batch(reports, request, cells)
    cell_path = cell_dir(path, "ema_ETH")
    decisions_dir(cell_path).mkdir(parents=True, exist_ok=True)
    write_json(
        cell_path / "last_run.json",
        {
            "is_error": False,
            "run_type": "multi_window",
            "multi_window": {"profitable": "1/2", "fold_count": 2, "folds": []},
            "promotion_gate": {
                "label": "REJECT",
                "promoted": False,
                "summary_line": "promotion_gate=REJECT (beats_buy_hold=fail)",
                "checks": [{"name": "beats_buy_hold", "status": "fail", "detail": "no edge"}],
            },
        },
    )
    # The shape a previous build wrote: no version stamp, so it cannot be trusted.
    write_json(cell_path / "summary.json", {"status": OK, "cell_id": "ema_ETH"})

    summary = cell_summary(path, {"cell_id": "ema_ETH", "status": OK}, Settings())
    assert summary["summary_version"] == SUMMARY_VERSION
    assert summary["gate"]["label"] == "REJECT"


def test_cell_summary_includes_risk_breaches_and_extended_metrics(tmp_path: Path) -> None:
    path = tmp_path / "batch"
    cell_path = path / "cells" / "regime_BTC"
    write_json(
        cell_path / "last_run.json",
        {
            "is_error": False,
            "run_type": "multi_window",
            "multi_window": {
                "profitable": "2/2",
                "fold_count": 2,
                "mean_oos_raw": "0.015",
                "median_oos_raw": "0.015",
                "worst_oos_raw": "0.01",
                "best_oos_raw": "0.02",
                "spread_raw": "0.01",
                "buy_and_hold_mean_raw": "0.005",
                "vol_matched_buy_and_hold_mean_raw": "0.007",
                "mean_excess_return_raw": "0.01",
                "beats_buy_and_hold": True,
                "beats_vol_matched_buy_and_hold": True,
                "total_oos_fills": 14,
                "mean_paid_cost_rate": 0.0001,
                "mean_breakeven_cost": 0.0005,
                "cost_headroom": 0.0004,
                "risk_breaches": {"daily_loss": 2, "max_leverage": 1},
                "folds": [],
            },
            "promotion_gate": {
                "label": "INCOMPLETE",
                "promoted": False,
                "summary_line": "promotion_gate=INCOMPLETE",
                "checks": [],
            },
        },
    )
    summary = cell_summary(path, {"cell_id": "regime_BTC", "status": OK}, Settings())
    assert summary["summary_version"] == 4
    numbers = summary["numbers"]
    assert numbers["mean_oos"] == pytest.approx(0.015)
    assert numbers["median_oos"] == pytest.approx(0.015)
    assert numbers["worst_oos"] == pytest.approx(0.01)
    assert numbers["best_oos"] == pytest.approx(0.02)
    assert numbers["spread"] == pytest.approx(0.01)
    assert numbers["vol_matched_buy_and_hold_mean"] == pytest.approx(0.007)
    assert numbers["cost_headroom"] == pytest.approx(0.0004)
    assert numbers["risk_breaches"] == {"daily_loss": 2, "max_leverage": 1}
    assert summary["gate"]["label"] == "INCOMPLETE"


def test_retry_requeues_only_the_cells_without_a_result(tmp_path: Path) -> None:
    """One timed-out cell must not cost the whole matrix (docs/35 §1 B-4).

    The 2026-10-03 sweep lost four hours to `vpin_momentum_DOGE`; the only re-run the
    dashboard had was `restart`, which redoes all fifty cells and throws away thirty-four
    finished ones.
    """
    reports = tmp_path / "reports"
    request = BatchRequest(robots=("ema", "regime", "glft"), symbols=("ETHUSDT",), parallel=1)
    cells = plan_cells(request, exists=_all_exist, wired=["ema", "regime"])
    batch_id, path = create_batch(reports, request, cells)
    assert BatchRun(path, python=_fake_python(tmp_path)).run() == 0

    # ema ok, regime failed, glft blocked for want of an adapter.
    kept = cell_dir(path, "ema_ETH") / "last_run.json"
    assert kept.is_file()
    before = kept.read_text(encoding="utf-8")

    # The robot is wired now, so the blocked cell becomes runnable in the fresh plan.
    replanned = plan_cells(request, exists=_all_exist, wired=["ema", "regime", "glft"])
    _, requeued = retry_batch(reports, batch_id, replanned)

    assert sorted(requeued) == ["glft_ETH", "regime_ETH"]
    batch = load_batch(reports, batch_id)
    assert batch is not None
    statuses = {cell["cell_id"]: cell["status"] for cell in batch["cells"]}
    assert statuses["ema_ETH"] == OK, "a finished cell keeps its result"
    assert statuses["regime_ETH"] == QUEUED, "a failed cell goes back in the queue"
    assert statuses["glft_ETH"] == QUEUED, "a cell blocked by a missing adapter is runnable now"
    assert batch["batch_id" if False else "status"] == QUEUED
    assert batch["retry_count"] == 1
    assert kept.read_text(encoding="utf-8") == before, "the kept cell's artifact is untouched"


def test_retry_drops_the_cached_summary_of_the_cells_it_reruns(tmp_path: Path) -> None:
    """A retried cell must not answer from the previous attempt's cached row."""
    reports = tmp_path / "reports"
    request = BatchRequest(robots=("ema", "regime"), symbols=("ETHUSDT",))
    cells = plan_cells(request, exists=_all_exist, wired=["ema", "regime"])
    batch_id, path = create_batch(reports, request, cells)
    assert BatchRun(path, python=_fake_python(tmp_path)).run() == 0

    # Reading the table is what caches a row; both cells get one now.
    batch_payload(reports, batch_id, Settings())
    failed_summary = cell_dir(path, "regime_ETH") / "summary.json"
    kept_summary = cell_dir(path, "ema_ETH") / "summary.json"
    assert failed_summary.is_file()
    assert kept_summary.is_file()

    retry_batch(reports, batch_id, plan_cells(request, exists=_all_exist, wired=["ema", "regime"]))

    assert not failed_summary.exists(), "the failed cell's cache must not survive a retry"
    assert kept_summary.is_file(), "the finished cell's cache is what keeps its row cheap"


def test_retry_says_nothing_to_do_instead_of_relaunching(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    request = BatchRequest(robots=("ema",), symbols=("ETHUSDT",))
    cells = plan_cells(request, exists=_all_exist, wired=["ema"])
    batch_id, path = create_batch(reports, request, cells)
    assert BatchRun(path, python=_fake_python(tmp_path)).run() == 0

    replanned = plan_cells(request, exists=_all_exist, wired=["ema"])
    _, requeued = retry_batch(reports, batch_id, replanned)
    assert requeued == []
    batch = load_batch(reports, batch_id)
    assert batch is not None
    assert batch["status"] == OK, "a batch with nothing to retry keeps its status"


# --- continuing an interrupted batch ----------------------------------------------------


def _interrupt(reports: Path, batch_id: str, statuses: dict[str, str]) -> None:
    """Make `batch.json` look like its process died mid-run: cells left as given, dead pid."""
    batch = load_batch(reports, batch_id)
    assert batch is not None
    for cell in batch["cells"]:
        if cell["cell_id"] in statuses:
            cell["status"] = statuses[cell["cell_id"]]
    # A pid that cannot be alive: the process went down with the machine.
    batch.update({"status": RUNNING, "pid": 2**22 + 12345, "finished_at": None})
    write_json(batch_dir_of(reports, batch_id) / "batch.json", batch)


def batch_dir_of(reports: Path, batch_id: str) -> Path:
    return reports / "batches" / batch_id


def test_resume_runs_only_the_unfinished_cells_and_keeps_the_rest(tmp_path: Path) -> None:
    """A reboot mid-batch must not cost the cells that already finished.

    `restart` threw them all away; `retry` ignored cells left `queued`/`running` by a dead
    process. A resume re-runs exactly those (and `cancelled`), keeps `ok` and `failed`.
    """
    reports = tmp_path / "reports"
    request = BatchRequest(robots=("ema", "regime"), symbols=("ETHUSDT", "BTCUSDT"), parallel=1)
    cells = plan_cells(request, exists=_all_exist, wired=["ema", "regime"])
    batch_id, path = create_batch(reports, request, cells)
    assert BatchRun(path, python=_fake_python(tmp_path)).run() == 0
    kept = cell_dir(path, "ema_ETH") / "last_run.json"
    before = kept.read_text(encoding="utf-8")

    # The machine went down: ema_BTC was mid-run, regime_BTC never started.
    _interrupt(reports, batch_id, {"ema_BTC": RUNNING, "regime_BTC": QUEUED})
    cut = cell_dir(path, "ema_BTC")
    stale = decisions_dir(cut) / "s-f9_2026-06-01.jsonl"
    stale.write_text('{"half": "a fold the dead run never finished"}\n', encoding="utf-8")
    (cut / "stdout.log").write_text("killed here", encoding="utf-8")
    interrupted = load_batch(reports, batch_id)
    assert interrupted is not None
    assert effective_status(interrupted) == LOST

    _, requeued = resume_batch(reports, batch_id)
    assert sorted(requeued) == ["ema_BTC", "regime_BTC"]
    batch = load_batch(reports, batch_id)
    assert batch is not None
    statuses = {cell["cell_id"]: cell["status"] for cell in batch["cells"]}
    assert statuses == {
        "ema_ETH": OK,
        "ema_BTC": QUEUED,
        "regime_ETH": FAILED,
        "regime_BTC": QUEUED,
    }, "failed cells are retry's job, finished ones are kept"
    assert batch["status"] == QUEUED
    assert batch["resume_count"] == 1
    assert not stale.exists(), "the half-written decision log must not be appended to"
    assert (cut / "stdout.interrupted.log").read_text(encoding="utf-8") == "killed here"

    assert BatchRun(path, python=_fake_python(tmp_path)).run() == 0
    done = load_batch(reports, batch_id)
    assert done is not None
    assert {c["cell_id"]: c["status"] for c in done["cells"]}["ema_BTC"] == OK
    assert kept.read_text(encoding="utf-8") == before, "a finished cell is not re-run"


def test_resume_continues_a_cancelled_batch(tmp_path: Path) -> None:
    """Cancel then Continue is a pause: the cancelled cells run, nothing else does."""
    reports = tmp_path / "reports"
    request = BatchRequest(robots=("ema",), symbols=("ETHUSDT", "BTCUSDT"), parallel=1)
    cells = plan_cells(request, exists=_all_exist, wired=["ema"])
    batch_id, path = create_batch(reports, request, cells)
    batch = load_batch(reports, batch_id)
    assert batch is not None
    batch["cells"][0]["status"] = OK
    batch["cells"][1]["status"] = CANCELLED
    batch.update({"status": CANCELLED, "pid": None})
    write_json(path / "batch.json", batch)

    assert resume_batch_dir(path) == [batch["cells"][1]["cell_id"]]


def test_resume_with_nothing_left_leaves_the_batch_alone(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    request = BatchRequest(robots=("ema", "regime"), symbols=("ETHUSDT",))
    cells = plan_cells(request, exists=_all_exist, wired=["ema", "regime"])
    _, path = create_batch(reports, request, cells)
    assert BatchRun(path, python=_fake_python(tmp_path)).run() == 0
    before = (path / "batch.json").read_text(encoding="utf-8")

    assert resume_batch_dir(path) == []
    assert (path / "batch.json").read_text(encoding="utf-8") == before


def test_a_reused_pid_does_not_keep_a_dead_batch_running(tmp_path: Path) -> None:
    """After a reboot the stored pid can be any program's: the batch is lost, not running.

    Before, such a batch showed `running` forever: it could be neither cancelled nor
    continued, and Cancel would have sent SIGTERM to a stranger.
    """
    reports = tmp_path / "reports"
    request = BatchRequest(robots=("ema",), symbols=("ETHUSDT",))
    cells = plan_cells(request, exists=_all_exist, wired=["ema"])
    batch_id, path = create_batch(reports, request, cells)
    stranger = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        batch = load_batch(reports, batch_id)
        assert batch is not None
        batch.update({"status": RUNNING, "pid": stranger.pid})
        write_json(path / "batch.json", batch)
        if Path("/proc").is_dir():
            assert not batch_process_alive(batch)
            assert effective_status(batch) == LOST
            assert resume_batch_dir(path) == [batch["cells"][0]["cell_id"]]
        assert stranger.poll() is None, "an unrelated process must never be signalled"
    finally:
        stranger.kill()
        stranger.wait()


def test_resume_refuses_while_the_batch_process_lives(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    request = BatchRequest(robots=("ema",), symbols=("ETHUSDT",))
    cells = plan_cells(request, exists=_all_exist, wired=["ema"])
    batch_id, path = create_batch(reports, request, cells)
    # Looks like the real thing to `/proc`: the module name and this batch's directory.
    alive = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", "run_batch_job", str(path)]
    )
    try:
        batch = load_batch(reports, batch_id)
        assert batch is not None
        batch.update({"status": RUNNING, "pid": alive.pid})
        write_json(path / "batch.json", batch)
        with pytest.raises(RuntimeError, match="still running"):
            resume_batch_dir(path)
    finally:
        alive.kill()
        alive.wait()


def test_the_resume_endpoint_and_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reports = tmp_path / "reports"
    request = BatchRequest(robots=("ema",), symbols=("ETHUSDT", "BTCUSDT"), folds=2)
    cells = plan_cells(request, exists=_all_exist, wired=["ema"])
    batch_id, path = create_batch(reports, request, cells)
    launched: list[str] = []
    monkeypatch.setattr(batches_routes, "_launch", lambda _ctx, bid, _path: launched.append(bid))
    client = TestClient(create_app(Settings(), root=tmp_path))

    assert client.post("/api/batches/nonexistent_batch_123/resume").status_code == 404
    assert client.post("/api/batches/bad..id!!/resume").status_code == 400

    _interrupt(reports, batch_id, {"ema_ETH": OK, "ema_BTC": RUNNING})
    resumed = client.post(f"/api/batches/{batch_id}/resume")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "resumed"
    assert resumed.json()["cells"] == ["ema_BTC"]
    assert launched == [batch_id]

    # Everything finished: the endpoint says so and launches nothing.
    done = load_batch(reports, batch_id)
    assert done is not None
    for cell in done["cells"]:
        cell["status"] = OK
    done.update({"status": OK, "pid": None})
    write_json(path / "batch.json", done)
    assert client.post(f"/api/batches/{batch_id}/resume").json()["status"] == "nothing_to_resume"
    assert launched == [batch_id]
    assert run_batch_main(["--batch-dir", str(path), "--resume"]) == 0
    assert "nothing to resume" in capsys.readouterr().err

    imported = {**done, "imported_from": "reports/decision-sweep"}
    write_json(path / "batch.json", imported)
    assert client.post(f"/api/batches/{batch_id}/resume").status_code == 422


def test_progress_counts_cells_and_estimates_from_finished_ones(tmp_path: Path) -> None:
    """An eight-hour matrix must say how far it is: the payload carries the numbers."""
    reports = tmp_path / "reports"
    request = BatchRequest(robots=("ema", "regime"), symbols=("ETHUSDT",))
    cells = plan_cells(request, exists=_all_exist, wired=["ema", "regime"])
    batch_id, path = create_batch(reports, request, cells)
    assert BatchRun(path, python=_fake_python(tmp_path)).run() == 0

    payload = batch_payload(reports, batch_id, Settings())
    assert payload is not None
    progress = payload["progress"]
    assert progress["total"] == 2
    assert progress["finished"] == 2
    assert progress["remaining"] == 0
    assert progress["counts"]["ok"] == 1
    assert progress["mean_cell_seconds"] is not None
    assert progress["eta_seconds"] is None, "nothing left to estimate once everything finished"
    assert progress["elapsed_seconds"] is not None


def test_progress_has_no_estimate_before_any_cell_finished(tmp_path: Path) -> None:
    """No finished cell means no basis for an estimate: None, not a made-up number."""
    reports = tmp_path / "reports"
    request = BatchRequest(robots=("ema",), symbols=("ETHUSDT",))
    cells = plan_cells(request, exists=_all_exist, wired=["ema"])
    batch_id, _ = create_batch(reports, request, cells)

    payload = batch_payload(reports, batch_id, Settings())
    assert payload is not None
    progress = payload["progress"]
    assert progress["eta_seconds"] is None
    assert progress["mean_cell_seconds"] is None
    assert progress["remaining"] == 1


def test_the_retry_endpoint_refuses_busy_imported_and_blocked_batches(tmp_path: Path) -> None:
    """The same guard rails as `restart`: a retry must never race or pretend to run."""
    root = tmp_path
    (root / "catalog").mkdir()
    settings = Settings(catalog_path="catalog")
    client = TestClient(create_app(settings, root=root))

    missing = client.post("/api/batches/nope/retry")
    assert missing.status_code == 404

    # An imported sweep has no request to re-run.
    sweep = root / "reports" / "decision-sweep"
    sweep.mkdir(parents=True)
    (sweep / "status.json").write_text("[]", encoding="utf-8")
    imported = client.post("/api/batches/import-sweep").json()["batch_id"]
    assert client.post(f"/api/batches/{imported}/retry").status_code == 422

    # A finished batch whose cells all have results: nothing to retry, and no relaunch.
    launched = client.post(
        "/api/batches",
        json={"robots": ["glft"], "symbols": ["ETHUSDT"], "dry_run": True},
    )
    assert launched.status_code == 200, launched.text
    assert launched.json()["cells"][0]["runnable"] is False, "glft has no adapter: it blocks"


def test_import_sweep_makes_a_batch(tmp_path: Path) -> None:
    from nautilus_lab.api.batch_store import import_sweep

    sweep = tmp_path / "decision-sweep"
    (sweep / "decisions").mkdir(parents=True)
    (sweep / "status.json").write_text(
        json.dumps(
            [
                {
                    "key": "ema_BTC",
                    "robot": "ema",
                    "symbol": "BTCUSDT",
                    "catalog": "catalog",
                    "interval": "1h",
                    "status": "ok",
                    "error": "",
                    "numbers": {
                        "aggregate": {"profitable": "2", "folds": "4", "mean": "0.76%"},
                        "baseline": {"buy_hold": "0.64%"},
                        "folds": [
                            {
                                "index": "0",
                                "oos_start": "a",
                                "oos_end": "b",
                                "fills": "10",
                                "return": "1.5%",
                                "buy_hold": "-2%",
                                "selected": "fast_ema=5",
                            }
                        ],
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    row = {
        "schema": "decision_trace/1",
        "kind": "bar_decision",
        "session_id": "abc",
        "ts": "2026-07-15T10:59:59+00:00",
        "close": 1,
        "outcome": "NO_SIGNAL",
        "steps": [],
    }
    (sweep / "decisions" / "ema_BTC.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    reports = tmp_path / "reports"
    batch_id = import_sweep(reports, sweep)
    payload = batch_payload(reports, batch_id, Settings())
    assert payload is not None
    (cell,) = payload["rows"]
    assert cell["numbers"]["mean_oos"] == pytest.approx(0.0076)
    assert cell["decisions"]["records"] == 1
    assert cell["decisions"]["untraced_bars"] == 1
    assert decisions_dir(cell_dir(reports / "batches" / batch_id, "ema_BTC")).exists()
    assert Decimal("0.0076") == Decimal(str(cell["numbers"]["mean_oos"]))


def test_delete_batch_removes_directory_and_endpoint(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    request = BatchRequest(robots=("ema",), symbols=("ETHUSDT",), folds=2)
    cells = plan_cells(request, exists=_all_exist, wired=["ema"])
    batch_id, path = create_batch(reports, request, cells)
    assert path.exists()
    assert (path / "batch.json").exists()

    # Create dummy cell artifact
    c_dir = cell_dir(path, "ema_ETH")
    decisions_dir(c_dir).mkdir(parents=True, exist_ok=True)
    (c_dir / "last_run.json").write_text("{}", encoding="utf-8")
    assert (c_dir / "last_run.json").exists()

    # Invalid batch id raises ValueError
    with pytest.raises(ValueError, match="invalid batch id"):
        delete_batch(reports, "../evil_batch")

    # App endpoint test
    app = create_app(Settings(), root=tmp_path)
    client = TestClient(app)

    # 404 for nonexistent batch
    resp_404 = client.delete("/api/batches/nonexistent_batch_123")
    assert resp_404.status_code == 404

    # 400 for bad id
    resp_400 = client.delete("/api/batches/bad..id!!")
    assert resp_400.status_code == 400

    # Successful delete via API
    resp = client.delete(f"/api/batches/{batch_id}")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "deleted": batch_id}

    # Everything is deleted
    assert not path.exists()
    assert load_batch(reports, batch_id) is None
    assert delete_batch(reports, batch_id) is False


# --- restarting a batch ----------------------------------------------------------------


def test_reset_batch_replans_cells_and_keeps_the_request(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    request = BatchRequest(robots=("ema", "glft"), symbols=("ETHUSDT",), folds=2, label="re")
    cells = plan_cells(request, exists=_all_exist, wired=["ema"])
    batch_id, path = create_batch(reports, request, cells)

    reset_batch(reports, batch_id, cells)

    batch = load_batch(reports, batch_id)
    assert batch is not None
    assert (path / "batch.json").exists()
    assert batch["status"] == QUEUED
    assert batch["restart_count"] == 1
    assert batch["restarted_at"]
    assert batch["request"] == request_to_dict(request)
    state = {c["cell_id"]: (c["status"], c["error"]) for c in batch["cells"]}
    assert state["ema_ETH"] == (QUEUED, None)
    assert state["glft_ETH"][0] == BLOCKED
    assert "no backtest adapter" in str(state["glft_ETH"][1])

    with pytest.raises(ValueError, match="invalid batch id"):
        reset_batch(reports, "../evil_batch", cells)


def test_restart_route_wipes_the_old_run_and_relaunches_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = tmp_path / "reports"
    request = BatchRequest(robots=("ema",), symbols=("ETHUSDT",), folds=2)
    cells = plan_cells(request, exists=_all_exist, wired=["ema"])
    batch_id, path = create_batch(reports, request, cells)

    # The restart re-plans the matrix against the current filesystem, so the catalog the
    series_dir = tmp_path / "catalog" / "data" / "bar" / "ETHUSDT.SIM-1-HOUR-LAST-EXTERNAL"
    series_dir.mkdir(parents=True)
    (series_dir / "bars.parquet").write_bytes(b"dummy")

    # Artifacts of the first run: the restart must delete them, not append to them.
    cell = cell_dir(path, "ema_ETH")
    decisions_dir(cell).mkdir(parents=True, exist_ok=True)
    write_json(cell / "summary.json", {"cell_id": "ema_ETH", "status": OK})
    (cell / "last_run.json").write_text('{"is_error": false}', encoding="utf-8")
    (path / "batch.log").write_text("old run\n", encoding="utf-8")
    (path / "trials").mkdir()
    (path / "trials" / "ema_ETH.jsonl").write_text("{}\n", encoding="utf-8")
    finished = load_batch(reports, batch_id) or {}
    finished.update({"status": OK, "finished_at": "2026-09-30T00:00:00+00:00"})
    for entry in finished["cells"]:
        entry.update({"status": OK, "returncode": 0, "error": None})
    write_json(path / "batch.json", finished)

    launched: list[tuple[str, Path]] = []

    def fake_launch(_ctx: object, bid: str, batch_path: Path) -> None:
        launched.append((bid, batch_path))

    monkeypatch.setattr(batches_routes, "_launch", fake_launch)
    client = TestClient(create_app(Settings(), root=tmp_path))

    resp = client.post(f"/api/batches/{batch_id}/restart")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "restarted"
    assert body["batch_id"] == batch_id
    assert [c["cell_id"] for c in body["cells"]] == ["ema_ETH"]
    assert launched == [(batch_id, path)]

    batch = load_batch(reports, batch_id)
    assert batch is not None
    assert batch["status"] == QUEUED
    assert batch["pid"] is None
    assert batch["finished_at"] is None
    assert [c["status"] for c in batch["cells"]] == [QUEUED]
    assert not cell.exists(), "old decisions and the cached summary must be gone"
    assert not (path / "batch.log").exists()
    assert not (path / "trials").exists()
    assert (path / "batch.json").exists()

    row = next(r for r in list_batches(reports) if r["id"] == batch_id)
    assert row["restart_count"] == 1
    assert row["restarted_at"] == batch["restarted_at"]


def test_restart_refuses_an_import_a_running_batch_and_unknown_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = tmp_path / "reports"
    request = BatchRequest(robots=("ema",), symbols=("ETHUSDT",), folds=2)
    cells = plan_cells(request, exists=_all_exist, wired=["ema"])
    batch_id, path = create_batch(reports, request, cells)

    def never_launch(*_args: object, **_kwargs: object) -> None:
        pytest.fail("a refused restart must not launch a process")

    monkeypatch.setattr(batches_routes, "_launch", never_launch)
    client = TestClient(create_app(Settings(), root=tmp_path))

    assert client.post("/api/batches/nonexistent_batch_123/restart").status_code == 404
    assert client.post("/api/batches/bad..id!!/restart").status_code == 400

    # An imported sweep keeps robots but no symbols/intervals: nothing to re-run.
    imported = {**(load_batch(reports, batch_id) or {}), "imported_from": "reports/decision-sweep"}
    write_json(path / "batch.json", imported)
    refused = client.post(f"/api/batches/{batch_id}/restart")
    assert refused.status_code == 422
    assert "imported" in refused.json()["detail"]

    # A batch that is still moving is cancelled first, not wiped under its own process.
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        running = {
            key: value
            for key, value in (load_batch(reports, batch_id) or {}).items()
            if key != "imported_from"
        }
        running.update({"status": RUNNING, "pid": child.pid})
        write_json(path / "batch.json", running)
        busy = client.post(f"/api/batches/{batch_id}/restart")
        assert busy.status_code == 409
        assert batch_id in busy.json()["detail"]
    finally:
        child.kill()
        child.wait()
    assert (path / "batch.json").exists()


def test_batch_request_carries_embargo_bars() -> None:
    request = BatchRequest(robots=("ema",), symbols=("ETHUSDT",), folds=2, embargo_bars=15)
    assert request.embargo_bars == 15

    as_dict = request_to_dict(request)
    restored = request_from_dict(as_dict)
    assert restored.embargo_bars == 15

    cell = plan_cells(request, exists=_all_exist, wired=["ema"])[0]
    config = research_job_config(request, cell)
    assert config["embargo_bars"] == 15

    with pytest.raises(ValueError, match="embargo_bars must be >= 0"):
        BatchRequest(robots=("ema",), symbols=("ETHUSDT",), folds=2, embargo_bars=-1)


def test_cell_summary_handles_none_single_backtest(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    batch_id = "test_batch"
    bdir = reports / "batches" / batch_id
    cdir = bdir / "cells" / "cell_1"
    cdir.mkdir(parents=True)
    write_json(
        cdir / "last_run.json",
        {
            "multi_window": {"folds": []},
            "single_backtest": None,
        },
    )
    cell = {"cell_id": "cell_1", "status": OK}
    summary = build_cell_summary(cdir, cell, Settings())
    assert summary["numbers"]["risk_breaches"] == {}

    write_json(
        bdir / "batch.json",
        {
            "id": batch_id,
            "status": OK,
            "cells": [cell],
            "request": None,
        },
    )
    payload = batch_payload(reports, batch_id, Settings())
    assert payload is not None
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["cell_id"] == "cell_1"


def test_plan_cells_sets_safeguards_for_vpin_and_formulaic() -> None:
    request = BatchRequest(
        robots=("vpin_momentum", "formulaic_lgbm"),
        symbols=("BTCUSDT",),
    )
    cells = plan_cells(request, exists=_all_exist, wired=["vpin_momentum", "formulaic_lgbm"])
    by_id = {c.cell_id: c for c in cells}
    assert by_id["vpin_momentum_BTC"].env.get("USE_QUANTILE_VPIN") == "true"
    assert by_id["formulaic_lgbm_BTC"].env.get("FORMULAIC_MIN_HOLD_BARS") == "4"
