"""deploy/: least-privilege invariants of the VPS stack (docs/27 E-1.8).

These are the properties that silently erode when a service is added or edited in a
hurry: a new container without the hardening block, a published API port, an extra
capability. Checking the files keeps them from depending on someone remembering.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"

#: The only capabilities a service may add back after `cap_drop: [ALL]`, and why.
ALLOWED_CAPS: dict[str, set[str]] = {
    "web": {"NET_BIND_SERVICE"},  # Caddy binds :80/:443 as root inside its image
    "backup": {"DAC_READ_SEARCH"},  # restic reads the app user's files whatever their mode
}


def _services() -> dict[str, Any]:
    yaml = pytest.importorskip("yaml")
    compose = yaml.safe_load((DEPLOY / "docker-compose.yml").read_text(encoding="utf-8"))
    services: dict[str, Any] = compose["services"]
    return services


def test_every_service_is_hardened() -> None:
    for name, service in _services().items():
        assert service.get("read_only") is True, f"{name}: root filesystem must be read-only"
        assert service.get("cap_drop") == ["ALL"], f"{name}: drop all capabilities"
        assert "no-new-privileges:true" in service.get("security_opt", []), name
        assert service.get("pids_limit"), f"{name}: needs a pids limit"
        assert service.get("mem_limit"), f"{name}: needs a memory limit"
        assert any(t.startswith("/tmp") for t in service.get("tmpfs", [])), f"{name}: /tmp"


def test_capabilities_added_back_are_the_documented_ones() -> None:
    for name, service in _services().items():
        added = set(service.get("cap_add", []))
        assert added <= ALLOWED_CAPS.get(name, set()), f"{name}: unexpected {added}"


def test_only_caddy_publishes_ports_and_only_on_bind_addr() -> None:
    for name, service in _services().items():
        ports = service.get("ports", [])
        if name != "web":
            assert not ports, f"{name} must not publish ports; Caddy is the only door"
            continue
        for port in ports:
            assert port.startswith("${BIND_ADDR:-127.0.0.1}:"), port


def test_dashboard_gets_a_csp_that_starts_in_report_only_mode() -> None:
    caddyfile = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")
    spa = caddyfile[caddyfile.index("handle {") :]
    assert "{$CSP_MODE:Content-Security-Policy-Report-Only}" in spa
    assert "frame-ancestors 'none'" in spa
    api = caddyfile[caddyfile.index("handle @api") : caddyfile.index("handle {")]
    assert "Content-Security-Policy" not in api, "tearsheets under @api have inline scripts"
    assert "Strict-Transport-Security" in caddyfile
