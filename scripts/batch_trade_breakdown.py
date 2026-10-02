#!/usr/bin/env python3
"""Per-trade breakdown of every cell of a batch backtest (docs/33).

Reads `reports/batches/<id>/cells/*/decisions/*.jsonl`, rebuilds round trips, tags them
with the entry-gate features (slow-EMA slope, vol ratio) and writes one Markdown report
plus a CSV of trades per cell next to the batch.

    uv run python scripts/batch_trade_breakdown.py reports/batches/20261002_131115_batch
    uv run python scripts/batch_trade_breakdown.py <batch> --cells regime_ETH,regime_BTC

For 4h cells pass the same calendar spans as on 1h (docs/33 §3):
    --htf-ema-period 50 --htf-slope-lookback 6 --vol-fast 6 --vol-slow 75

The tags are diagnostics found on the very OOS data being described: a group that
"would have been better" is a hypothesis to pre-register, not a result.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterator, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_lab.application.trade_breakdown import (
    Trade,
    bars_from_records,
    fold_of,
    gate_features,
    reconstruct_trades,
    render_cell_markdown,
    tag_trades,
)
from nautilus_lab.domain.entry_filters import EntryFilterParams


def _records(decisions: Path) -> Iterator[tuple[int, Mapping[str, Any]]]:
    """`(fold, record)` in log order: files by (fold, day), lines as written."""
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


def _write_csv(path: Path, trades: list[Trade]) -> None:
    fields = [
        "fold", "side", "leg", "regime", "entry_reason", "ts_in", "px_in", "qty", "stop",
        "ts_out", "px_out", "exit_reason", "gross", "fees", "net", "r_multiple", "fee_r",
        "hold_hours", "slope_aligned", "vol_ratio",
    ]  # fmt: skip
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        for t in trades:
            writer.writerow([getattr(t, name) for name in fields])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else None)
    parser.add_argument("batch_dir", type=Path)
    parser.add_argument("--cells", help="Comma-separated cell ids (default: all)")
    parser.add_argument("--taker-fee", type=float, default=0.00075)
    parser.add_argument("--htf-ema-period", type=int, default=200)
    parser.add_argument("--htf-slope-lookback", type=int, default=24)
    parser.add_argument("--vol-fast", type=int, default=24)
    parser.add_argument("--vol-slow", type=int, default=300)
    parser.add_argument(
        "--out", type=Path, help="Report path (default: <batch>/trade_breakdown.md)"
    )
    args = parser.parse_args(argv)

    cells_dir = args.batch_dir / "cells"
    if not cells_dir.is_dir():
        print(f"ERROR: no cells/ under {args.batch_dir}", file=sys.stderr)
        return 1
    wanted = {c.strip() for c in args.cells.split(",")} if args.cells else None
    params = EntryFilterParams(
        htf_trend=True,
        htf_ema_period=args.htf_ema_period,
        htf_slope_lookback=args.htf_slope_lookback,
        vol_expansion=True,
        vol_fast_period=args.vol_fast,
        vol_slow_period=args.vol_slow,
        min_vol_ratio=Decimal("1"),
    )
    sections = [
        f"# Trade breakdown — {args.batch_dir.name}",
        "",
        f"taker fee {args.taker_fee}; slow EMA {params.htf_ema_period}/"
        f"{params.htf_slope_lookback}; vol ratio {params.vol_fast_period}/"
        f"{params.vol_slow_period}. Diagnostics on OOS data, not results.",
        "",
    ]
    for cell in sorted(p for p in cells_dir.iterdir() if p.is_dir()):
        if wanted is not None and cell.name not in wanted:
            continue
        decisions = cell / "decisions"
        if not decisions.is_dir():
            continue
        records = list(_records(decisions))
        rec = reconstruct_trades(records, taker_fee=args.taker_fee)
        bars = bars_from_records((r for _, r in records), instrument_id=cell.name)
        trades = tag_trades(rec.trades, gate_features(bars, params))
        _write_csv(cell / "trades.csv", trades)
        sections.append(render_cell_markdown(cell.name, rec, trades))
        print(f"{cell.name}: {len(trades)} trades, net {sum(t.net for t in trades):,.0f}")
    out = args.out or args.batch_dir / "trade_breakdown.md"
    out.write_text("\n".join(sections), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
