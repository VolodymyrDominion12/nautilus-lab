from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nautilus_lab.api.app import app
from nautilus_lab.api.command_center import build_command_center, scan_triangular_demo
from nautilus_lab.api.journal_service import list_journal_entries, update_journal_decision
from nautilus_lab.api.ml_runner import list_models
from nautilus_lab.application.journal import PENDING, JournalEntry


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_command_center_payload(tmp_path: Path) -> None:
    payload = build_command_center(
        reports_dir=tmp_path,
        catalog_dir="/tmp/catalog",
        research_running=False,
        ingest_running=False,
        ml_running=False,
        paper_running=False,
    )
    assert payload["safety"]["mode"] == "FAIL_CLOSED"
    assert "jobs" in payload
    assert payload["jobs"]["ml_train"]["label"] == "LightGBM training"


def test_scan_triangular_demo() -> None:
    result = scan_triangular_demo()
    assert "opportunities" in result
    assert result["note"]


def test_list_models_returns_list() -> None:
    models = list_models(Path("models"))
    assert isinstance(models, list)


def test_journal_api_empty(client: TestClient) -> None:
    response = client.get("/api/journal")
    assert response.status_code == 200
    assert "entries" in response.json()


def test_journal_patch_invalid_decision(client: TestClient) -> None:
    response = client.patch("/api/journal/0", json={"decision": "invalid"})
    assert response.status_code == 400


def test_command_center_route(client: TestClient) -> None:
    response = client.get("/api/command-center")
    assert response.status_code == 200
    body = response.json()
    assert body["safety"]["live_enabled"] is False


def test_ml_models_route(client: TestClient) -> None:
    response = client.get("/api/ml/models")
    assert response.status_code == 200
    assert "models" in response.json()


def test_propose_dry_run(client: TestClient) -> None:
    response = client.post("/api/propose", json={"count": 3, "dry_run": True})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dry_run"
    assert "prompt" in body


def test_catalogs_route(client: TestClient) -> None:
    response = client.get("/api/catalogs")
    assert response.status_code == 200
    body = response.json()
    assert "default" in body
    assert isinstance(body["catalogs"], list)


def test_paper_log_route(client: TestClient) -> None:
    response = client.get("/api/paper/log")
    assert response.status_code == 200
    assert "summary" in response.json()


def test_update_journal_decision_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jsonl = tmp_path / "journal.jsonl"
    entry = JournalEntry(
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        source="test",
        subject="regime walk-forward",
        gates="walk-forward",
        decision=PENDING,
    )
    jsonl.write_text(json.dumps(entry.as_dict()) + "\n", encoding="utf-8")

    def fake_journal_paths(_cfg: object) -> tuple[Path, Path]:
        return tmp_path, jsonl

    monkeypatch.setattr("nautilus_lab.api.journal_service.journal_paths", fake_journal_paths)
    rows = list_journal_entries()
    assert len(rows) == 1
    updated = update_journal_decision(0, "accepted")
    assert updated["decision"] == "accepted"
