"""Batch backtest: planning the matrix, running cells, and the table rows (docs/30)."""

from __future__ import annotations

import json
import stat
import sys
import textwrap
from decimal import Decimal
from pathlib import Path

import pytest

from nautilus_lab.api.batch_store import (
    BLOCKED,
    FAILED,
    OK,
    QUEUED,
    batch_payload,
    cell_dir,
    create_batch,
    decisions_dir,
    find_session_cell,
    list_batches,
    load_batch,
    request_from_dict,
    request_to_dict,
    run_payload,
)
from nautilus_lab.api.run_batch_job import BatchRun
from nautilus_lab.application.batch_plan import BatchRequest, plan_cells, research_job_config
from nautilus_lab.infrastructure.settings import Settings


def _all_exist(_path: str) -> bool:
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
        "buy_and_hold_mean_raw": "0.005", "total_oos_fills": 8, "folds": folds}},
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
    assert {c["cell_id"]: c["status"] for c in load_batch(reports, batch_id)["cells"]} == {
        "ema_ETH": QUEUED,
        "regime_ETH": QUEUED,
        "glft_ETH": BLOCKED,
    }

    assert BatchRun(path, python=_fake_python(tmp_path)).run() == 0

    batch = load_batch(reports, batch_id)
    status = {c["cell_id"]: c["status"] for c in batch["cells"]}
    assert status == {"ema_ETH": OK, "regime_ETH": FAILED, "glft_ETH": BLOCKED}
    assert batch["status"] == OK

    cfg = Settings()
    payload = batch_payload(reports, batch_id, cfg)
    assert payload is not None
    row = next(r for r in payload["rows"] if r["cell_id"] == "ema_ETH")
    assert row["numbers"]["mean_oos"] == pytest.approx(0.01)
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
