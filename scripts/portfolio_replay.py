#!/usr/bin/env python3
"""Replay a batch's single-coin cells on one shared account (plan 2026-10-16, P1.5/1.6).

Reads `reports/batches/<id>/cells/*/trades.jsonl` (written with each cell's summary since
SUMMARY_VERSION 5; for older batches the trades are rebuilt from the decision logs, without
funding) and runs them through `application/portfolio_replay.py`:

    uv run python scripts/portfolio_replay.py reports/batches/20261013_053010_batch --robot regime
    uv run python scripts/portfolio_replay.py <batch> --variant R1_fixed40 --heat 0.03 --per-side 4
    uv run python scripts/portfolio_replay.py <batch> --variant R1_fixed40 --target-vol 0.12
    uv run python scripts/portfolio_replay.py <batch> --variant E20,E40,E90 --risk 0.00167

Several variants (comma-separated) replay as one ensemble: every sub-system's trades go
on the account, each at `--risk`, and the side cap counts a coin once however many
sub-systems hold it. Give the ensemble the single system's total risk split evenly.

Three replays are printed side by side: `uncapped` (every trade at the same risk — the sum
of the separate accounts), `capped` (heat and side caps) and, with `--target-vol`,
`capped+vol`. The report lands next to the batch as `portfolio_<robot>[_<variant>].md`.

It is a replay of trades the cells already made, not a new backtest: read the module
docstring before reading the numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from nautilus_lab.application.portfolio_replay import (
    ReplayResult,
    ReplayRules,
    ReplayTrade,
    render_markdown,
    replay,
    trade_from_row,
)
from nautilus_lab.application.trade_breakdown import fold_of, reconstruct_trades, trade_row


def _cell_matches(name: str, robot: str, variants: frozenset[str]) -> bool:
    base, _, suffix = name.partition("__")
    if not base.startswith(f"{robot}_"):
        return False
    return suffix in variants if variants else suffix == ""


def _decision_records(decisions: Path) -> Iterator[tuple[int, Mapping[str, Any]]]:
    files = [(fold_of(path.name), path) for path in decisions.glob("*.jsonl")]
    for fold, path in sorted((f, p) for f, p in files if f is not None):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    yield fold, record


def _cell_rows(cell_dir: Path, taker_fee: float) -> tuple[list[dict[str, Any]], str]:
    """The cell's trade rows and where they came from."""
    path = cell_dir / "trades.jsonl"
    if path.exists():
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return rows, "trades.jsonl"
    rec = reconstruct_trades(_decision_records(cell_dir / "decisions"), taker_fee=taker_fee)
    return [trade_row(trade) for trade in rec.trades], "decisions (no funding)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else None)
    parser.add_argument("batch_dir", type=Path)
    parser.add_argument("--robot", default="regime")
    parser.add_argument(
        "--variant",
        default=None,
        help="Variant name (cell id after '__'); comma-separated = one ensemble",
    )
    parser.add_argument("--risk", type=float, default=0.005, help="Risk per trade, share")
    parser.add_argument("--heat", type=float, default=0.03, help="Max open risk, share")
    parser.add_argument("--per-side", type=int, default=4, help="Max positions per side")
    parser.add_argument("--target-vol", type=float, default=None, help="Annualised, e.g. 0.12")
    parser.add_argument("--taker-fee", type=float, default=0.00075, help="For rebuilt trades")
    parser.add_argument("--exclude", default="", help="Comma-separated cell ids to leave out")
    args = parser.parse_args(argv)

    cells_root = args.batch_dir / "cells"
    if not cells_root.is_dir():
        print(f"no cells directory in {args.batch_dir}", file=sys.stderr)
        return 2
    excluded = {item.strip() for item in args.exclude.split(",") if item.strip()}
    variants = frozenset(v.strip() for v in (args.variant or "").split(",") if v.strip())
    trades: list[ReplayTrade] = []
    sources: list[str] = []
    for cell_dir in sorted(p for p in cells_root.iterdir() if p.is_dir()):
        if cell_dir.name in excluded or not _cell_matches(cell_dir.name, args.robot, variants):
            continue
        rows, source = _cell_rows(cell_dir, args.taker_fee)
        group = cell_dir.name.partition("__")[0]  # the coin: one position for the side cap
        cell_trades = [
            t for t in (trade_from_row(cell_dir.name, r, group=group) for r in rows) if t
        ]
        trades.extend(cell_trades)
        sources.append(f"- {cell_dir.name}: {len(cell_trades)} trades from {source}")
    if not trades:
        print("no trades matched (check --robot / --variant)", file=sys.stderr)
        return 1

    replays: dict[str, ReplayResult] = {
        "uncapped": replay(
            trades, ReplayRules(risk_per_trade=args.risk, max_heat=None, max_per_side=None)
        ),
        "capped": replay(
            trades,
            ReplayRules(risk_per_trade=args.risk, max_heat=args.heat, max_per_side=args.per_side),
        ),
    }
    if args.target_vol is not None:
        replays["capped+vol"] = replay(
            trades,
            ReplayRules(
                risk_per_trade=args.risk,
                max_heat=args.heat,
                max_per_side=args.per_side,
                target_vol=args.target_vol,
            ),
        )

    capped = replays["capped"]
    folds = sorted(set().union(*(res.pnl_by_fold for res in replays.values())))
    lines = [
        f"# Portfolio replay — {args.batch_dir.name}, {args.robot}"
        + (f" / {args.variant}" if args.variant else ""),
        "",
        f"Risk per trade {args.risk:.2%}, heat cap {args.heat:.1%}, {args.per_side} per side"
        + (f", vol target {args.target_vol:.0%}" if args.target_vol else "")
        + ". Replay of the cells' own trades on one account; drawdown on realised equity only.",
        "",
        render_markdown(replays),
        "",
        "## PnL by fold (account currency)",
        "",
        "| fold | " + " | ".join(replays) + " |",
        "|---|" + "---:|" * len(replays),
    ]
    for fold in folds:
        values = " | ".join(f"{res.pnl_by_fold.get(fold, 0.0):+,.0f}" for res in replays.values())
        lines.append(f"| {fold} | {values} |")
    lines += ["", "## PnL by cell (capped)", "", "| cell | PnL |", "|---|---:|"]
    lines += [f"| {cell} | {pnl:+,.0f} |" for cell, pnl in capped.pnl_by_cell.items()]
    lines += ["", "## Sources", "", *sources, ""]
    report = "\n".join(lines)
    suffix = f"_{'+'.join(sorted(variants))}" if variants else ""
    out = args.batch_dir / f"portfolio_{args.robot}{suffix}.md"
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
