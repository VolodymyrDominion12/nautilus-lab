"""Run provenance (docs/27 E-1.4): code, dependencies, settings and data of every run."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from nautilus_lab.api.live_paper_boot import boot_live_paper
from nautilus_lab.api.paper_streamer import LivePaperConfig, LivePaperSessionManager
from nautilus_lab.application.journal import JournalEntry, append_record, load_records
from nautilus_lab.domain.provenance import RunManifest
from nautilus_lab.infrastructure.live_paper_journal import LivePaperJournal
from nautilus_lab.infrastructure.provenance import (
    REVISION_ENV,
    REVISION_FILE,
    catalog_fingerprint,
    code_revision,
    collect_manifest,
    settings_sha256,
)

GIT = shutil.which("git")
T0 = datetime(2026, 9, 24, 10, tzinfo=UTC)


def _load_report_script() -> ModuleType:
    """scripts/ is not a package; load the report the way `uv run python scripts/...` does."""
    path = Path(__file__).resolve().parents[2] / "scripts" / "live_paper_report.py"
    spec = importlib.util.spec_from_file_location("live_paper_report", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before running: its dataclasses resolve string annotations through it.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


live_paper_report = _load_report_script()


def _git(repo: Path, *args: str) -> None:
    assert GIT is not None
    subprocess.run(
        [GIT, "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    if GIT is None:
        pytest.skip("needs git")
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "uv.lock").write_text("lock v1\n", encoding="utf-8")
    (root / "code.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    return root


# ------------------------------------------------------------------ the value


def test_manifest_round_trips_through_json() -> None:
    manifest = RunManifest(
        code_revision="a" * 40,
        code_dirty=False,
        revision_source="git",
        lock_sha256="b" * 64,
        python_version="3.12.9",
        nautilus_version="1.231.0",
        settings_sha256="c" * 64,
        catalog_fingerprint="d" * 64,
        catalog_files=12,
    )
    raw = json.loads(json.dumps(manifest.as_dict()))
    assert RunManifest.from_dict(raw) == manifest
    assert manifest.reproducible
    assert manifest.warnings() == ()


def test_summary_line_marks_a_dirty_tree_and_unknowns() -> None:
    line = RunManifest(code_revision="0123456789abcdef", code_dirty=True).summary_line()
    assert "rev=0123456789ab+dirty" in line
    assert "lock=unknown" in line
    assert "catalog=" not in line, "no catalog was read, so none is claimed"


@pytest.mark.parametrize(
    ("manifest", "reason"),
    [
        (RunManifest(code_dirty=None, lock_sha256="x"), "revision unknown"),
        (RunManifest(code_revision="abc", code_dirty=True, lock_sha256="x"), "uncommitted"),
        (RunManifest(code_revision="abc", code_dirty=False), "uv.lock"),
    ],
)
def test_warnings_say_why_a_run_is_not_reproducible(manifest: RunManifest, reason: str) -> None:
    assert not manifest.reproducible or reason == "uv.lock"
    assert any(reason in item for item in manifest.warnings())


@pytest.mark.parametrize(
    "payload",
    [{"code_dirty": "no"}, {"catalog_files": "12"}, {"catalog_files": True}, {"lock_sha256": 1}],
)
def test_from_dict_rejects_wrong_types(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="must be"):
        RunManifest.from_dict(payload)


# ------------------------------------------------------------- the collector


def test_clean_checkout_is_reproducible(repo: Path) -> None:
    manifest = collect_manifest(repo_root=repo, environ={})
    assert manifest.revision_source == "git"
    assert manifest.code_revision is not None
    assert len(manifest.code_revision) == 40
    assert manifest.code_dirty is False
    assert manifest.reproducible
    assert manifest.lock_sha256 is not None


def test_uncommitted_edit_makes_the_tree_dirty(repo: Path) -> None:
    (repo / "code.py").write_text("x = 2\n", encoding="utf-8")
    manifest = collect_manifest(repo_root=repo, environ={})
    assert manifest.code_dirty is True
    assert not manifest.reproducible


def test_untracked_files_do_not_make_the_tree_dirty(repo: Path) -> None:
    # reports/, data/ and notebooks appear next to the code all the time; they are not code.
    (repo / "scratch.txt").write_text("notes\n", encoding="utf-8")
    assert collect_manifest(repo_root=repo, environ={}).code_dirty is False


def test_without_git_the_revision_comes_from_the_image_then_the_marker(tmp_path: Path) -> None:
    assert code_revision(tmp_path, {REVISION_ENV: "feed" * 10}) == ("feed" * 10, False, "env")
    (tmp_path / REVISION_FILE).write_text("abc1234\n", encoding="utf-8")
    assert code_revision(tmp_path, {}) == ("abc1234", False, "file")


def test_nothing_known_is_recorded_as_unknown_not_as_an_error(tmp_path: Path) -> None:
    manifest = collect_manifest(repo_root=tmp_path, environ={})
    assert manifest.code_revision is None
    assert manifest.code_dirty is None
    assert manifest.lock_sha256 is None
    assert manifest.python_version  # always known


def test_settings_hash_is_order_free_and_ignores_secrets() -> None:
    base = {"maker_fee": "0.001", "taker_fee": "0.001", "robot": "regime"}
    assert settings_sha256(base) == settings_sha256(dict(reversed(list(base.items()))))
    with_secrets = {**base, "llm_api_key": "sk-1", "api_token": "t", "telegram_chat_id": "1"}
    assert settings_sha256(with_secrets) == settings_sha256(base)
    # A shell override of a fee is exactly what this hash exists to expose.
    assert settings_sha256({**base, "taker_fee": "0.0005"}) != settings_sha256(base)


def test_catalog_fingerprint_follows_the_data_not_the_copy(tmp_path: Path) -> None:
    first = tmp_path / "a" / "catalog"
    (first / "data" / "bar").mkdir(parents=True)
    (first / "data" / "bar" / "part-0.parquet").write_bytes(b"0" * 100)
    second = tmp_path / "b" / "catalog"
    shutil.copytree(first, second)  # new mtimes, same data
    fingerprint, files = catalog_fingerprint([first])
    assert files == 1
    assert catalog_fingerprint([second]) == (fingerprint, 1)

    (first / "data" / "bar" / "part-1.parquet").write_bytes(b"1" * 50)  # an ingest
    assert catalog_fingerprint([first])[0] != fingerprint


def test_missing_catalog_is_unknown(tmp_path: Path) -> None:
    assert catalog_fingerprint([tmp_path / "absent"]) == (None, None)


# ------------------------------------------------------ where it is recorded


def test_journal_record_carries_provenance_and_old_records_still_load(tmp_path: Path) -> None:
    jsonl = tmp_path / "journal.jsonl"
    old = JournalEntry(created_at=T0, source="lab research", subject="regime", gates="walk-forward")
    payload = old.as_dict()
    del payload["provenance"]  # a line written before E-1.4
    jsonl.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    manifest = RunManifest(code_revision="abc", code_dirty=False, settings_sha256="s")
    append_record(jsonl, replace(old, provenance=manifest))

    records = load_records(jsonl)
    assert records[0].provenance is None
    assert records[1].provenance == manifest


def _paper_config() -> LivePaperConfig:
    return LivePaperConfig(symbol="ETHUSDT", interval="1h", starting_equity=Decimal("10000"))


def _paper_manager(journal: LivePaperJournal) -> LivePaperSessionManager:
    manager = LivePaperSessionManager(journal=journal)
    manager._launch_stream = lambda: None  # type: ignore[method-assign]
    return manager


def test_paper_session_records_its_code_at_start_and_after_resume(tmp_path: Path) -> None:
    path = tmp_path / "live.jsonl"
    asyncio.run(_paper_manager(LivePaperJournal(path)).start(_paper_config()))
    # The process dies (deploy); a new one resumes the session.
    second = _paper_manager(LivePaperJournal(path))
    assert asyncio.run(boot_live_paper(second, autostart=None)) == "resumed"

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    kinds = [record["type"] for record in records]
    assert kinds[0] == "session_start"
    assert "session_resume" in kinds
    for record in records:
        if record["type"] in {"session_start", "session_resume"}:
            RunManifest.from_dict(record["provenance"])  # well-formed, whatever the host


def test_resume_record_does_not_disturb_what_is_resumed(tmp_path: Path) -> None:
    path = tmp_path / "live.jsonl"
    first = _paper_manager(LivePaperJournal(path))
    asyncio.run(first.start(_paper_config()))
    asyncio.run(boot_live_paper(_paper_manager(LivePaperJournal(path)), autostart=None))
    resumable = LivePaperJournal(path).load_resumable()
    assert resumable is not None
    assert resumable.session_id == first.session_id


def test_report_shows_a_code_change_inside_one_session() -> None:
    revisions = [
        live_paper_report.revision_label({"code_revision": "a" * 40, "code_dirty": False}),
        live_paper_report.revision_label({"code_revision": "a" * 40, "code_dirty": False}),
        live_paper_report.revision_label({"code_revision": "b" * 40, "code_dirty": True}),
    ]
    line = live_paper_report.code_line(revisions)
    assert line == f"  code={'a' * 12} -> {'b' * 12}+dirty  (code changed during the session)"
    assert live_paper_report.revision_label(None) == "unknown"
    assert "changed" not in live_paper_report.code_line(["x", "x"])


def test_report_reads_revisions_from_a_journal(tmp_path: Path) -> None:
    path = tmp_path / "live.jsonl"
    journal = LivePaperJournal(path)
    journal.append("session_start", "s1", {"config": {}, "provenance": {"code_revision": "a1"}})
    journal.append("session_resume", "s1", {"provenance": {"code_revision": "b2"}})
    (summary,) = live_paper_report.collect(journal)
    assert summary.revisions == ["a1", "b2"]
