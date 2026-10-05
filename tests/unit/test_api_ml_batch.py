from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from nautilus_lab.api.app import create_app
from nautilus_lab.api.ml_runner import MLTrainConfig, execute_ml_train, list_models
from nautilus_lab.infrastructure.settings import Settings


def _cfg() -> Settings:
    return Settings(_env_file=None, catalog_path="catalogs/test")  # type: ignore[call-arg]


def test_list_models_enriches_with_card(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    clean_dir = models_dir / "clean"
    clean_dir.mkdir(parents=True)

    model_file = clean_dir / "formulaic_BTC_preoos.txt"
    model_file.write_text("dummy model content", encoding="utf-8")

    card_file = clean_dir / "formulaic_BTC_preoos.txt.card.json"
    card_data = {
        "bar_type": "BTC/USDT.SIM-1-HOUR-LAST-EXTERNAL",
        "horizon": 5,
        "instrument_id": "BTC/USDT.SIM",
        "model_sha256": "abc123",
        "robot": "formulaic_lgbm",
        "rows": 12000,
        "schema": "model_card/1",
        "train_first_ts": "2024-01-01T00:00:00+00:00",
        "train_last_ts": "2025-01-01T00:00:00+00:00",
    }
    card_file.write_text(json.dumps(card_data), encoding="utf-8")

    models = list_models(models_dir)
    assert len(models) == 1
    m = models[0]
    assert m["filename"] == "formulaic_BTC_preoos.txt"
    assert m["instrument_id"] == "BTC/USDT.SIM"
    assert m["robot"] == "formulaic_lgbm"
    assert m["rows"] == 12000
    assert m["horizon"] == 5


def test_delete_ml_model_endpoint(tmp_path: Path) -> None:
    app = create_app(_cfg(), root=tmp_path)
    client = TestClient(app)

    # Models dir in app root or cwd
    models_dir = Path("models")
    models_dir.mkdir(exist_ok=True)
    test_model = models_dir / "_test_dummy_model.txt"
    test_model.write_text("model data", encoding="utf-8")
    test_card = models_dir / "_test_dummy_model.txt.card.json"
    test_card.write_text("{}", encoding="utf-8")

    try:
        # Delete invalid non-existent model
        res_bad = client.delete("/api/ml/models/models/nonexistent.txt")
        assert res_bad.status_code == 200
        assert res_bad.json()["status"] == "error"

        # Delete existing model
        res_ok = client.delete(f"/api/ml/models/{test_model.as_posix()}")
        assert res_ok.status_code == 200
        assert res_ok.json()["status"] == "ok"
        assert not test_model.exists()
        assert not test_card.exists()
    finally:
        test_model.unlink(missing_ok=True)
        test_card.unlink(missing_ok=True)


def test_execute_ml_train_batch_handles_failures(tmp_path: Path) -> None:
    # Test batch config with nonexistent catalog
    job = MLTrainConfig(
        model_types=("formulaic", "meta_label"),
        instruments=("BTC/USDT", "ETH/USDT"),
        catalog_path=str(tmp_path / "empty_catalog"),
    )
    result, log_text = execute_ml_train(job)
    assert result["is_finished"] is True
    assert result["model_type"] == "batch"
    assert result["total_tasks"] == 4
    assert len(result["runs"]) == 4
    # All 4 failed because catalog is empty
    assert result["succeeded"] == 0
    assert result["is_error"] is True
    assert "Starting ML Batch Training: 2 model(s) x 2 instrument(s)" in log_text
