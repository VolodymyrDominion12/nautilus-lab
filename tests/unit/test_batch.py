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
    FAILED,
    OK,
    QUEUED,
    RUNNING,
    SUMMARY_VERSION,
    batch_payload,
    cell_dir,
    cell_summary,
    create_batch,
    decisions_dir,
    delete_batch,
    find_session_cell,
    list_batches,
    load_batch,
    request_from_dict,
    request_to_dict,
    reset_batch,
    run_payload,
    write_json,
)
from nautilus_lab.api.routes import batches as batches_routes
from nautilus_lab.api.run_batch_job import BatchRun
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
        BatchRequest(variants=(BatchVariant("H0", {"A": "1"}), BatchVariant("H0", {"B": "2"})))
    with pytest.raises(ValueError, match="overrides nothing"):
        BatchVariant("H0", {})
    with pytest.raises(ValueError, match="variant name"):
        BatchVariant("H 0", {"A": "1"})
    with pytest.raises(ValueError, match="SETTINGS_NAME"):
        BatchVariant("H0", {"lower": "1"})
    with pytest.raises(ValueError, match="too many"):
        BatchRequest(
            variants=tuple(
                BatchVariant(f"H{index}", {"A": "1"}) for index in range(MAX_VARIANTS + 1)
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
