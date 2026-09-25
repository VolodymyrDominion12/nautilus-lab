"""Choose a robot's parameters on in-sample bars, then stop looking.

A paper session runs a frozen configuration forward, so *something* has to decide
what that configuration is. Defaults are not a decision: `vpin_momentum` and
`formulaic_lgbm` ship with defaults whose gates never open, so a paper session on
defaults shows `fills=0` and looks broken while actually being unconfigured.

This module does the choosing under the project's one non-negotiable rule: the
selection window must end before the session window begins, with an embargo gap
between them. Nothing here reads a bar from the holdout, and the returned DTO carries
the window it was fitted on so the report can say so out loud.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    BarFeed,
    FundingFeed,
    OrderBookFeed,
    ResearchBacktestPort,
    SelectedParams,
    TickFeed,
    apply_selected,
    selected_from_request,
)
from nautilus_lab.application.param_grid import iter_param_grid
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.application.score import in_sample_score
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.regime import RobotName, require_backtest_support


@dataclass(frozen=True, slots=True)
class ParamSelection:
    """The winner of an in-sample grid, and the evidence it was fitted on.

    `holdout_bars` and `embargo_bars` are carried so a caller can assert that the
    selection window and the session window really are disjoint — the one property
    that makes the selection legitimate.
    """

    params: SelectedParams
    tried: int
    in_sample_bars: int
    holdout_bars: int
    embargo_bars: int
    in_sample_start: datetime | None
    in_sample_end: datetime | None
    in_sample_return: Decimal | None
    notes: str

    def summary_line(self) -> str:
        def percent(value: Decimal | None) -> str:
            return "n/a" if value is None else f"{value * 100:.2f}%"

        return (
            f"parameters selected on in-sample only: tried={self.tried} "
            f"is_bars={self.in_sample_bars} holdout_bars={self.holdout_bars} "
            f"embargo_bars={self.embargo_bars} is_return={percent(self.in_sample_return)} "
            f"selected={self.params.label()}"
        )


class RunParamSelection:
    """Grid-search a robot's parameters on the bars that precede the session window."""

    def __init__(
        self,
        engine: ResearchBacktestPort,
        feed: BarFeed,
        tick_feed: TickFeed | None = None,
        book_feed: OrderBookFeed | None = None,
        funding_feed: FundingFeed | None = None,
    ) -> None:
        self._engine = engine
        self._feed = feed
        self._tick_feed = tick_feed
        self._book_feed = book_feed
        self._funding_feed = funding_feed

    def execute(
        self,
        request: BacktestRequest,
        *,
        holdout_bars: int,
        embargo_bars: int,
    ) -> ParamSelection:
        require_simulated_mode(request.mode)
        require_backtest_support(request.robot)
        if holdout_bars < 1:
            raise ValueError("holdout_bars must be >= 1 to leave a session window")
        if embargo_bars < 0:
            raise ValueError("embargo_bars must be >= 0")

        if request.robot in (RobotName.PAIRS, RobotName.FUNDING):
            return self._select_pairs(request, holdout_bars=holdout_bars, embargo_bars=embargo_bars)
        return self._select_single(request, holdout_bars=holdout_bars, embargo_bars=embargo_bars)

    def _select_single(
        self,
        request: BacktestRequest,
        *,
        holdout_bars: int,
        embargo_bars: int,
    ) -> ParamSelection:
        bars = self._feed.load(request)
        in_sample = _in_sample_slice(bars, holdout_bars=holdout_bars, embargo_bars=embargo_bars)

        ticks = None
        if request.use_tick_vpin or request.use_hawkes:
            if self._tick_feed is None:
                raise ValueError("Tick feed must be provided to use tick_vpin or hawkes")
            ticks = self._tick_feed.load(request)

        books = None
        if request.robot is RobotName.ML_OBI:
            if self._book_feed is None:
                raise ValueError("OrderBook feed must be provided to use ML_OBI")
            # Only the in-sample part of the book series may be shown to the selection.
            end = in_sample[-1].ts_utc if in_sample else None
            books = [
                snapshot
                for snapshot in self._book_feed.load(request)
                if end is None or snapshot.ts_utc <= end
            ]

        return self._grid(
            request,
            in_sample,
            lambda candidate: self._engine.run(candidate, in_sample, ticks, books),
            holdout_bars=holdout_bars,
            embargo_bars=embargo_bars,
        )

    def _select_pairs(
        self,
        request: BacktestRequest,
        *,
        holdout_bars: int,
        embargo_bars: int,
    ) -> ParamSelection:
        multi = self._feed.load_multi(request)
        ref = (
            (request.funding_spot_id or "ETH/USDT.SIM")
            if request.robot is RobotName.FUNDING
            else request.pairs.leg_a
        )
        reference = list(multi[ref])
        cut = _in_sample_cut(len(reference), holdout_bars=holdout_bars, embargo_bars=embargo_bars)
        # Both legs are cut on the same row indices: they arrive aligned by an inner
        # join, so identical cuts keep the spread built from contemporaneous bars.
        in_sample = {key: list(value[:cut]) for key, value in multi.items()}
        in_sample_ref = in_sample[ref]
        funding = self._funding_feed.load(request) if self._funding_feed is not None else None

        return self._grid(
            request,
            in_sample_ref,
            lambda candidate: self._engine.run_spread(candidate, in_sample, funding=funding),
            holdout_bars=holdout_bars,
            embargo_bars=embargo_bars,
        )

    def _grid(
        self,
        request: BacktestRequest,
        in_sample: list[OhlcvBar],
        run_is: Callable[[BacktestRequest], BacktestReport],
        *,
        holdout_bars: int,
        embargo_bars: int,
    ) -> ParamSelection:
        if not in_sample:
            raise ValueError(
                "in-sample window is empty: holdout_bars plus embargo_bars "
                "leave no bars to select on"
            )

        best_params = selected_from_request(request)
        best_report: BacktestReport | None = None
        best_score: Decimal | None = None
        tried = 0
        for candidate_params in iter_param_grid(request):
            tried += 1
            report = run_is(apply_selected(request, candidate_params))
            score = in_sample_score(
                report,
                metric=request.selection_metric,
                starting_equity=request.starting_equity,
            )
            if best_report is None or best_score is None or score > best_score:
                best_score = score
                best_params = candidate_params
                best_report = report
        if best_report is None:
            raise ValueError("parameter grid is empty")

        return ParamSelection(
            params=best_params,
            tried=tried,
            in_sample_bars=len(in_sample),
            holdout_bars=holdout_bars,
            embargo_bars=embargo_bars,
            in_sample_start=in_sample[0].ts_utc,
            in_sample_end=in_sample[-1].ts_utc,
            in_sample_return=_return_fraction(best_report, request.starting_equity),
            notes=(
                f"grid selection on in-sample only ({len(in_sample)} bars, "
                f"embargo={embargo_bars}); the session window and its "
                f"{holdout_bars} bars were never read here"
            ),
        )


def _in_sample_cut(total: int, *, holdout_bars: int, embargo_bars: int) -> int:
    """Row index where the in-sample window ends: holdout plus embargo are excluded."""
    cut = total - holdout_bars - embargo_bars
    if cut < 0:
        raise ValueError(
            f"history has {total} bars; holdout_bars={holdout_bars} plus "
            f"embargo_bars={embargo_bars} do not fit"
        )
    return cut


def _in_sample_slice(
    bars: list[OhlcvBar],
    *,
    holdout_bars: int,
    embargo_bars: int,
) -> list[OhlcvBar]:
    return list(
        bars[: _in_sample_cut(len(bars), holdout_bars=holdout_bars, embargo_bars=embargo_bars)]
    )


def _return_fraction(report: BacktestReport, starting_equity: Decimal) -> Decimal | None:
    if report.ending_balance is None or starting_equity <= 0:
        return None
    return (report.ending_balance - starting_equity) / starting_equity
