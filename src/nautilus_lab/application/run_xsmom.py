"""Walk-forward and overfitting audit for the cross-sectional momentum robot.

Same protocol as the single-instrument robots, so its numbers are comparable and the
promotion gate can read them:

* rolling folds (`domain.walk_forward.rolling_windows`) — parameters are re-selected
  on each fold's in-sample block and reported on the block after it, never re-read;
* the out-of-sample run is warmed on the bars right before its window and trades from
  the window's first bar only;
* the baseline is the equal-weight buy&hold of the same basket over the same bars —
  rotating between coins only adds value if it beats simply holding all of them;
* the audit (PBO/CSCV + DSR) scores every grid configuration on contiguous blocks.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from itertools import product

from nautilus_lab.application.dtos import OverfitAuditReport
from nautilus_lab.application.run_overfitting_audit import audit_from_matrix
from nautilus_lab.application.score import in_sample_score
from nautilus_lab.application.xsmom_backtest import (
    DEFAULT_SLIPPAGE,
    XsMomRun,
    require_aligned,
    run_xsmom,
)
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.fees import FeeSchedule
from nautilus_lab.domain.metrics import SelectionMetric
from nautilus_lab.domain.walk_forward import WalkForwardWindow, bars_in_range, rolling_windows
from nautilus_lab.domain.windowing import warmup_tail
from nautilus_lab.domain.xsmom import Weighting, XsMomParams


@dataclass(frozen=True, slots=True)
class XsMomGrid:
    """Small on purpose: every extra configuration is one more trial DSR must discount."""

    lookback_bars: tuple[int, ...] = (14, 30, 60)
    top_n: tuple[int, ...] = (2, 3)
    rebalance_every: tuple[int, ...] = (7,)
    skip_bars: int = 1
    require_positive: bool = True
    weighting: Weighting = Weighting.EQUAL

    def candidates(self) -> tuple[XsMomParams, ...]:
        return tuple(
            XsMomParams(
                lookback_bars=lookback,
                skip_bars=self.skip_bars,
                top_n=top_n,
                rebalance_every=rebalance,
                require_positive=self.require_positive,
                weighting=self.weighting,
            )
            for lookback, top_n, rebalance in product(
                self.lookback_bars, self.top_n, self.rebalance_every
            )
        )


@dataclass(frozen=True, slots=True)
class XsMomRequest:
    starting_equity: Decimal = Decimal("100000")
    fees: FeeSchedule = field(default_factory=FeeSchedule.binance_spot_vip0)
    slippage: Decimal = DEFAULT_SLIPPAGE
    grid: XsMomGrid = field(default_factory=XsMomGrid)
    folds: int = 6
    in_sample_fraction: Decimal = Decimal("0.5")
    embargo_bars: int = 0
    selection_metric: SelectionMetric = SelectionMetric.CALMAR
    periods_per_year: int | None = None
    pbo_blocks: int = 8


@dataclass(frozen=True, slots=True)
class XsMomFold:
    index: int
    window: WalkForwardWindow
    selected: XsMomParams
    in_sample: XsMomRun
    out_of_sample: XsMomRun

    @property
    def oos_return(self) -> Decimal:
        return self.out_of_sample.return_fraction

    @property
    def buy_and_hold_return(self) -> Decimal | None:
        return self.out_of_sample.basket_return


@dataclass(frozen=True, slots=True)
class XsMomWalkForwardReport:
    """Mirrors the `MultiWindowReport` surface the promotion gate reads."""

    folds: tuple[XsMomFold, ...]
    symbols: tuple[str, ...]

    @property
    def oos_returns(self) -> tuple[Decimal, ...]:
        return tuple(fold.oos_return for fold in self.folds)

    @property
    def profitable_folds(self) -> int:
        return sum(1 for value in self.oos_returns if value > 0)

    @property
    def mean_oos_return(self) -> Decimal | None:
        values = self.oos_returns
        return sum(values, Decimal("0")) / Decimal(len(values)) if values else None

    @property
    def median_oos_return(self) -> Decimal | None:
        values = self.oos_returns
        return statistics.median(values) if values else None

    @property
    def mean_buy_and_hold_return(self) -> Decimal | None:
        values = [f.buy_and_hold_return for f in self.folds if f.buy_and_hold_return is not None]
        return sum(values, Decimal("0")) / Decimal(len(values)) if values else None

    @property
    def total_oos_fills(self) -> int:
        return sum(fold.out_of_sample.trades for fold in self.folds)

    def beats_buy_and_hold(self) -> bool | None:
        robot, basket = self.mean_oos_return, self.mean_buy_and_hold_return
        if robot is None or basket is None:
            return None
        return robot > basket

    def summary_line(self) -> str:
        def percent(value: Decimal | None) -> str:
            return "n/a" if value is None else f"{value * 100:.2f}%"

        verdict = self.beats_buy_and_hold()
        comparison = (
            "n/a" if verdict is None else "beats basket" if verdict else "does not beat basket"
        )
        return (
            f"xsmom symbols={','.join(self.symbols)} folds={len(self.folds)} "
            f"profitable={self.profitable_folds}/{len(self.folds)} "
            f"mean_oos={percent(self.mean_oos_return)} "
            f"median_oos={percent(self.median_oos_return)} "
            f"mean_basket={percent(self.mean_buy_and_hold_return)} ({comparison}) "
            f"oos_trades={self.total_oos_fills}"
        )


def _slice(
    bars_by_symbol: Mapping[str, Sequence[OhlcvBar]],
    reference: Sequence[OhlcvBar],
) -> dict[str, list[OhlcvBar]]:
    stamps = {bar.ts_utc for bar in reference}
    return {s: [bar for bar in bars if bar.ts_utc in stamps] for s, bars in bars_by_symbol.items()}


def _run(
    request: XsMomRequest,
    bars: Mapping[str, Sequence[OhlcvBar]],
    params: XsMomParams,
    trade_start: datetime | None = None,
) -> XsMomRun:
    return run_xsmom(
        bars,
        params,
        starting_equity=request.starting_equity,
        fees=request.fees,
        slippage=request.slippage,
        trade_start=trade_start,
        periods_per_year=request.periods_per_year,
    )


def _score(request: XsMomRequest, run: XsMomRun) -> Decimal:
    return in_sample_score(
        run.as_backtest_report(),
        metric=request.selection_metric,
        starting_equity=request.starting_equity,
    )


def run_xsmom_walk_forward(
    bars_by_symbol: Mapping[str, Sequence[OhlcvBar]], request: XsMomRequest
) -> XsMomWalkForwardReport:
    symbols = require_aligned(bars_by_symbol)
    reference = list(bars_by_symbol[symbols[0]])
    candidates = request.grid.candidates()
    warmup = max(params.warmup_bars for params in candidates)
    windows = rolling_windows(
        reference,
        folds=request.folds,
        in_sample_fraction=request.in_sample_fraction,
        embargo_bars=request.embargo_bars,
    )
    folds: list[XsMomFold] = []
    for index, window in enumerate(windows):
        is_ref = bars_in_range(reference, start=window.in_sample_start, end=window.in_sample_end)
        oos_ref = bars_in_range(
            reference, start=window.out_of_sample_start, end=window.out_of_sample_end
        )
        if len(is_ref) <= warmup or not oos_ref:
            raise ValueError(
                f"fold {index}: {len(is_ref)} in-sample bars cannot warm a {warmup}-bar "
                "lookback; load more history or use fewer folds"
            )
        in_sample = _slice(bars_by_symbol, is_ref)
        best: tuple[Decimal, XsMomParams, XsMomRun] | None = None
        for params in candidates:
            run = _run(request, in_sample, params)
            score = _score(request, run)
            if best is None or score > best[0]:
                best = (score, params, run)
        if best is None:  # candidates is never empty; say so if that ever changes
            raise RuntimeError("xsmom selection saw no candidate configuration")
        _, selected, is_run = best

        warm_ref = warmup_tail(reference, oos_ref, warmup)
        oos_bars = _slice(bars_by_symbol, [*warm_ref, *oos_ref])
        oos_run = _run(request, oos_bars, selected, trade_start=oos_ref[0].ts_utc)
        folds.append(
            XsMomFold(
                index=index,
                window=window,
                selected=selected,
                in_sample=is_run,
                out_of_sample=oos_run,
            )
        )
    return XsMomWalkForwardReport(folds=tuple(folds), symbols=symbols)


def run_xsmom_audit(
    bars_by_symbol: Mapping[str, Sequence[OhlcvBar]], request: XsMomRequest
) -> OverfitAuditReport:
    """PBO/CSCV + DSR over contiguous blocks, each block warmed on the bars before it."""
    symbols = require_aligned(bars_by_symbol)
    reference = list(bars_by_symbol[symbols[0]])
    candidates = request.grid.candidates()
    warmup = max(params.warmup_bars for params in candidates)
    blocks = request.pbo_blocks
    size = len(reference) // blocks
    if size < 2:
        raise ValueError(f"{len(reference)} bars cannot fill {blocks} blocks")
    matrix: list[tuple[Decimal | None, ...]] = []
    for block in range(blocks):
        start = block * size
        end = len(reference) if block == blocks - 1 else (block + 1) * size
        block_ref = reference[start:end]
        warm = warmup_tail(reference, block_ref, warmup)
        bars = _slice(bars_by_symbol, [*warm, *block_ref])
        row = tuple(
            _run(request, bars, params, trade_start=block_ref[0].ts_utc).return_fraction
            for params in candidates
        )
        matrix.append(row)
    labels = tuple(params.label() for params in candidates)
    return audit_from_matrix(labels, tuple(matrix), blocks)
