"""Golden backtests (docs/27 E-2.6): same code + same data -> the same numbers.

Fails when any fill count, fee, balance, drawdown or walk-forward return of the fixed
synthetic runs in `scripts/golden_backtest.py` moves. That is the point: an engine or
library upgrade (Renovate PR) must show its effect here before it is merged. When the
change is intended, `uv run python scripts/golden_backtest.py --update` and commit the
snapshot with the reason.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytest.importorskip("nautilus_trader")

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "golden_backtest.py"


def _golden() -> ModuleType:
    spec = importlib.util.spec_from_file_location("golden_backtest", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


golden = _golden()


def test_settings_ignore_env_file_and_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TAKER_FEE", "0.5")
    monkeypatch.setenv("ROBOT", "ema")
    cfg = golden.hermetic_settings(tmp_path)
    defaults = golden.Settings.model_fields
    assert cfg.taker_fee == defaults["taker_fee"].default
    assert cfg.robot == defaults["robot"].default
    assert cfg.catalog_path == str(tmp_path)


def test_differences_name_every_moved_value() -> None:
    old = {"nautilus_trader": "1.0", "cases": {"regime": {"fills": 10, "fees_paid": "1.5"}}}
    new = {"nautilus_trader": "1.1", "cases": {"regime": {"fills": 12, "fees_paid": "1.5"}}}
    assert golden.differences(old, new) == [
        "engine: nautilus_trader 1.0 -> 1.1",
        "regime.fills: 10 -> 12",
    ]
    assert golden.differences(old, old) == []


@pytest.mark.integration
def test_golden_backtests_are_unchanged() -> None:
    expected = golden.load_snapshot()
    if expected is None:
        pytest.fail(
            f"no golden snapshot at {golden.SNAPSHOT}: run "
            "`uv run python scripts/golden_backtest.py --update` and commit it"
        )
    changed = golden.differences(expected, golden.run_all())
    assert not changed, (
        "golden backtests changed (review, then --update and commit with the reason):\n  "
        + "\n  ".join(changed)
    )
