"""/healthz, /readyz and /api/metrics on the real app (docs/27 E-1.5/E-1.6)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from nautilus_lab.api.app import app


def test_healthz_answers_without_a_token() -> None:
    res = TestClient(app).get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_readyz_reports_status_and_problems() -> None:
    res = TestClient(app).get("/readyz")
    body = res.json()
    assert res.status_code == (200 if body["status"] == "ready" else 503)
    assert isinstance(body["problems"], list)
    assert isinstance(body["feeds"], list)
    assert "equity" not in res.text, "readiness is public; balances are not"


def test_metrics_are_served_as_prometheus_text() -> None:
    res = TestClient(app).get("/api/metrics")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    assert "nautilus_lab_ready " in res.text
    assert "nautilus_lab_info{" in res.text
