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


def _sample_record(
    robot: str = "regime",
    offset_days: int = 0,
    *,
    session_id: str | None = None,
    instrument_id: str = "ETHUSDT",
) -> DecisionRecord:
    ts = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC) - timedelta(days=offset_days)
    return DecisionRecord(
        bar_end_utc=ts,
        robot=robot,
        instrument_id=instrument_id,
        close_price=Decimal("2650.50"),
        regime="TREND",
        signal="LONG",
        signal_reason="ER threshold break",
        indicators={"er": "0.45", "trend_ema": "2600.0"},
        states={"effective_regime": "TREND"},
        session_id=session_id,
    )


def _enabled_writer(tmp_path: Path) -> JsonlDecisionLogWriter:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        decision_log_enabled=True,
        decision_log_dir="data/paper/decisions",
    )
    return JsonlDecisionLogWriter(settings, root=tmp_path)


def test_session_keyed_log_is_read_back_by_session_id(tmp_path: Path) -> None:
    """The dashboard asks by session id: the file must be filed under that same key."""
    writer = _enabled_writer(tmp_path)

    writer.log(_sample_record(robot="ema", session_id="ema-eth-159a09"))

    assert (tmp_path / "data/paper/decisions/ema-eth-159a09_2026-09-25.jsonl").is_file()
    logs = writer.get_recent_logs("ema-eth-159a09")
    assert len(logs) == 1
    assert logs[0]["session_id"] == "ema-eth-159a09"
    assert logs[0]["robot"] == "ema"
    # Neither the session name without its suffix (the key the route used to use) nor the
    # robot name is this session's log: an empty answer there is the bug that was fixed.
    assert writer.get_recent_logs("ema-eth") == []
    assert writer.get_recent_logs("ema") == []


def test_two_sessions_of_one_robot_keep_separate_logs(tmp_path: Path) -> None:
    """hold-btc and hold-eth run the same robot; one robot-keyed file mixed their decisions."""
    writer = _enabled_writer(tmp_path)

    writer.log(_sample_record(robot="hold", session_id="hold-btc-5d65f4", instrument_id="BTCUSDT"))
    writer.log(_sample_record(robot="hold", session_id="hold-eth-4d1f08", instrument_id="ETHUSDT"))

    btc = writer.get_recent_logs("hold-btc-5d65f4")
    eth = writer.get_recent_logs("hold-eth-4d1f08")
    assert [row["instrument"] for row in btc] == ["BTCUSDT"]
    assert [row["instrument"] for row in eth] == ["ETHUSDT"]


def test_records_without_a_session_still_fall_back_to_the_robot_name(tmp_path: Path) -> None:
    """Backtests and the CLI write session-less records, as the pre-fix files did."""
    writer = _enabled_writer(tmp_path)

    writer.log(_sample_record(robot="regime"))

    assert (tmp_path / "data/paper/decisions/regime_2026-09-25.jsonl").is_file()
    assert len(writer.get_recent_logs("regime")) == 1


def test_session_id_is_sanitised_before_it_becomes_a_file_name(tmp_path: Path) -> None:
    """The session name comes from an API caller: it must not choose the path."""
    writer = _enabled_writer(tmp_path)

    writer.log(_sample_record(robot="ema", session_id="../../etc/passwd"))

    log_dir = tmp_path / "data/paper/decisions"
    assert sorted(p.name for p in log_dir.glob("*.jsonl")) == ["etc_passwd_2026-09-25.jsonl"]
    assert not (tmp_path / "etc").exists()
    assert len(writer.get_recent_logs("../../etc/passwd")) == 1


def test_decision_log_writer_disabled(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
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
    settings = Settings(  # type: ignore[call-arg]
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
    settings = Settings(  # type: ignore[call-arg]
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
    settings = Settings(  # type: ignore[call-arg]
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

    # Session-keyed names age the same way (the date is still the last `_`-separated part).
    old_session_file = log_dir / f"ema-eth-159a09_{old_date}.jsonl"
    old_session_file.write_text('{"test": 3}\n', encoding="utf-8")
    recent_session_file = log_dir / f"ema-eth-159a09_{recent_date}.jsonl"
    recent_session_file.write_text('{"test": 4}\n', encoding="utf-8")

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        decision_log_enabled=True,
        decision_log_dir="data/paper/decisions",
        decision_log_retention_days=7,
    )
    _ = JsonlDecisionLogWriter(settings, root=tmp_path)

    assert not old_file.exists(), "Old log file should have been pruned"
    assert recent_file.exists(), "Recent log file should be retained"
    assert not old_session_file.exists(), "Old session-keyed log should have been pruned"
    assert recent_session_file.exists(), "Recent session-keyed log should be retained"


def test_null_decision_log_writer() -> None:
    writer = NullDecisionLogWriter()
    record = _sample_record()
    writer.log(record)
    writer.append(record)
