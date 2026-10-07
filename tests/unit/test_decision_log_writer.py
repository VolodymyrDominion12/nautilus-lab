from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from nautilus_lab.domain.decision_log import DecisionRecord
from nautilus_lab.infrastructure.decision_log_writer import (
    JsonlDecisionLogWriter,
    NullDecisionLogWriter,
    prune_decision_logs,
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


def test_get_recent_logs_filters_by_regime_and_signal(tmp_path: Path) -> None:
    """`regime` and `signal` narrow bar decisions, case-insensitively; no-match stays empty."""
    writer = _enabled_writer(tmp_path)
    base = _sample_record(session_id="regime-eth-159a09")
    t0 = base.bar_end_utc
    writer.log(replace(base, bar_end_utc=t0, regime="uptrend", signal="buy"))
    writer.log(
        replace(base, bar_end_utc=t0 + timedelta(minutes=1), regime="downtrend", signal="sell")
    )
    writer.log(replace(base, bar_end_utc=t0 + timedelta(minutes=2), regime="range", signal=None))

    assert [r["regime"] for r in writer.get_recent_logs("regime-eth-159a09", regime="uptrend")] == [
        "uptrend"
    ]
    assert [r["signal"] for r in writer.get_recent_logs("regime-eth-159a09", signal="sell")] == [
        "sell"
    ]
    assert writer.get_recent_logs("regime-eth-159a09", regime="uptrend", signal="sell") == []
    assert [r["regime"] for r in writer.get_recent_logs("regime-eth-159a09", signal="buy")] == [
        "uptrend"
    ]
    # A signal filter drops rows that carried no signal (the range row above).
    assert writer.get_recent_logs("regime-eth-159a09", signal="flat") == []


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


def _write_log(path: Path, *, age_days: float) -> Path:
    """A log file written `age_days` ago: the age the retention policy must read."""
    path.write_text('{"test": 1}\n', encoding="utf-8")
    stamp = (datetime.now(UTC) - timedelta(days=age_days)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def test_decision_log_writer_pruning(tmp_path: Path) -> None:
    log_dir = tmp_path / "data/paper/decisions"
    log_dir.mkdir(parents=True)

    # Written 10 days ago and 1 day ago; both names carry their own bar dates, which are
    # not the ages: the sweep must go by the write time.
    old_file = _write_log(log_dir / "regime_2024-01-01.jsonl", age_days=10)
    recent_file = _write_log(log_dir / "regime_2024-01-02.jsonl", age_days=1)
    old_session_file = _write_log(log_dir / "ema-eth-159a09_2024-01-01.jsonl", age_days=10)
    recent_session_file = _write_log(log_dir / "ema-eth-159a09_2024-01-02.jsonl", age_days=1)

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        decision_log_enabled=True,
        decision_log_dir="data/paper/decisions",
        decision_log_retention_days=7,
    )
    _ = JsonlDecisionLogWriter(settings, root=tmp_path)

    assert not old_file.exists(), "A log written 10 days ago should have been pruned"
    assert not old_session_file.exists(), "A session-keyed log ages the same way"
    assert recent_file.exists(), "A log written yesterday should be retained"
    assert recent_session_file.exists(), "A recent session-keyed log should be retained"


def test_decision_log_writer_keeps_a_backtest_log_whose_bar_dates_are_history(
    tmp_path: Path,
) -> None:
    """A research run over 2024 data writes `2024-…` names **today**: keep them.

    On 2026-09-28 the sweep aged files by the date in the name, so an API restart deleted
    ~62 MB of one backtest's decisions (bar dates 2024-01-01…2026-09-19) and the dashboard's
    Backtest Details lost everything but the last three simulated days.
    """
    log_dir = tmp_path / "data/paper/decisions"
    log_dir.mkdir(parents=True)
    backtest_files = [
        _write_log(log_dir / f"0d83e156-0000-0000-0000-000000000000_{date}.jsonl", age_days=0)
        for date in ("2024-01-01", "2025-06-15", "2026-09-19")
    ]

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        decision_log_enabled=True,
        decision_log_dir="data/paper/decisions",
        decision_log_retention_days=7,
    )
    writer = JsonlDecisionLogWriter(settings, root=tmp_path)

    assert all(path.exists() for path in backtest_files), "fresh logs, however old their bars"
    assert len(writer.get_recent_logs("0d83e156-0000-0000-0000-000000000000")) == 3


