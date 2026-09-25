"""The dashboard's generated types match the API (docs/27 E-2.3).

Two ways they could drift: someone changes a response model and forgets to regenerate
`api.gen.ts`, or a route sends something its model does not describe. Both fail here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from nautilus_lab.api import responses
from nautilus_lab.api.app import create_app
from nautilus_lab.api.jobs import JobManager
from nautilus_lab.infrastructure.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "gen_api_types", ROOT / "scripts" / "gen_api_types.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_generated_typescript_is_up_to_date() -> None:
    generator = _generator()
    committed = generator.OUTPUT.read_text(encoding="utf-8")
    assert committed == generator.render(), (
        "frontend/src/services/api.gen.ts is stale: run `uv run python scripts/gen_api_types.py`"
    )


def test_every_response_model_is_generated() -> None:
    text = _generator().render()
    for model in responses.RESPONSE_MODELS:
        assert f"export interface {model.__name__} {{" in text, model.__name__


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        ({"type": "string"}, "string"),
        ({"anyOf": [{"type": "integer"}, {"type": "null"}]}, "number | null"),
        ({"type": "array", "items": {"$ref": "#/$defs/JobState"}}, "JobState[]"),
        (
            {"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
            "(string | null)[]",
        ),
        ({"enum": ["a", "b"], "type": "string"}, '"a" | "b"'),
        ({"type": "object", "additionalProperties": {"type": "string"}}, "Record<string, string>"),
        ({}, "Record<string, unknown>"),
    ],
)
def test_json_schema_nodes_become_typescript(schema: dict[str, Any], expected: str) -> None:
    assert _generator().ts_type(schema) == expected


def test_an_unsupported_schema_fails_instead_of_guessing() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        _generator().ts_type({"type": "tuple-of-dreams"})


# ---- what the routes actually send ----------------------------------------------------


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    jobs = JobManager(reports_dir=tmp_path / "reports", python="python", schedule=lambda _: None)
    cfg = Settings(_env_file=None)  # type: ignore[call-arg]
    return TestClient(create_app(cfg, root=tmp_path, jobs=jobs))


def _conforms(model: type[BaseModel], body: dict[str, Any], *, all_fields: bool = True) -> None:
    model.model_validate(body)
    if all_fields:
        missing = set(model.model_fields) - set(body)
        assert not missing, f"{model.__name__}: the route does not send {sorted(missing)}"


def test_status_and_health_match_their_models(client: TestClient) -> None:
    _conforms(responses.StatusResponse, client.get("/api/status").json())
    _conforms(responses.HealthResponse, client.get("/healthz").json())
    for job in client.get("/api/status").json()["jobs"].values():
        _conforms(responses.JobState, job)


def test_catalog_list_and_ingest_log_match_their_models(client: TestClient) -> None:
    _conforms(responses.CatalogsResponse, client.get("/api/catalogs").json())
    _conforms(responses.JobLogResponse, client.get("/api/catalog/ingest/log").json())


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/catalog/ingest", {"symbols": "ETHUSDT"}),
        ("/api/paper/run", {"robot": "regime", "bars": 200}),
        ("/api/ml/train", {}),
        ("/api/research/cancel", None),
        ("/api/catalog/ingest/cancel", None),
        ("/api/ml/train/cancel", None),
        ("/api/paper/cancel", None),
    ],
)
def test_actions_answer_with_an_action_result(
    client: TestClient, path: str, body: dict[str, Any] | None
) -> None:
    reply = client.post(path, json=body) if body is not None else client.post(path)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    _conforms(responses.ActionResult, data, all_fields=False)
    assert None not in data.values(), "unset fields are left out, as before the model"
