"""Preregister alpha hypotheses, then run them on validation once.

  # 1. register: fixes hypotheses + criteria, writes research/preregistrations/alpha-*.json
  .venv/bin/python scripts/alpha_validate.py register \
      --spec research/alpha/validation-spec-2026-10-20.json \
      --exploration-report reports/alpha_screen/20261020_085712_perp_1h/alpha_screen.md
  git add research/preregistrations/alpha-*.json && git commit -m "preregister alpha H1-H2"

  # 2. run: one look per registration; the outcome goes to research/alpha_validation_log.jsonl
  .venv/bin/python scripts/alpha_validate.py run --prereg research/preregistrations/alpha-....json

`run` refuses a registration that was already run, edited after registration, or that
names a holdout coin.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from nautilus_lab.application.alpha.universe import load_universe
from nautilus_lab.application.alpha.validate import (
    Criteria,
    Hypothesis,
    Leg,
    Preregistration,
    file_sha256,
    read_preregistration,
    run_validation,
    write_preregistration,
)
from nautilus_lab.domain.data_zone import DEFAULT_ZONE_POLICY
from nautilus_lab.infrastructure.alpha_panel_store import load_or_build

DEFAULT_SYMBOLS = (
    "BTCUSDT,ETHUSDT,ADAUSDT,AVAXUSDT,BNBUSDT,DOGEUSDT,DOTUSDT,LINKUSDT,LTCUSDT,SOLUSDT,XRPUSDT"
)


def _register(args: argparse.Namespace) -> int:
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    if args.universe:
        universe = load_universe(Path(args.universe))
        symbols = DEFAULT_ZONE_POLICY.research_symbols(universe.ever())
        panel_label = f"{spec.get('panel_label', 'perp_1h')}_top{universe.top_n}"
    else:
        symbols = DEFAULT_ZONE_POLICY.research_symbols(
            s.strip().upper() for s in args.symbols.split(",") if s.strip()
        )
        panel_label = spec.get("panel_label", "perp_1h")
    prereg = Preregistration(
        hypotheses=tuple(
            Hypothesis(
                id=h["id"],
                legs=tuple(
                    Leg(signal=leg["signal"], direction=int(leg["direction"])) for leg in h["legs"]
                ),
                horizon=int(h["horizon"]),
                rationale=h["rationale"],
                beta_neutral=bool(h.get("beta_neutral", True)),
            )
            for h in spec["hypotheses"]
        ),
        symbols=symbols,
        panel_label=panel_label,
        cost_bps=float(spec.get("cost_bps", 7.0)),
        criteria=Criteria(**spec.get("criteria", {})),
        exploration_report=args.exploration_report,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        note=spec.get("note", ""),
        universe=args.universe or "",
        universe_sha256=file_sha256(Path(args.universe)) if args.universe else "",
    )
    path = write_preregistration(prereg, Path(args.out))
    print(f"registered {len(prereg.hypotheses)} hypotheses as {prereg.digest}: {path}")
    print("commit this file before `run`; the digest is its identity")
    return 0


def _run(args: argparse.Namespace) -> int:
    prereg = read_preregistration(Path(args.prereg))
    interval = prereg.panel_label.split("_")[1]
    membership_of = None
    if prereg.universe:
        universe_path = Path(prereg.universe)
        if file_sha256(universe_path) != prereg.universe_sha256:
            raise SystemExit(
                f"{universe_path} changed since registration (sha256 mismatch); "
                "the registered universe is the only one this hypothesis may use"
            )
        membership_of = load_universe(universe_path).mask
    panel = load_or_build(
        Path(args.panel_cache or f"research/panels/{prereg.panel_label}.npz"),
        rebuild=False,
        bar_catalog=Path(args.bar_catalog),
        symbols=prereg.symbols,
        interval=interval,
        perp=prereg.panel_label.startswith("perp"),
        funding_catalog=Path(args.funding_catalog),
    )
    run = run_validation(
        panel,
        prereg,
        policy=DEFAULT_ZONE_POLICY,
        log=Path(args.log),
        membership=membership_of(panel) if membership_of else None,
    )
    print(f"validation {run.digest} windows={run.windows} (logged to {args.log})")
    for outcome in run.outcomes:
        book = outcome.book
        verdict = "PASS" if outcome.passed else "FAIL"
        print(
            f"  {verdict} {outcome.id}: IC={_f(outcome.ic_mean, 4)} t={_f(outcome.t_block, 2)} "
            f"p={_f(outcome.p_one_sided, 4)} (<= {outcome.p_threshold:.4f}) "
            f"SRnet={_f(book.sharpe_net, 2)} be={_f(book.breakeven_bps, 1)}bps "
            f"corr={_f(book.market_corr, 2)} years={outcome.net_sharpe_by_year}"
        )
        for reason in outcome.reasons:
            print(f"      - {reason}")
    return 0 if all(o.passed for o in run.outcomes) else 3


def _f(value: float | None, digits: int) -> str:
    return "n/a" if value is None else f"{value:+.{digits}f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preregistered alpha validation")
    sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register")
    reg.add_argument("--spec", required=True)
    reg.add_argument("--exploration-report", required=True)
    reg.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    reg.add_argument("--universe", default=None, help="point-in-time universe file")
    reg.add_argument("--out", default="research/preregistrations")
    run = sub.add_parser("run")
    run.add_argument("--prereg", required=True)
    run.add_argument("--bar-catalog", default="catalog_perp_1h")
    run.add_argument("--funding-catalog", default="catalog")
    run.add_argument("--panel-cache", default=None)
    run.add_argument("--log", default="research/alpha_validation_log.jsonl")
    args = parser.parse_args(argv)
    return _register(args) if args.command == "register" else _run(args)


if __name__ == "__main__":
    sys.exit(main())
