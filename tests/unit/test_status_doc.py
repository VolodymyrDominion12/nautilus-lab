"""`docs/STATUS.md` is current and the specs agree with the code (docs/27 E-2.8)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_status", ROOT / "scripts" / "gen_status.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_status_table_is_up_to_date() -> None:
    generator = _generator()
    assert generator.OUTPUT.read_text(encoding="utf-8") == generator.render(), (
        "docs/STATUS.md is stale: run `uv run python scripts/gen_status.py`"
    )


def test_every_spec_says_what_the_code_does() -> None:
    generator = _generator()
    assert generator.discrepancies(generator.load_specs("strategies")) == []


def test_a_spec_claiming_an_adapter_the_code_lacks_is_reported() -> None:
    generator = _generator()
    specs = generator.load_specs("strategies")
    lying = [
        {**spec, "implementation": {**spec["implementation"], "wired_in_backtest": True}}
        if spec["name"] == "glft"
        else spec
        for spec in specs
    ]
    problems = generator.discrepancies(lying)
    assert len(problems) == 1 and problems[0].startswith("glft:")


def test_a_robot_without_a_spec_is_reported() -> None:
    generator = _generator()
    specs = [s for s in generator.load_specs("strategies") if s["name"] != "ema"]
    assert any(problem.startswith("ema:") for problem in generator.discrepancies(specs))


def test_gate_thresholds_are_read_from_the_code() -> None:
    from nautilus_lab.application.promotion_gate import GateCriteria

    text = _generator().render()
    criteria = GateCriteria()
    assert f"| `min_folds` | {criteria.min_folds} |" in text
    assert f"| `min_oos_fills` | {criteria.min_oos_fills} |" in text
