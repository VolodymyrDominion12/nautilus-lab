"""CLI coverage for the offline proposal loop and the append-only research journal.

No network: `llm_completer` is replaced with a fake, and the journal is pointed at a
temporary file through the environment.
"""

import json
from pathlib import Path

import pytest

from nautilus_lab.application.journal import ROWS_END, ROWS_START
from nautilus_lab.domain.ports import ChatCompleter
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.interfaces import cli

_HYPOTHESES = json.dumps(
    [
        {
            "name": "volume-climax reversal",
            "formula": "-reversal_3 * zscore(volume_ratio)",
            "mechanism": "the aggressor is spent after a volume spike",
            "horizon_bars": 5,
            "expected_sign": -1,
            "kill_condition": "out-of-sample IC < 0 in two adjacent folds",
        }
    ]
)


class _FakeCompleter:
    def __init__(self, response: str = _HYPOTHESES) -> None:
        self.response = response
        self.calls = 0

    def complete(self, *, system: str, user: str) -> str:
        self.calls += 1
        return self.response


@pytest.fixture
def fake_completer(monkeypatch: pytest.MonkeyPatch) -> _FakeCompleter:
    completer = _FakeCompleter()

    def _factory(
        cfg: Settings, *, model: str | None = None, base_url: str | None = None
    ) -> ChatCompleter:
        return completer

    # The completer is resolved inside `execute_propose`, not in `cli`, so the patch
    # target is that module's namespace. Patching `cli` raised AttributeError.
    monkeypatch.setattr(
        "nautilus_lab.application.run_alpha_proposal.llm_completer",
        _factory,
    )
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    return completer


@pytest.fixture
def journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    markdown = tmp_path / "journal.md"
    markdown.write_text(
        "# Journal\n\n"
        "| Дата | Джерело | Гіпотеза / робот | Ворота | OOS | buy&hold | Рішення | Причина |\n"
        "|------|---------|------------------|--------|-----|----------|---------|---------|\n"
        f"{ROWS_START}\n{ROWS_END}\n",
        encoding="utf-8",
    )
    jsonl = tmp_path / "journal.jsonl"
    monkeypatch.setenv("JOURNAL_PATH", str(markdown))
    monkeypatch.setenv("JOURNAL_JSONL_PATH", str(jsonl))
    monkeypatch.setenv("JOURNAL_ENABLED", "false")
    return markdown, jsonl


def test_propose_dry_run_needs_no_key_and_no_network(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "")
    assert cli.main(["propose", "--dry-run", "--count", "3"]) == 0
    out = capsys.readouterr().out
    assert "trend_er" in out
    assert "Give 3" not in out  # the Ukrainian prompt asks in Ukrainian, not in English
    assert "[dry-run]" in out


def test_propose_fails_closed_without_api_key(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "")
    code = cli.main(["propose", "--output-dir", str(tmp_path / "hypotheses")])
    assert code == 1
    assert "fails closed" in capsys.readouterr().err
    assert not (tmp_path / "hypotheses").exists()


def test_propose_writes_artifact_and_pending_journal_row(
    capsys: pytest.CaptureFixture[str],
    fake_completer: _FakeCompleter,
    journal: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    markdown, jsonl = journal
    output_dir = tmp_path / "hypotheses"
    code = cli.main(
        [
            "propose",
            "--model",
            "fake-model",
            "--as-of",
            "2026-09-15",
            "--output-dir",
            str(output_dir),
            "--slug",
            "test-run",
            "--journal",
        ]
    )
    assert code == 0
    assert fake_completer.calls == 1
    artifact = output_dir / "test-run.json"
    assert artifact.exists()
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["count_parsed"] == 1
    assert payload["review"]["status"] == "pending"

    row = markdown.read_text(encoding="utf-8")
    assert "| lab propose | proposal fake-model |" in row
    assert "⏳ pending" in row
    record = json.loads(jsonl.read_text(encoding="utf-8").strip())
    assert record["source"] == "lab propose"
    assert record["artifact"] == str(artifact)
    assert "artifact=" in capsys.readouterr().out


def test_propose_rejects_a_bad_as_of(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["propose", "--dry-run", "--as-of", "15-09-2026"])
    assert excinfo.value.code == 2


def test_research_journal_appends_row_when_asked(
    journal: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    markdown, jsonl = journal
    assert cli.main(["research", "--synthetic", "--bars", "300", "--journal"]) == 0
    assert "journal_row_appended=" in capsys.readouterr().out
    row = markdown.read_text(encoding="utf-8")
    assert "| lab research | regime ETH/USDT.SIM |" in row
    assert "synthetic backtest (no OOS split)" in row
    # An in-sample return must never land in the OOS column.
    assert "| n/a | n/a |" in row
    assert "IS return" in row
    record = json.loads(jsonl.read_text(encoding="utf-8").strip())
    assert record["subject"] == "regime ETH/USDT.SIM"
    assert record["decision"] == "pending"


def test_research_journal_walk_forward_row_carries_the_oos_number(
    journal: tuple[Path, Path],
) -> None:
    markdown, _ = journal
    code = cli.main(["research", "--synthetic", "--bars", "600", "--walk-forward", "--journal"])
    assert code == 0
    row = markdown.read_text(encoding="utf-8")
    assert "walk-forward synthetic single split" in row
    assert "single split; buy&hold not measured" in row


def test_research_journal_is_off_by_default(journal: tuple[Path, Path]) -> None:
    markdown, jsonl = journal
    assert cli.main(["research", "--synthetic", "--bars", "300"]) == 0
    assert "| lab research |" not in markdown.read_text(encoding="utf-8")
    assert not jsonl.exists()


def test_research_journal_via_env_flag(
    journal: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    markdown, _ = journal
    monkeypatch.setenv("JOURNAL_ENABLED", "true")
    assert cli.main(["research", "--synthetic", "--bars", "300"]) == 0
    assert "| lab research |" in markdown.read_text(encoding="utf-8")


def test_research_journal_fails_closed_without_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "journal.md"
    broken.write_text("# Journal without markers\n", encoding="utf-8")
    monkeypatch.setenv("JOURNAL_PATH", str(broken))
    monkeypatch.setenv("JOURNAL_JSONL_PATH", str(tmp_path / "journal.jsonl"))
    assert cli.main(["research", "--synthetic", "--bars", "300", "--journal"]) == 1
    assert "marker pair" in capsys.readouterr().err