def test_decision_log_writer_keeps_everything_when_retention_is_off(tmp_path: Path) -> None:
    log_dir = tmp_path / "data/paper/decisions"
    log_dir.mkdir(parents=True)
    ancient = _write_log(log_dir / "regime_2020-01-01.jsonl", age_days=400)

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        decision_log_enabled=True,
        decision_log_dir="data/paper/decisions",
        decision_log_retention_days=0,
    )
    _ = JsonlDecisionLogWriter(settings, root=tmp_path)

    assert ancient.exists(), "retention 0 means keep the logs"


def test_null_decision_log_writer() -> None:
    writer = NullDecisionLogWriter()
    record = _sample_record()
    writer.log(record)
    writer.append(record)
    assert writer.prune() == (0, 0)


def test_decision_log_writer_size_quota_pruning(tmp_path: Path) -> None:
    """When directory exceeds max_mb quota, oldest files are pruned (LRU)."""
    log_dir = tmp_path / "data/paper/decisions"
    log_dir.mkdir(parents=True)

    # Create 3 files of 1 MB each with different write timestamps
    data_1mb = "x" * (1024 * 1024)
    file_old = log_dir / "session_2026-10-01.jsonl"
    file_mid = log_dir / "session_2026-10-02.jsonl"
    file_new = log_dir / "session_2026-10-03.jsonl"

    file_old.write_text(data_1mb, encoding="utf-8")
    file_mid.write_text(data_1mb, encoding="utf-8")
    file_new.write_text(data_1mb, encoding="utf-8")

    now = datetime.now(UTC).timestamp()
    os.utime(file_old, (now - 300, now - 300))
    os.utime(file_mid, (now - 200, now - 200))
    os.utime(file_new, (now - 100, now - 100))

    # Quota is 2 MB: total is 3 MB, so the oldest file must be pruned
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        decision_log_enabled=True,
        decision_log_dir="data/paper/decisions",
        decision_log_retention_days=30,  # all files within retention days
        decision_log_max_mb=2,
    )
    _ = JsonlDecisionLogWriter(settings, root=tmp_path)

    assert not file_old.exists(), "Oldest file should be pruned to satisfy 2 MB quota"
    assert file_mid.exists(), "Newer files should be retained"
    assert file_new.exists(), "Newer files should be retained"


def test_decision_log_writer_periodic_prune_in_log(tmp_path: Path) -> None:
    """log() triggers retention sweep if prune_interval_seconds has elapsed."""
    log_dir = tmp_path / "data/paper/decisions"
    log_dir.mkdir(parents=True)

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        decision_log_enabled=True,
        decision_log_dir="data/paper/decisions",
        decision_log_retention_days=7,
        decision_log_prune_interval_seconds=10,
    )
    writer = JsonlDecisionLogWriter(settings, root=tmp_path)

    # Plant an old file after startup
    old_file = _write_log(log_dir / "old_session_2024-01-01.jsonl", age_days=10)
    assert old_file.exists()

    record = _sample_record(robot="ema")
    # Calling log() before interval should not prune yet
    writer.log(record)
    assert old_file.exists()

    # Advance time past prune_interval_seconds
    writer._last_prune_time -= 20
    writer.log(record)
    assert not old_file.exists(), "log() should have triggered periodic pruning"


def test_prune_decision_logs_dry_run(tmp_path: Path) -> None:
    """dry_run=True computes pruned count and bytes without deleting files."""
    log_dir = tmp_path / "decisions"
    log_dir.mkdir(parents=True)

    old_file = _write_log(log_dir / "old_2024-01-01.jsonl", age_days=10)
    pruned_files, pruned_bytes = prune_decision_logs(log_dir, retention_days=7, dry_run=True)

    assert pruned_files == 1
    assert pruned_bytes > 0
    assert old_file.exists(), "dry_run must not delete the file"
