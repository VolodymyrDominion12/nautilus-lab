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
