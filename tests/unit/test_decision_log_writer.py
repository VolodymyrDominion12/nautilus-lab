from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from nautilus_lab.domain.decision_log import DecisionRecord
from nautilus_lab.infrastructure.decision_log_writer import (
    JsonlDecisionLogWriter,
    NullDecisionLogWriter,
)
from nautilus_lab.infrastructure.settings import Settings


def _sample_record(robot: str = "regime", offset_days: int = 0) -> DecisionRecord:
    ts = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC) - timedelta(days=offset_days)
    return DecisionRecord(
        bar_end_utc=ts,
        robot=robot,
        instrument_id="ETHUSDT",
        close_price=Decimal("2650.50"),
        regime="TREND",
        signal="LONG",
        signal_reason="ER threshold break",
        indicators={"er": "0.45", "trend_ema": "2600.0"},
        states={"effective_regime": "TREND"},
    )


def test_decision_log_writer_disabled(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        decision_log_enabled=False,
        decision_log_dir="data/paper/decisions",
    )
    writer = JsonlDecisionLogWriter(settings, root=tmp_path)
    assert not (tmp_path / "data/paper/decisions").exists()

    record = _sample_record()
    writer.log(record)
    assert writer.get_recent_logs("regime") == []


def test_decision_log_writer_writes_and_reads(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        decision_log_enabled=True,
        decision_log_dir="data/paper/decisions",
    )
    writer = JsonlDecisionLogWriter(settings, root=tmp_path)
    assert (tmp_path / "data/paper/decisions").is_dir()

    record = _sample_record(robot="regime")
    writer.log(record)

    logs = writer.get_recent_logs("regime")
    assert len(logs) == 1
    assert logs[0]["robot"] == "regime"
    assert logs[0]["instrument"] == "ETHUSDT"
    assert logs[0]["close"] == "2650.50"
    assert logs[0]["signal"] == "LONG"
    assert logs[0]["indicators"]["er"] == "0.45"

    # Also test append alias
    writer.append(record)
    logs_after = writer.get_recent_logs("regime")
    assert len(logs_after) == 2


def test_decision_log_writer_fallback_on_oserror(tmp_path: Path) -> None:
    """When configured directory fails with OSError (e.g. read-only filesystem),

    it must fall back to data/paper/decisions without crashing.
    """
    settings = Settings(
        _env_file=None,
        decision_log_enabled=True,
        decision_log_dir="logs/decisions",
    )

    original_mkdir = Path.mkdir

    def mock_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        if "logs" in str(self):
            raise OSError(30, "Read-only file system", str(self))
        original_mkdir(self, *args, **kwargs)  # type: ignore[arg-type]

    with patch.object(Path, "mkdir", side_effect=mock_mkdir, autospec=True):
        writer = JsonlDecisionLogWriter(settings, root=tmp_path)

    # Directory fell back to data/paper/decisions
    assert writer._dir == tmp_path / "data/paper/decisions"
    assert writer._enabled is True

    record = _sample_record(robot="ema")
    writer.log(record)
    logs = writer.get_recent_logs("ema")
    assert len(logs) == 1
    assert logs[0]["robot"] == "ema"


def test_decision_log_writer_disables_gracefully_when_all_fail(tmp_path: Path) -> None:
    """When both configured dir and fallback fail, disable logging rather than crashing."""
    settings = Settings(
        _env_file=None,
        decision_log_enabled=True,
        decision_log_dir="logs/decisions",
    )

    def fail_all_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        raise OSError(30, "Read-only file system", str(self))

    with patch.object(Path, "mkdir", side_effect=fail_all_mkdir, autospec=True):
        writer = JsonlDecisionLogWriter(settings, root=tmp_path)

    assert writer._enabled is False
    record = _sample_record()
    writer.log(record)
    assert writer.get_recent_logs("regime") == []


def test_decision_log_writer_pruning(tmp_path: Path) -> None:
    log_dir = tmp_path / "data/paper/decisions"
    log_dir.mkdir(parents=True)

    # Create old log file (10 days old)
    old_date = (datetime.now(UTC) - timedelta(days=10)).strftime("%Y-%m-%d")
    old_file = log_dir / f"regime_{old_date}.jsonl"
    old_file.write_text('{"test": 1}\n', encoding="utf-8")

    # Create recent log file (1 day old)
    recent_date = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    recent_file = log_dir / f"regime_{recent_date}.jsonl"
    recent_file.write_text('{"test": 2}\n', encoding="utf-8")

    settings = Settings(
        _env_file=None,
        decision_log_enabled=True,
        decision_log_dir="data/paper/decisions",
        decision_log_retention_days=7,
    )
    _ = JsonlDecisionLogWriter(settings, root=tmp_path)

    assert not old_file.exists(), "Old log file should have been pruned"
    assert recent_file.exists(), "Recent log file should be retained"


def test_null_decision_log_writer() -> None:
    writer = NullDecisionLogWriter()
    record = _sample_record()
    writer.log(record)
    writer.append(record)
