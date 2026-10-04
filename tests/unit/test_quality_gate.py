from __future__ import annotations

import json
from pathlib import Path

import pytest

from nautilus_lab.domain.errors import DataQualityError
from nautilus_lab.infrastructure.quality_gate import QualityGate, quality_status, worst_status

BAR = "SOL/USDT.SIM-1-DAY-LAST-EXTERNAL"


def _write(root: Path, payload: object) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "quality.json").write_text(json.dumps(payload), encoding="utf-8")


def test_no_report_is_unknown_and_allowed(tmp_path: Path) -> None:
    assert quality_status(tmp_path, BAR) == "unknown"
    assert QualityGate(tmp_path)(BAR) == "unknown"


def test_ok_and_warn_pass(tmp_path: Path) -> None:
    _write(tmp_path, {BAR: {"status": "warn"}, "other": {"status": "ok"}})
    assert QualityGate(tmp_path)(BAR) == "warn"
    assert QualityGate(tmp_path)("other") == "ok"


def test_fail_is_refused_unless_explicitly_allowed(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {BAR: {"status": "fail", "missing_bars": 40, "relisting_suspects": [{"ts": "x"}]}},
    )
    with pytest.raises(DataQualityError, match="missing bars 40"):
        QualityGate(tmp_path)(BAR)
    assert QualityGate(tmp_path, allow_failed=True)(BAR) == "fail"


def test_a_broken_report_file_is_unknown_not_a_crash(tmp_path: Path) -> None:
    (tmp_path / "quality.json").write_text("{not json", encoding="utf-8")
    assert quality_status(tmp_path, BAR) == "unknown"
    _write(tmp_path, {BAR: {"status": "weird"}})
    assert quality_status(tmp_path, BAR) == "unknown"


def test_worst_status_orders_fail_over_warn_over_unknown_over_ok() -> None:
    assert worst_status(["ok", "warn", "unknown"]) == "warn"
    assert worst_status(["ok", "fail"]) == "fail"
    assert worst_status(["ok", "unknown"]) == "unknown"
    assert worst_status([]) == "unknown"
