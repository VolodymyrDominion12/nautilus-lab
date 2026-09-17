#!/usr/bin/env python3
"""Offline A/B: does an input-dependent (selective) filter beat a fixed one?

Question behind the experiment (see `docs/18-transformery-ssm-vidpovidnist.md` §3, P3):
in Mamba the discretisation step is a function of the input. In the scalar case that
recurrence is an EMA, so the whole idea reduces to one measurable question — does
alpha_t = f(efficiency ratio) beat a constant alpha, on real bars, after fees?

Method: the same rolling-fold geometry the CLI uses (`rolling_windows`, folds=4,
in-sample fraction 0.7, embargo 10), but with the configuration **fixed by hand inside
each fold** instead of selected on in-sample. That is deliberate: parameter selection
would hide the effect being measured, because the control (selectivity = 0) could win
selection for reasons unrelated to selectivity. Each fold is scored out-of-sample only,
and buy&hold is computed on the same out-of-sample block.

Reported per configuration: OOS return per fold, mean, fills, traded notional, and the
breakeven cost from `domain/metrics.py`. This is not a substitute for
`lab research --robot adaptive_ema --folds 4` (which selects on IS) — it is the direct
control experiment that run cannot give, because selectivity = 0 is a legal grid point
and would simply be the winner if adaptivity adds nothing.

Run: .venv/bin/python scripts/experiment_adaptive_filter.py
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from nautilus_lab.domain.adaptive_ema import AdaptiveEmaParams
from nautilus_lab.domain.bars import BarOrigin
from nautilus_lab.domain.metrics import buy_and_hold_return
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.walk_forward import rolling_windows, split_by_window
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.infrastructure.timeframe import nautilus_bar_type
from nautilus_lab.interfaces.composition import research_request

FOLDS = 4
IN_SAMPLE_FRACTION = Decimal("0.7")
EMBARGO_BARS = 10
CONFIGS: tuple[tuple[str, Decimal], ...] = (
    ("selectivity=0 (control: fixed alpha)", Decimal("0")),
    ("selectivity=0.5", Decimal("0.5")),
    ("selectivity=1", Decimal("1")),
)


def _oos_return(ending: Decimal | None, starting: Decimal) -> Decimal | None:
    if ending is None or starting <= 0:
        return None
    return (ending - starting) / starting


def _percent(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.2f}%"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="catalog", help="Parquet catalog path")
    parser.add_argument("--interval", default="1h", help="Bar interval")
    parser.add_argument("--instrument", default="ETH/USDT.SIM", help="Instrument id")
    parser.add_argument("--period", type=int, default=40, help="Base EMA period")
    parser.add_argument("--folds", type=int, default=FOLDS, help="Rolling folds")
    args = parser.parse_args()

    cfg = Settings(catalog_path=args.catalog, bar_interval=args.interval)
    cfg = cfg.model_copy(update={"instrument_id": args.instrument})
    store = NautilusParquetCatalog(Path(args.catalog), fees=cfg.fee_schedule())
    bars = store.load(bar_type=nautilus_bar_type(args.instrument, args.interval))
    windows = rolling_windows(
        bars,
        folds=args.folds,
        in_sample_fraction=IN_SAMPLE_FRACTION,
        embargo_bars=EMBARGO_BARS,
    )

    base_request = research_request(
        cfg,
        bar_count=len(bars),
        robot=RobotName.ADAPTIVE_EMA,
        source=BarOrigin.CATALOG,
    )
    engine = NautilusResearchBacktest()

    returns: dict[str, list[Decimal | None]] = {label: [] for label, _ in CONFIGS}
    print(
        f"{args.instrument} {args.interval} bars={len(bars)} folds={len(windows)} "
        f"period={args.period} (configs fixed, NOT selected on in-sample)"
    )
    for index, window in enumerate(windows):
        split = split_by_window(bars, window)
        oos_bars = list(split.out_of_sample)
        baseline = buy_and_hold_return(oos_bars)
        print(
            f"  fold {index} OOS=[{window.out_of_sample_start.isoformat()}, "
            f"{window.out_of_sample_end.isoformat()}) bars={len(oos_bars)} "
            f"buy_hold={_percent(baseline)}"
        )
        for label, selectivity in CONFIGS:
            request = replace(
                base_request,
                adaptive_params=AdaptiveEmaParams(
                    base_period=args.period,
                    er_period=cfg.adaptive_er_period,
                    selectivity=selectivity,
                    slope_lookback=cfg.adaptive_slope_lookback,
                    enter_trend_er=cfg.enter_trend_er,
                    exit_trend_er=cfg.exit_trend_er,
                    donchian_period=cfg.donchian_period,
                    bb_period=cfg.bb_period,
                    bb_k=cfg.bb_k,
                ),
            )
            report = engine.run(request, oos_bars)
            value = _oos_return(report.ending_balance, cfg.starting_equity)
            returns[label].append(value)
            metrics = report.metrics
            notional = metrics.traded_notional if metrics is not None else Decimal("0")
            breakeven = metrics.breakeven_cost if metrics is not None else None
            breakeven_bps = "n/a" if breakeven is None else f"{breakeven * 10000:+.2f}"
            print(
                f"    {label:<36} return={_percent(value)} fills={report.fills} "
                f"notional={notional:.0f} breakeven_bps={breakeven_bps}"
            )

    print("  out-of-sample aggregate")
    for label, _ in CONFIGS:
        values = [value for value in returns[label] if value is not None]
        if not values:
            print(f"    {label:<36} n/a")
            continue
        mean = sum(values, Decimal("0")) / Decimal(len(values))
        best = max(values)
        worst = min(values)
        profitable = sum(1 for value in values if value > 0)
        print(
            f"    {label:<36} mean={_percent(mean)} profitable={profitable}/{len(values)} "
            f"worst={_percent(worst)} best={_percent(best)}"
        )
    control = [value for value in returns[CONFIGS[0][0]] if value is not None]
    for label, _ in CONFIGS[1:]:
        values = [value for value in returns[label] if value is not None]
        if len(values) != len(control) or not values:
            continue
        deltas = [value - base for value, base in zip(values, control, strict=True)]
        mean_delta = sum(deltas, Decimal("0")) / Decimal(len(deltas))
        print(
            f"    paired delta {label} vs control: mean={_percent(mean_delta)} "
            f"per_fold={[_percent(delta) for delta in deltas]}"
        )


if __name__ == "__main__":
    main()
