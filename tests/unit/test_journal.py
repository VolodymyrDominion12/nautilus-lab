import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from nautilus_lab.application.journal import (
    PENDING,
    ROWS_END,
    ROWS_START,
    JournalEntry,
    append_record,
    append_row,
    load_records,
    record_run,
)
from nautilus_lab.domain.errors import JournalFormatError

_NOW = datetime(2026, 9, 15, 10, 30, tzinfo=UTC)


def _journal(tmp_path: Path, *, body: str = "") -> Path:
    path = tmp_path / "journal.md"
    path.write_text(
        "# Journal\n\n"
        "| Дата | Джерело | Гіпотеза / робот | Ворота | OOS | buy&hold | Рішення | Причина |\n"
        "|------|---------|------------------|--------|-----|----------|---------|---------|\n"
        f"{ROWS_START}\n{body}{ROWS_END}\n\nEnd.\n",
        encoding="utf-8",
    )
    return path


def _entry(
    *,
    created_at: datetime = _NOW,
    source: str = "lab research",
    subject: str = "regime ETH/USDT.SIM",
    gates: str = "walk-forward catalog folds=4",
    decision: str = PENDING,
    reason: str = "auto: profitable 1/4 folds",
    oos_return: Decimal | None = Decimal("-0.007"),
    buy_and_hold_return: Decimal | None = Decimal("0.0244"),
    fills: int | None = 356,
    artifact: str | None = None,
) -> JournalEntry:
    return JournalEntry(
        created_at=created_at,
        source=source,
        subject=subject,
        gates=gates,
        decision=decision,
        reason=reason,
        oos_return=oos_return,
        buy_and_hold_return=buy_and_hold_return,
        fills=fills,
        artifact=artifact,
    )


def test_markdown_row_carries_numbers_not_impressions() -> None:
    row = _entry().markdown_row()
    assert row.startswith("| 2026-09-15 10:30 | lab research | regime ETH/USDT.SIM |")
    assert "| -0.70% | 2.44% |" in row
    assert PENDING in row
    assert row.endswith("|")
    assert row.count("|") == 9


def test_markdown_row_marks_missing_numbers_as_not_available() -> None:
    row = _entry(oos_return=None, buy_and_hold_return=None).markdown_row()
    assert "| n/a | n/a |" in row


def test_markdown_row_flattens_pipes_and_newlines() -> None:
    row = _entry(reason="line one\nline two | with pipe").markdown_row()
    assert row.count("|") == 9
    assert "line one line two / with pipe" in row


def test_markdown_row_truncates_a_rambling_reason() -> None:
    row = _entry(reason="x" * 500).markdown_row()
    assert "..." in row
    assert "x" * 500 not in row


def test_entry_rejects_unknown_decision() -> None:
    with pytest.raises(ValueError, match="decision must be one of"):
        _entry(decision="looks-good")


def test_append_row_keeps_existing_rows(tmp_path: Path) -> None:
    path = _journal(tmp_path, body="| old row |\n")
    append_row(path, _entry())
    text = path.read_text(encoding="utf-8")
    assert "| old row |" in text
    assert text.index("old row") < text.index("| 2026-09-15 10:30 |")
    assert text.index("| 2026-09-15 10:30 |") < text.index(ROWS_END)
    assert text.rstrip().endswith("End.")


def test_append_row_is_append_only(tmp_path: Path) -> None:
    path = _journal(tmp_path)
    append_row(path, _entry(reason="first"))
    append_row(path, _entry(reason="second"))
    text = path.read_text(encoding="utf-8")
    assert text.count("| 2026-09-15 10:30 |") == 2
    assert text.index("first") < text.index("second")


def test_append_row_preserves_a_human_decision(tmp_path: Path) -> None:
    path = _journal(tmp_path)
    append_row(path, _entry())
    edited = path.read_text(encoding="utf-8").replace("⏳ pending", "✅ accepted")
    path.write_text(edited, encoding="utf-8")
    append_row(path, _entry(subject="ema ETH/USDT.SIM"))
    text = path.read_text(encoding="utf-8")
    assert text.count("✅ accepted") == 1
    assert text.count("⏳ pending") == 1


def test_append_row_fails_closed_without_markers(tmp_path: Path) -> None:
    path = tmp_path / "journal.md"
    path.write_text("# Journal without markers\n", encoding="utf-8")
    with pytest.raises(JournalFormatError, match="marker pair"):
        append_row(path, _entry())


def test_append_row_fails_closed_on_inverted_markers(tmp_path: Path) -> None:
    path = tmp_path / "journal.md"
    path.write_text(f"{ROWS_END}\n{ROWS_START}\n", encoding="utf-8")
    with pytest.raises(JournalFormatError, match="before"):
        append_row(path, _entry())


def test_append_row_fails_closed_when_journal_is_missing(tmp_path: Path) -> None:
    with pytest.raises(JournalFormatError, match="not found"):
        append_row(tmp_path / "absent.md", _entry())


def test_record_run_writes_both_logs(tmp_path: Path) -> None:
    markdown = _journal(tmp_path)
    jsonl = tmp_path / "nested" / "journal.jsonl"
    record_run(markdown_path=markdown, jsonl_path=jsonl, entry=_entry())
    assert "| 2026-09-15 10:30 |" in markdown.read_text(encoding="utf-8")
    payload = json.loads(jsonl.read_text(encoding="utf-8").strip())
    assert payload["subject"] == "regime ETH/USDT.SIM"
    assert payload["oos_return"] == "-0.007"
    assert payload["fills"] == 356
    assert payload["decision"] == PENDING


def test_records_round_trip(tmp_path: Path) -> None:
    jsonl = tmp_path / "journal.jsonl"
    entry = _entry(artifact="research/hypotheses/2026-09-15-x.json")
    append_record(jsonl, entry)
    append_record(jsonl, _entry(subject="ema ETH/USDT.SIM", oos_return=None))
    records = load_records(jsonl)
    assert len(records) == 2
    assert records[0] == entry
    assert records[1].oos_return is None
    assert records[0].artifact == "research/hypotheses/2026-09-15-x.json"


def test_load_records_treats_a_missing_file_as_empty_history(tmp_path: Path) -> None:
    assert load_records(tmp_path / "nothing.jsonl") == ()


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"created_at": 5}, "created_at"),
        ({"decision": 7}, "decision"),
        ({"fills": "many"}, "fills"),
        ({"source": ""}, "source"),
        ({"oos_return": 1.5}, "oos_return"),
    ],
)
def test_from_dict_rejects_untrusted_records(payload: dict[str, object], match: str) -> None:
    base: dict[str, object] = {
        "created_at": _NOW.isoformat(),
        "source": "lab research",
        "subject": "regime ETH/USDT.SIM",
        "gates": "walk-forward",
        "decision": PENDING,
        "reason": "",
        "oos_return": None,
        "buy_and_hold_return": None,
        "fills": None,
        "artifact": None,
    }
    base.update(payload)
    with pytest.raises(ValueError, match=match):
        JournalEntry.from_dict(base)
