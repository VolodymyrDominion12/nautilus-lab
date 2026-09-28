"""The paper↔backtest decision diff: align by bar timestamp, compare outcome/signal."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

TRACE_DIFF = Path(__file__).resolve().parents[2] / "scripts" / "trace_diff.py"


def _load() -> ModuleType:
    """scripts/ is not a package; load it the way `uv run python scripts/...` does."""
    spec = importlib.util.spec_from_file_location("trace_diff", TRACE_DIFF)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


trace_diff = _load()


def _row(
    ts: str,
    outcome: str,
    signal: str = "",
    *,
    kind: str = "bar_decision",
    **extra: Any,
) -> dict[str, Any]:
    return {"ts": ts, "kind": kind, "outcome": outcome, "signal": signal, **extra}


def test_index_by_ts_drops_intrabar_and_counts_replays() -> None:
    index, dupes = trace_diff.index_by_ts(
        [
            _row("2026-09-25T10:00:00+00:00", "ENTRY_OPENED", "buy"),
            _row("2026-09-25T10:00:00+00:00", "HOLD_NOOP", "buy"),  # a replayed fold
            _row("2026-09-25T10:01:00+00:00", "STOP_LOSS", kind="intrabar"),
        ]
    )
    assert list(index) == ["2026-09-25T10:00:00+00:00"]
    assert index["2026-09-25T10:00:00+00:00"]["outcome"] == "HOLD_NOOP"  # last wins
    assert dupes == 1


def test_diff_reports_outcome_and_signal_divergences() -> None:
    paper = [
        _row("t1", "ENTRY_OPENED", "buy"),
        _row("t2", "NO_SIGNAL"),
        _row("t3", "EXIT", "sell"),
        _row("t_paper_only", "NO_SIGNAL"),
    ]
    backtest = [
        _row("t1", "ENTRY_BLOCKED_RISK", "buy"),
        _row("t2", "NO_SIGNAL"),
        _row("t3", "EXIT", "flat"),
        _row("t_backtest_only", "NO_SIGNAL"),
    ]
    result = trace_diff.diff(paper, backtest)
    assert result.common_bars == 3
    assert result.paper_only == 1
    assert result.backtest_only == 1
    assert [item.kind for item in result.divergences] == ["outcome", "signal"]
    assert result.divergences[0].ts == "t1"


def test_diff_reports_config_mismatch_and_no_common_bars() -> None:
    paper = [_row("t1", "NO_SIGNAL", config_hash="aaa")]
    backtest = [_row("t2", "NO_SIGNAL", config_hash="bbb")]
    result = trace_diff.diff(paper, backtest)
    assert result.common_bars == 0
    assert result.paper_config == "aaa"
    assert result.backtest_config == "bbb"

    text = trace_diff.render(result, paper_key="p", backtest_key="b")
    assert "no common bars" in text
    assert "config differs" in text


def test_render_counts_and_caps_divergences() -> None:
    paper = [
        _row("t0", "ENTRY_OPENED", "buy"),
        _row("t1", "NO_SIGNAL"),
        _row("t2", "NO_SIGNAL"),
        _row("t3", "EXIT", "sell"),
    ]
    backtest = [
        _row("t0", "NO_SIGNAL"),
        _row("t1", "NO_SIGNAL"),
        _row("t2", "NO_SIGNAL"),
        _row("t3", "EXIT", "sell"),
    ]
    result = trace_diff.diff(paper, backtest)
    assert len(result.divergences) == 1

    text = trace_diff.render(result, paper_key="p", backtest_key="b", limit=1)
    assert "divergences: 1 / 4" in text
    assert "t0" in text
