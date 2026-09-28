"""Compare a live paper session's decisions with a backtest over the same window.

    uv run python scripts/trace_diff.py regime-eth-159a09 0d83e156-f6fd-483d-b21a-fe26721e1f8c

Reads both decision logs from `data/paper/decisions/` (or `--dir`) and aligns their
`bar_decision` records by bar timestamp. For every bar both saw, it compares the
`outcome` (and, when the outcome agrees, the raw `signal`); a bar where the live
terminal and the backtest decided differently is a divergence. It also warns when the
two runs used different parameters (`config_hash`), because then a divergence may just
be a different configuration rather than a bug.

This is the "does the paper terminal rehearse the tested config" check: a divergence on
the same bars and the same config means the live path and the engine disagreed, which
is a bug in one of them, not a market difference. `intrabar` records (stops, manual
closes) are counted but not diffed — they are event-driven, not one-per-bar.

Exit code 0 = the bars the two runs share all agree; 1 = divergences found, or the two
logs share no bars (nothing to compare).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nautilus_lab.infrastructure.decision_log_writer import JsonlDecisionLogWriter
from nautilus_lab.infrastructure.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = "data/paper/decisions"


@dataclass(frozen=True, slots=True)
class Divergence:
    """One bar where paper and backtest did not agree."""

    ts: str
    paper_outcome: str
    paper_signal: str
    backtest_outcome: str
    backtest_signal: str

    @property
    def kind(self) -> str:
        return "outcome" if self.paper_outcome != self.backtest_outcome else "signal"


@dataclass(frozen=True, slots=True)
class Diff:
    paper_bars: int
    backtest_bars: int
    common_bars: int
    paper_only: int
    backtest_only: int
    divergences: tuple[Divergence, ...]
    paper_config: str | None
    backtest_config: str | None
    paper_dupes: int
    backtest_dupes: int


def index_by_ts(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], int]:
    """Bar-decision rows keyed by `ts`, plus how many duplicate timestamps were dropped.

    A walk-forward backtest replays the same window per fold, so one `ts` can appear
    several times; the last occurrence wins and the count says how much was replayed.
    """
    index: dict[str, dict[str, Any]] = {}
    dupes = 0
    for row in rows:
        if row.get("kind") == "intrabar":
            continue
        ts = str(row.get("ts") or "")
        if not ts:
            continue
        if ts in index:
            dupes += 1
        index[ts] = row
    return index, dupes


def _config(rows: list[dict[str, Any]]) -> str | None:
    return next((str(r.get("config_hash")) for r in rows if r.get("config_hash")), None)


def diff(paper_rows: list[dict[str, Any]], backtest_rows: list[dict[str, Any]]) -> Diff:
    """Align two decision logs by bar timestamp and compare their decisions."""
    paper, paper_dupes = index_by_ts(paper_rows)
    backtest, backtest_dupes = index_by_ts(backtest_rows)
    common = sorted(set(paper) & set(backtest))
    divergences: list[Divergence] = []
    for ts in common:
        p, b = paper[ts], backtest[ts]
        po, bo = str(p.get("outcome") or ""), str(b.get("outcome") or "")
        ps, bs = str(p.get("signal") or ""), str(b.get("signal") or "")
        if po != bo or ps != bs:
            divergences.append(Divergence(ts, po, ps, bo, bs))
    return Diff(
        paper_bars=len(paper),
        backtest_bars=len(backtest),
        common_bars=len(common),
        paper_only=len(set(paper) - set(backtest)),
        backtest_only=len(set(backtest) - set(paper)),
        divergences=tuple(divergences),
        paper_config=_config(paper_rows),
        backtest_config=_config(backtest_rows),
        paper_dupes=paper_dupes,
        backtest_dupes=backtest_dupes,
    )


def _bar_line(label: str, key: str, bars: int, dupes: int, config: str | None) -> str:
    dup = f" replays={dupes}" if dupes else ""
    cfg = f" config={config}" if config else " config=?"
    return f"{label:<9} {key}  bars={bars}{dup}{cfg}"


def render(diff: Diff, *, paper_key: str, backtest_key: str, limit: int = 20) -> str:
    lines = [
        _bar_line("paper", paper_key, diff.paper_bars, diff.paper_dupes, diff.paper_config),
        _bar_line(
            "backtest", backtest_key, diff.backtest_bars, diff.backtest_dupes, diff.backtest_config
        ),
        f"common={diff.common_bars}  paper_only={diff.paper_only}  "
        f"backtest_only={diff.backtest_only}",
    ]
    if diff.paper_config and diff.backtest_config and diff.paper_config != diff.backtest_config:
        lines.append(
            f"WARNING: config differs (paper={diff.paper_config}, "
            f"backtest={diff.backtest_config}) — divergences may just be different parameters"
        )
    if diff.common_bars == 0:
        lines.append("no common bars: the two logs cover different windows or instruments")
        return "\n".join(lines)
    lines.append(f"divergences: {len(diff.divergences)} / {diff.common_bars} common bars")
    shown = diff.divergences[:limit]
    lines.extend(
        f"  {item.ts}  {item.kind:<7}  paper={item.paper_outcome or '—'}"
        f"[{item.paper_signal or '—'}]  backtest={item.backtest_outcome or '—'}"
        f"[{item.backtest_signal or '—'}]"
        for item in shown
    )
    if len(diff.divergences) > limit:
        lines.append(f"  … and {len(diff.divergences) - limit} more (raise --limit)")
    return "\n".join(lines)


def _writer(directory: str) -> JsonlDecisionLogWriter:
    # retention_days=0: this is a read-only tool and must never prune a log it reads.
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        decision_log_enabled=True,
        decision_log_dir=directory,
        decision_log_retention_days=0,
    )
    return JsonlDecisionLogWriter(settings, root=ROOT)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paper", help="live paper session id or research-run key")
    parser.add_argument("backtest", help="backtest run key (single_backtest.session_id)")
    parser.add_argument("--dir", default=DEFAULT_DIR, help="decision log directory")
    parser.add_argument("--limit", type=int, default=20, help="divergences to print")
    args = parser.parse_args(argv)

    writer = _writer(args.dir)
    paper = writer.read_range(args.paper)
    backtest = writer.read_range(args.backtest)
    if not paper and not backtest:
        print(f"no decision records for {args.paper!r} or {args.backtest!r}", file=sys.stderr)
        return 1
    result = diff(paper, backtest)
    print(render(result, paper_key=args.paper, backtest_key=args.backtest, limit=args.limit))
    if result.common_bars == 0 or result.divergences:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
