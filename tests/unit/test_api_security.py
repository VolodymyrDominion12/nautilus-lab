import pytest

from nautilus_lab.api.security import DEFAULT_ALLOWED_ORIGINS, ApiSecurity


def _refusal(security: ApiSecurity, **overrides: str | None) -> str | None:
    request: dict[str, str | None] = {
        "method": "PUT",
        "path": "/api/settings",
        "origin": None,
        "presented_token": None,
    }
    request.update(overrides)
    return security.refusal(
        method=str(request["method"]),
        path=str(request["path"]),
        origin=request["origin"],
        presented_token=request["presented_token"],
    )


def test_foreign_origin_is_refused_even_without_a_token() -> None:
    """The attack: any page in the browser rewriting .env through the dashboard API."""
    reason = _refusal(ApiSecurity(), origin="https://evil.example")
    assert reason is not None and "origin" in reason


def test_dashboard_origin_and_non_browser_clients_pass_without_a_token() -> None:
    assert _refusal(ApiSecurity(), origin="http://localhost:5173") is None
    assert _refusal(ApiSecurity(), origin="http://localhost:5173/") is None
    assert _refusal(ApiSecurity(), origin=None) is None


def test_preflight_is_left_to_cors() -> None:
    assert _refusal(ApiSecurity(), method="OPTIONS", origin="https://evil.example") is None


def test_token_is_required_on_api_paths_when_configured() -> None:
    security = ApiSecurity(token="s3cret")
    assert _refusal(security) == "missing or invalid API token"
    assert _refusal(security, presented_token="wrong") == "missing or invalid API token"
    assert _refusal(security, presented_token="s3cret") is None
    # Static tearsheets are embedded in an iframe, which cannot send a header.
    assert _refusal(security, method="GET", path="/static_reports/x.html") is None


def test_from_values_parses_and_falls_back_to_defaults() -> None:
    parsed = ApiSecurity.from_values(origins=" http://a:1/ , http://b:2 ", token=" t ")
    assert parsed.allowed_origins == ("http://a:1", "http://b:2")
    assert parsed.token == "t"
    assert ApiSecurity.from_values(origins="", token="").allowed_origins == DEFAULT_ALLOWED_ORIGINS


def test_paper_role_refuses_research_and_settings_writes() -> None:
    paper = ApiSecurity.from_values(origins="", token="", role="paper")
    for method, path in [
        ("PUT", "/api/settings"),
        ("POST", "/api/research"),
        ("POST", "/api/catalog/ingest"),
        ("POST", "/api/ml/train"),
        ("POST", "/api/propose"),
        ("POST", "/api/paper/run"),
        ("PATCH", "/api/journal/3"),
    ]:
        reason = _refusal(paper, method=method, path=path)
        assert reason is not None and "LAB_ROLE=paper" in reason, (method, path)


def test_paper_role_keeps_reads_and_live_terminal_controls() -> None:
    paper = ApiSecurity.from_values(origins="", token="", role="paper")
    for method, path in [
        ("GET", "/api/status"),
        ("GET", "/api/paper/live/state"),
        ("GET", "/api/paper/live-stream"),
        ("POST", "/api/paper/live/start"),
        ("POST", "/api/paper/live/stop"),
        ("POST", "/api/paper/live/close-position"),
        ("POST", "/api/paper/live/update-stops"),
        ("OPTIONS", "/api/research"),
    ]:
        assert _refusal(paper, method=method, path=path) is None, (method, path)


def test_full_role_is_the_default_and_unknown_role_fails_closed() -> None:
    assert ApiSecurity.from_values(origins="", token="").role == "full"
    assert _refusal(ApiSecurity(), method="POST", path="/api/research") is None
    with pytest.raises(ValueError, match="LAB_ROLE"):
        ApiSecurity.from_values(origins="", token="", role="papr")


def test_paper_role_still_checks_origin_and_token_first() -> None:
    paper = ApiSecurity.from_values(origins="https://lab.example", token="s3cret", role="paper")
    reason = _refusal(paper, method="GET", path="/api/status", origin="https://evil.example")
    assert reason is not None and "origin" in reason
    assert _refusal(paper, method="GET", path="/api/status") == "missing or invalid API token"
    assert (
        _refusal(paper, method="POST", path="/api/paper/live/stop", presented_token="s3cret")
        is None
    )
