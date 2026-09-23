from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nautilus_lab.api.app import app
from nautilus_lab.api.run_paper_job import main as run_paper_job_main
from nautilus_lab.api.run_research_job import main as run_research_job_main


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_api_root_and_status(client: TestClient) -> None:
    res_root = client.get("/")
    assert res_root.status_code in (200, 404)  # depends on frontend dist existence

    res_status = client.get("/api/status")
    assert res_status.status_code == 200
    data = res_status.json()
    assert "research_running" in data
    assert "ingest_running" in data


def test_api_strategies(client: TestClient) -> None:
    res = client.get("/api/strategies")
    assert res.status_code == 200
    data = res.json()
    assert "strategies" in data
    assert len(data["strategies"]) > 0


def test_api_reports(client: TestClient) -> None:
    res = client.get("/api/reports")
    assert res.status_code == 200
    data = res.json()
    assert "reports" in data


def test_api_research_history_and_logs(client: TestClient) -> None:
    res_log = client.get("/api/research/log")
    assert res_log.status_code == 200

    res_history = client.get("/api/research/history")
    assert res_history.status_code == 200
    assert "history" in res_history.json()

    res_not_found = client.get("/api/research/history/non_existent_history_id_12345")
    assert res_not_found.status_code == 404


def test_api_catalog_logs_and_details(client: TestClient) -> None:
    res_ingest_log = client.get("/api/catalog/ingest/log")
    assert res_ingest_log.status_code == 200

    res_cat = client.get("/api/catalog")
    assert res_cat.status_code == 200


def test_api_settings_schema_and_update(client: TestClient) -> None:
    res_schema = client.get("/api/settings/schema")
    assert res_schema.status_code == 200
    assert "groups" in res_schema.json()

    res_settings = client.get("/api/settings")
    assert res_settings.status_code == 200

    # Оновлення з невалідним ключем
    res_bad_put = client.put("/api/settings", json={"settings": {"INVALID_KEY": "123"}})
    assert res_bad_put.status_code == 400


def test_api_cancel_endpoints_when_idle(client: TestClient) -> None:
    assert client.post("/api/research/cancel").status_code == 200
    assert client.post("/api/catalog/ingest/cancel").status_code == 200
    assert client.post("/api/ml/train/cancel").status_code == 200
    assert client.post("/api/paper/cancel").status_code == 200


def test_api_scan_triangular(client: TestClient) -> None:
    res = client.post("/api/scan/triangular")
    assert res.status_code == 200
    data = res.json()
    assert "opportunities" in data


def test_run_paper_job_cli(tmp_path: Path) -> None:
    cfg_file = tmp_path / "paper_cfg.json"
    # 150 bars is the warm-up floor for `regime`; a shorter session is refused rather
    # than silently run with indicators that never warmed up.
    cfg_file.write_text(
        json.dumps({"robot": "regime", "bars": 200, "source": "synthetic"}),
        encoding="utf-8",
    )
    code = run_paper_job_main(["--config-json", str(cfg_file), "--reports-dir", str(tmp_path)])
    assert code == 0
    assert (tmp_path / "paper.log").exists()
    assert (tmp_path / "paper.json").exists()
    payload = json.loads((tmp_path / "paper.json").read_text(encoding="utf-8"))
    assert payload["is_error"] is False
    assert payload["mode"] == "paper"
    assert payload["robot"] == "regime"
    assert "no order was submitted" in payload["disclaimer"]


def test_run_research_job_cli(tmp_path: Path) -> None:
    cfg_file = tmp_path / "research_cfg.json"
    cfg_file.write_text(
        json.dumps(
            {
                "robot": "regime",
                "source": "synthetic",
                "bars": 300,
                "folds": 1,
                "full_sample": True,
                "generate_tearsheet": False,
            }
        ),
        encoding="utf-8",
    )
    code = run_research_job_main(["--config-json", str(cfg_file), "--reports-dir", str(tmp_path)])
    assert code == 0
    assert (tmp_path / "last_run.json").exists()


def test_run_ml_job_cli(tmp_path: Path) -> None:
    from nautilus_lab.api.run_ml_job import main as run_ml_job_main

    cfg_file = tmp_path / "ml_cfg.json"
    cfg_file.write_text(
        json.dumps({"model_type": "formulaic", "catalog_path": str(tmp_path / "nonexistent")}),
        encoding="utf-8",
    )
    code = run_ml_job_main(["--config-json", str(cfg_file), "--reports-dir", str(tmp_path)])
    assert code == 1
    assert (tmp_path / "ml_train.log").exists()
    assert (tmp_path / "ml_train.json").exists()


def test_api_hypotheses_endpoints(client: TestClient) -> None:
    res = client.get("/api/hypotheses")
    assert res.status_code == 200
    data = res.json()
    assert "hypotheses" in data
    assert isinstance(data["hypotheses"], list)
    if data["hypotheses"]:
        first = data["hypotheses"][0]
        assert "file" in first
        assert "url" in first
        detail_res = client.get(f"/api/hypotheses/{first['file']}")
        assert detail_res.status_code == 200
        assert "hypotheses" in detail_res.json()

    # Bad paths
    assert client.get("/api/hypotheses/nonexistent_file_xyz.json").status_code == 404
    assert client.get("/api/hypotheses/..evil").status_code == 400
