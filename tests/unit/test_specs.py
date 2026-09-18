"""Spec-Driven Development: checks that specs have not drifted from the code.

The point is not to validate YAML. It is to catch the case where a spec and the
implementation disagree — a spec that has drifted is worse than no spec at all,
because it lies with confidence. That is exactly how docs/05 came to claim three
robots were wired into the engine while the code had five.

The checks themselves live in specs/_validator.py so the CLI and these tests
cannot diverge from each other. This module is the pytest wrapper: one test per
spec, plus the coverage rule.

    uv run pytest tests/unit/test_specs.py -v
    uv run pytest tests/unit/test_specs.py -k regime -v
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SPECS_DIR = PROJECT_ROOT / "specs"


def _load_validator() -> ModuleType:
    """Load specs/_validator.py by path (the leading underscore blocks import)."""
    file_spec = importlib.util.spec_from_file_location(
        "_spec_validator", SPECS_DIR / "_validator.py"
    )
    if file_spec is None or file_spec.loader is None:
        raise RuntimeError("cannot load specs/_validator.py")
    module = importlib.util.module_from_spec(file_spec)
    sys.modules["_spec_validator"] = module
    file_spec.loader.exec_module(module)
    return module


validator = _load_validator()
SCHEMA: dict[str, Any] = yaml.safe_load((SPECS_DIR / "_schema.yaml").read_text(encoding="utf-8"))
FACTS = validator.collect_facts()


def _collect_specs() -> list[tuple[str, str, dict[str, Any]]]:
    """Every spec on disk as (kind, name, data)."""
    found: list[tuple[str, str, dict[str, Any]]] = []
    for kind in ("strategy", "component"):
        directory = SPECS_DIR / SCHEMA[kind]["dir"]
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            if path.stem.startswith("_"):
                continue
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                found.append((kind, path.stem, data))
    return found


ALL_SPECS = _collect_specs()
SPEC_IDS = [f"{kind}/{name}" for kind, name, _ in ALL_SPECS]


def test_validator_parses_project_code() -> None:
    """Fail loudly when the validator can no longer read the code.

    The most important test here: every other check is meaningless if the facts
    were not read. If ``minimum_bars()`` is rewritten in a shape the validator
    cannot parse, it would otherwise report every spec as valid without checking
    anything.
    """
    assert not FACTS.problems, (
        "validator could not read the code, so nothing below is actually checked:\n  "
        + "\n  ".join(FACTS.problems)
    )
    assert FACTS.robot_names, "no RobotName values found"
    assert FACTS.wired, "BACKTEST_WIRED_ROBOTS not found"
    assert FACTS.minimum_bars, "minimum_bars() not parsed"
    assert FACTS.setting_fields, "Settings fields not found"


def test_every_robot_has_a_spec() -> None:
    """Adding a robot to RobotName requires adding its spec.

    This test is meant to fail when a strategy is introduced without a
    specification. It is "spec before code", enforced by a machine.
    """
    covered = {name for kind, name, _ in ALL_SPECS if kind == "strategy"}
    missing = sorted(FACTS.robot_names - covered)
    assert not missing, (
        f"robots without a spec: {', '.join(missing)}.\n"
        "Create specs/strategies/<name>.yaml — see specs/strategies/regime.yaml"
    )


@pytest.mark.parametrize(("kind", "name", "spec"), ALL_SPECS, ids=SPEC_IDS)
def test_spec_is_valid_and_matches_code(kind: str, name: str, spec: dict[str, Any]) -> None:
    """The spec is well-formed and agrees with the code (same checks as the CLI)."""
    report = validator.Report()
    validator.check_common(spec, name, report, SCHEMA)
    if kind == "strategy":
        validator.check_strategy(spec, name, report, SCHEMA, FACTS)
    else:
        validator.check_component(spec, name, report, SCHEMA, FACTS)
    assert spec.get("kind") == kind, f"kind={spec.get('kind')!r} does not match dir {kind!r}"
    assert not report.errors, "\n".join(f"  • {e}" for e in report.errors)


def test_component_invariants_reference_real_tests() -> None:
    """Every verified_by must point at a test that actually exists.

    This is the value component specs exist for: an invariant without a test is a
    claim, not a guarantee. A missing test is allowed, but only explicitly via
    test_missing_reason, which the validator surfaces as a warning.
    """
    broken: list[str] = []
    for kind, name, spec in ALL_SPECS:
        if kind != "component":
            continue
        for item in spec.get("invariants_enforced") or []:
            verified = item.get("verified_by")
            if not verified:
                continue
            path_part, _, func_part = verified.partition("::")
            test_path = PROJECT_ROOT / path_part
            if not test_path.is_file():
                broken.append(f"{name}: test file missing — {path_part}")
                continue
            if func_part and func_part.split("[")[0] not in validator._test_nodes(test_path):
                broken.append(f"{name}: {path_part} has no test {func_part!r}")
    assert not broken, "\n".join(f"  • {b}" for b in broken)


@pytest.mark.parametrize(("kind", "name", "spec"), ALL_SPECS, ids=SPEC_IDS)
def test_spec_declares_known_status(kind: str, name: str, spec: dict[str, Any]) -> None:
    """status must come from the schema, or its per-status checks never apply."""
    allowed = SCHEMA[kind]["statuses"]
    assert spec.get("status") in allowed, f"status={spec.get('status')!r} not in {sorted(allowed)}"


def test_docs_agree_with_backtest_wired_robots() -> None:
    """docs/05-roboty.md table must agree with BACKTEST_WIRED_ROBOTS and RobotName (Sprint S6)."""
    errors = validator.check_docs_alignment(FACTS)
    assert not errors, "\n".join(f"  • {e}" for e in errors)
