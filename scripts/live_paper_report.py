"""Summarise a live paper journal pulled from the VPS (scripts/pull_vps.sh).

    uv run python scripts/live_paper_report.py data/vps/paper
    uv run python scripts/live_paper_report.py data/vps/paper --csv out/

Arguments are journal files or folders (every `*.jsonl` inside, recursively: the
single-session `live_events.jsonl` and one file per session under `sessions/`).

One block per session: configuration, fills, fees, realised and marked PnL, max
drawdown of the per-bar equity curve. `--csv DIR` also writes fills.csv and
equity.csv (one row per closed bar) for a notebook — or read the journal directly:

    import pandas as pd
    events = pd.read_json("data/vps/paper/live_events.jsonl", lines=True)

Numbers are exactly what the terminal booked; nothing is recomputed from prices.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_lab.infrastructure.live_paper_journal import (
    FILL,
    SESSION_START,
    SESSION_STOP,
    SNAPSHOT,
    LivePaperJournal,
)


@dataclass
class SessionSummary:
    session_id: str
    config: dict[str, Any]
    started_at: str
    stopped: bool = False
    fills: list[dict[str, Any]] = field(default_factory=list)
    equity: list[dict[str, Any]] = field(default_factory=list)
    last_snapshot: dict[str, Any] | None = None


def collect(journal: LivePaperJournal) -> list[SessionSummary]:
    sessions: dict[str, SessionSummary] = {}
    for record in journal.events():
        sid = str(record["session_id"])
        if record["type"] == SESSION_START:
            sessions[sid] = SessionSummary(
                session_id=sid,
                config=dict(record.get("config") or {}),
                started_at=str(record.get("started_at") or record.get("logged_at") or ""),
            )
            continue
        summary = sessions.get(sid)
        if summary is None:
            continue
        if record["type"] == FILL and isinstance(record.get("fill"), dict):
            summary.fills.append(record["fill"])
        elif record["type"] == SNAPSHOT:
            summary.last_snapshot = record
            point = record.get("equity_point")
            if isinstance(point, dict):
                summary.equity.append(point)
        elif record["type"] == SESSION_STOP:
            summary.stopped = True
    return list(sessions.values())


def max_drawdown(equity: list[float]) -> float:
    peak = float("-inf")
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst


def journal_paths(inputs: list[Path]) -> list[Path]:
    paths: list[Path] = []
    for item in inputs:
        if item.is_dir():
            paths.extend(sorted(item.rglob("*.jsonl")))
        elif item.exists():
            paths.append(item)
    return paths


def marked_return(summary: SessionSummary) -> Decimal | None:
    start = Decimal(str(summary.config.get("starting_equity", "0")))
    snap = summary.last_snapshot or {}
    if start <= 0 or "equity" not in snap:
        return None
    return (Decimal(str(snap["equity"])) / start - 1) * 100


def benchmarks(summaries: list[SessionSummary]) -> dict[tuple[str, str], Decimal]:
    """Latest `hold` session per symbol+interval: what every robot there is judged against."""
    found: dict[tuple[str, str], Decimal] = {}
    for summary in summaries:
        cfg = summary.config
        value = marked_return(summary)
        if cfg.get("robot") == "hold" and value is not None:
            found[(str(cfg.get("symbol")), str(cfg.get("interval")))] = value
    return found


def render(summary: SessionSummary, bench: dict[tuple[str, str], Decimal] | None = None) -> str:
    cfg = summary.config
    snap = summary.last_snapshot or {}
    start = Decimal(str(cfg.get("starting_equity", "0")))
    equity = Decimal(str(snap.get("equity", start)))
    fees = sum((Decimal(str(f.get("fee", "0"))) for f in summary.fills), Decimal("0"))
    closes = [f for f in summary.fills if not str(f.get("reason", "")).startswith("Open ")]
    wins = sum(1 for f in closes if Decimal(str(f.get("realized_pnl", "0"))) > 0)
    ret = (equity / start - 1) * 100 if start > 0 else Decimal("0")
    dd = max_drawdown([float(p["equity"]) for p in summary.equity]) * 100
    status = "stopped" if summary.stopped else "running/resumable"
    position = snap.get("position")
    name = cfg.get("name") or "-"
    lines = [
        f"session {name} ({summary.session_id})  [{status}]  started {summary.started_at}",
        f"  {cfg.get('robot')} {cfg.get('symbol')} {cfg.get('interval')}  "
        f"risk/trade={cfg.get('risk_per_trade')} stop={cfg.get('stop_pct')} "
        f"tp_x={cfg.get('take_profit_multiple')} taker_fee={cfg.get('taker_fee')}",
        f"  bars={len(summary.equity)} fills={len(summary.fills)} "
        f"closed_trades={len(closes)} wins={wins}",
        f"  start={start} equity(marked)={equity:.2f} return={ret:.2f}% "
        f"realized={Decimal(str(snap.get('realized_pnl', '0'))):.2f} fees={fees:.2f} "
        f"max_dd={dd:.2f}%",
        f"  open_position={position if position else 'flat'}",
    ]
    key = (str(cfg.get("symbol")), str(cfg.get("interval")))
    if bench and cfg.get("robot") != "hold" and key in bench:
        lines.append(f"  vs hold {key[0]} {key[1]}: {ret - bench[key]:+.2f} pp")
    if cfg.get("notes"):
        lines.append(f"  notes: {cfg.get('notes')}")
    refusals = snap.get("risk_refusals") or {}
    if refusals:
        lines.append(f"  risk_refusals={refusals}")
    return "\n".join(lines)


def write_csv(summaries: list[SessionSummary], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fill_keys = ["id", "ts", "symbol", "side", "qty", "price", "fee", "realized_pnl", "reason"]
    with (out_dir / "fills.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["session_id", *fill_keys])
        for summary in summaries:
            for fill in summary.fills:
                writer.writerow([summary.session_id, *(fill.get(k, "") for k in fill_keys)])
    eq_keys = ["time", "equity", "realized_pnl", "unrealized_pnl"]
    with (out_dir / "equity.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["session_id", *eq_keys])
        for summary in summaries:
            for point in summary.equity:
                writer.writerow([summary.session_id, *(point.get(k, "") for k in eq_keys)])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "journals", type=Path, nargs="+", help="journal files or folders (e.g. data/vps/paper)"
    )
    parser.add_argument("--csv", type=Path, default=None, help="write fills.csv/equity.csv here")
    args = parser.parse_args(argv)
    paths = journal_paths(args.journals)
    if not paths:
        print(f"no journal files in: {', '.join(map(str, args.journals))}", file=sys.stderr)
        return 1
    summaries = [s for path in paths for s in collect(LivePaperJournal(path))]
    summaries.sort(key=lambda s: s.started_at)
    if not summaries:
        print("journals have no sessions")
        return 0
    bench = benchmarks(summaries)
    print("\n\n".join(render(s, bench) for s in summaries))
    if args.csv is not None:
        write_csv(summaries, args.csv)
        print(f"\nwrote {args.csv / 'fills.csv'} and {args.csv / 'equity.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
