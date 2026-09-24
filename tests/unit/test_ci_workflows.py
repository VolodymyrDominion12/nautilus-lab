"""Invariants of the GitHub workflows (docs/27 E-0.6, E-1.1 to E-1.3).

Workflows are code that runs with a token next to the repository. These are the rules
that a quick edit breaks without anyone noticing: a job that asks for write access, a
checkout that leaves the token in .git/config, a trigger that runs fork code with
secrets, a Python version hard-coded apart from .python-version.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def _load(path: Path) -> dict[Any, Any]:
    yaml = pytest.importorskip("yaml")
    data: dict[Any, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def _steps(workflow: dict[Any, Any]) -> list[dict[str, Any]]:
    return [step for job in workflow["jobs"].values() for step in job.get("steps", [])]


def test_there_are_workflows_to_check() -> None:
    names = {path.name for path in WORKFLOWS}
    assert {"ci.yml", "frontend.yml", "images.yml", "security.yml"} <= names


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_token_is_read_only(path: Path) -> None:
    workflow = _load(path)
    assert workflow.get("permissions") == {"contents": "read"}, "least privilege at the top"
    for name, job in workflow["jobs"].items():
        permissions = job.get("permissions", {})
        assert "write" not in str(permissions), f"{path.name}:{name} asks for write access"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_checkout_does_not_keep_the_token(path: Path) -> None:
    for step in _steps(_load(path)):
        if str(step.get("uses", "")).startswith("actions/checkout@"):
            assert step.get("with", {}).get("persist-credentials") is False, path.name


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_trigger_runs_fork_code_with_secrets(path: Path) -> None:
    workflow = _load(path)
    # YAML 1.1 (PyYAML) reads the key `on` as True.
    triggers: dict[str, Any] = workflow.get("on") or workflow.get(True) or {}
    assert "pull_request_target" not in triggers, path.name
    assert "workflow_run" not in triggers, path.name


def test_ci_python_comes_from_python_version_file() -> None:
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    for step in _steps(_load(ROOT / ".github" / "workflows" / "ci.yml")):
        run = str(step.get("run", ""))
        if "uv python install" in run:
            line = next(item for item in run.splitlines() if "uv python install" in item)
            assert line.strip() == "uv python install", "no version here: .python-version"


def test_frontend_ci_uses_the_node_major_the_image_builds_with() -> None:
    nvmrc = (ROOT / "frontend" / ".nvmrc").read_text(encoding="utf-8").strip()
    dockerfile = (ROOT / "deploy" / "Dockerfile.web").read_text(encoding="utf-8")
    assert f"FROM node:{nvmrc}" in dockerfile
