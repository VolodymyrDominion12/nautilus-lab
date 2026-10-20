"""Alpha screen (A1): G2 templates against residual forward returns, exploration only.

Usage (from the repository root):

  .venv/bin/python scripts/alpha_screen.py                      # 11 perps 1h, default zones
  .venv/bin/python scripts/alpha_screen.py --rebuild            # after `lab ingest`
  .venv/bin/python scripts/alpha_screen.py --horizons 4,24,72 --perms 500
  .venv/bin/python scripts/alpha_screen.py --no-ledger          # dry run: trials not recorded

Writes `reports/alpha_screen/<UTC date>_<label>/alpha_screen.{json,md}` and appends the
trials to `research/trials.jsonl`. The DSR anywhere else then sees that this
dataset was searched.

There is no `--zone` flag. The screen is selection, and selection is allowed on
exploration only (see `domain/data_zone.py`).
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from nautilus_lab.application.alpha.report import record_trials, write_report
from nautilus_lab.application.alpha.screen import ScreenConfig, run_screen
from nautilus_lab.domain.data_zone import DEFAULT_ZONE_POLICY, DataZone
from nautilus_lab.infrastructure.alpha_panel_store import load_or_build
from nautilus_lab.infrastructure.trial_ledger import JsonlTrialLedger

DEFAULT_SYMBOLS = (
    "BTCUSDT,ETHUSDT,ADAUSDT,AVAXUSDT,BNBUSDT,DOGEUSDT,DOTUSDT,LINKUSDT,LTCUSDT,SOLUSDT,XRPUSDT"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bar-catalog", default="catalog_perp_1h")
    parser.add_argument("--funding-catalog", default="catalog")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--spot", action="store_true", help="spot bars: no funding, no premium")
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--horizons", default="1,4,24,72,168", help="in bars")
    parser.add_argument("--cost-bps", type=float, default=7.0)
    parser.add_argument("--perms", type=int, default=200)
    parser.add_argument("--panel-cache", default=None)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--out", default="reports/alpha_screen")
    parser.add_argument("--ledger", default="research/trials.jsonl")
    parser.add_argument("--no-ledger", action="store_true")
    args = parser.parse_args(argv)

    perp = not args.spot
    label = f"{'perp' if perp else 'spot'}_{args.interval}"
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    cache = Path(args.panel_cache or f"research/panels/{label}.npz")

    started = time.monotonic()
    panel = load_or_build(
        cache,
        rebuild=args.rebuild,
        bar_catalog=Path(args.bar_catalog),
        symbols=symbols,
        interval=args.interval,
        perp=perp,
        funding_catalog=Path(args.funding_catalog) if perp else None,
    )
    elapsed = time.monotonic() - started
    print(f"panel {panel.shape[0]} bars x {panel.shape[1]} symbols ({elapsed:.1f}s)")

    config = ScreenConfig(
        horizons=tuple(int(h) for h in args.horizons.split(",")),
        cost_bps=args.cost_bps,
        permutations=args.perms,
    )
    report = run_screen(panel, policy=DEFAULT_ZONE_POLICY, zone=DataZone.EXPLORATION, config=config)
    ledger = None if args.no_ledger else JsonlTrialLedger(Path(args.ledger))
    report = replace(report, trials_total=record_trials(ledger, report, label))

    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path, md_path = write_report(report, Path(args.out) / f"{stamp}_{label}", label)
    print(f"wrote {json_path} and {md_path} ({time.monotonic() - started:.1f}s)")
    print(f"research symbols: {', '.join(report.symbols)}; held out: {', '.join(report.held_out)}")
    print(f"controls_ok={report.controls_ok} trials_total={report.trials_total}")
    for result in report.candidates:
        book = result.book_beta_neutral
        print(
            f"  CANDIDATE {result.trial_id} ic={result.ic_mean:+.4f} t={result.t_block:+.2f} "
            f"z={result.perm_z:+.2f} SRnet={book.sharpe_net:+.2f} be={book.breakeven_bps:.1f}bps"
        )
    if not report.candidates:
        print("  no candidates passed the gate")
    return 0 if report.controls_ok else 2


if __name__ == "__main__":
    sys.exit(main())
