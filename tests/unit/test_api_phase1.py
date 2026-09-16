from __future__ import annotations

from pathlib import Path

import pytest

from nautilus_lab.api.experiment_history import list_history
from nautilus_lab.api.research_runner import ResearchJobConfig, _optional_window
from nautilus_lab.api.settings_coerce import apply_setting_overrides
from nautilus_lab.infrastructure.settings import Settings


def test_apply_setting_overrides_changes_robot() -> None:
    cfg = Settings()
    updated = apply_setting_overrides(cfg, {"ROBOT": "ema", "FAST_EMA": "12"})
    assert updated.robot.value == "ema"
    assert updated.fast_ema == 12


def test_optional_window_requires_all_dates() -> None:
    job = ResearchJobConfig(is_start="2024-01-01", is_end="2024-06-01")
    with pytest.raises(ValueError, match="is_start"):
        _optional_window(job)


def test_list_history_empty(tmp_path: Path) -> None:
    assert list_history(tmp_path, limit=5) == []
