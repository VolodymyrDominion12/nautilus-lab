#!/usr/bin/env python
"""Measure the VPIN distribution of a stored aggTrades series.

Reads the tick series out of the catalog and reports what the toxicity gate would
actually see: the distribution of completed-bucket VPIN, and how often it would cross
`VPIN_TOXIC_THRESHOLD`. This is the number behind the verdict that `vpin_momentum`
stands aside at 1h (docs/24 §5.3) — it is reproduced here rather than pasted into a
document, because a threshold that is never reached is exactly the kind of claim that
should be cheap to check.

Usage:
    .venv/bin/python scripts/measure_tick_vpin.py --symbol ETHUSDT
    .venv/bin/python scripts/measure_tick_vpin.py --symbol ETHUSDT --bucket 1000 --threshold 0.7
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from nautilus_lab.domain.ticks import AggTrade
from nautilus_lab.domain.vpin import TickVpin
from nautilus_lab.infrastructure.agg_trades_catalog import ParquetAggTradesCatalog


def percentile(values: Sequence[Decimal], fraction: Decimal) -> Decimal | None:
    """Nearest-rank percentile on a sorted copy. None for an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    rank = int((Decimal(len(ordered)) - 1) * fraction)
    return ordered[rank]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="catalog")
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--bucket", type=int, default=1000, help="VPIN bucket volume (base units)")
    parser.add_argument(
        "--threshold",
        default="0.7",
        help="Toxicity threshold to test against (VPIN_TOXIC_THRESHOLD)",
    )
    args = parser.parse_args(argv)

    catalog = ParquetAggTradesCatalog(Path(args.catalog))
    if not catalog.series_exists(args.symbol):
        print(
            f"no aggTrades series for {args.symbol} in {args.catalog}. "
            "Collect one with 'lab ingest --trades --live-ticks MINUTES'.",
            file=sys.stderr,
        )
        return 1

    trades: list[AggTrade] = catalog.load(symbol=args.symbol)
    if not trades:
        print(f"tick series for {args.symbol} is empty", file=sys.stderr)
        return 1

    threshold = Decimal(str(args.threshold))
    vpin = TickVpin(bucket_volume=Decimal(args.bucket), toxic_threshold=threshold)
    samples: list[Decimal] = []
    toxic = 0
    previous = None
    for trade in trades:
        vpin.update_from_trade(is_buy=trade.is_aggressive_buy, volume=Decimal(trade.qty))
        state = vpin.last
        # `last` keeps the most recent completed bucket, so an unchanged object means
        # the bucket has not closed yet and must not be counted twice.
        if state is None or state is previous:
            continue
        previous = state
        samples.append(state.value)
        if state.toxic:
            toxic += 1

    span = trades[-1].ts_utc - trades[0].ts_utc
    print(f"symbol={args.symbol} trades={len(trades)}")
    print(f"window=[{trades[0].ts_utc.isoformat()}, {trades[-1].ts_utc.isoformat()}] span={span}")
    print(f"bucket_volume={args.bucket} threshold={threshold} completed_buckets={len(samples)}")
    if not samples:
        print("no bucket completed: the bucket volume is larger than the collected flow")
        return 0
    mean = sum(samples, Decimal("0")) / Decimal(len(samples))
    print(
        f"vpin median={percentile(samples, Decimal('0.5'))} "
        f"p90={percentile(samples, Decimal('0.9'))} "
        f"max={max(samples)} mean={mean}"
    )
    share = Decimal(toxic) / Decimal(len(samples))
    print(f"toxic_buckets={toxic}/{len(samples)} share={share * 100:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
