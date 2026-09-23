from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal

from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    BarFeed,
    OrderBookFeed,
    OverfitAuditReport,
    OverfitAuditRequest,
    ResearchBacktestPort,
    TickFeed,
    apply_selected,
    index_of_best_configuration,
)
from nautilus_lab.application.param_grid import iter_param_grid
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.application.run_research_backtest import minimum_bars
from nautilus_lab.domain.align import align_bars_inner_join
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.deflated_sharpe import (
    DeflatedSharpeResult,
    deflated_sharpe_ratio,
    sharpe_ratio,
)
from nautilus_lab.domain.overfitting import probability_of_backtest_overfitting
from nautilus_lab.domain.regime import RobotName, require_backtest_support

# Runs one already-parameterised configuration on one block, by block index.
BlockRunner = Callable[[BacktestRequest, int], BacktestReport]


class RunOverfitAudit:
    """Score the whole parameter grid on every history block, then estimate PBO.

    The audit answers one question the walk-forward report cannot: is the
    configuration this project selects on one stretch of history still good on a
    stretch it was not chosen on? `RunWalkForward` reports a single winner and a
    single out-of-sample number, so a grid can look productive while its ranking is
    pure noise. CSCV makes that visible as one probability.
    """

    def __init__(
        self,
        engine: ResearchBacktestPort,
        feed: BarFeed,
        tick_feed: TickFeed | None = None,
        book_feed: OrderBookFeed | None = None,
    ) -> None:
        self._engine = engine
        self._feed = feed
        self._tick_feed = tick_feed
        self._book_feed = book_feed

    def execute(self, request: OverfitAuditRequest) -> OverfitAuditReport:
        require_simulated_mode(request.backtest.mode)
        require_backtest_support(request.backtest.robot)
        if request.backtest.robot is RobotName.PAIRS:
            return self._execute_pairs(request)
        return self._execute_single(request)

    def _execute_single(self, request: OverfitAuditRequest) -> OverfitAuditReport:
        bars = self._feed.load(request.backtest)
        ranges = _block_ranges(len(bars), request.blocks)
        blocks: tuple[tuple[OhlcvBar, ...], ...] = tuple(
            tuple(bars[start:end]) for start, end in ranges
        )
        _require_warmup(request.backtest.robot, blocks)

        ticks = None
        if request.backtest.use_tick_vpin or request.backtest.use_hawkes:
            if self._tick_feed is None:
                raise ValueError("Tick feed must be provided to use tick_vpin or hawkes")
            ticks = self._tick_feed.load(request.backtest)

        # `ml_obi` cannot score a block without order books, and passing `None` would
        # silently audit a different strategy than the one being reported on.
        books = None
        if request.backtest.robot is RobotName.ML_OBI:
            if self._book_feed is None:
                raise ValueError("OrderBook feed must be provided to use ML_OBI")
            books = self._book_feed.load(request.backtest)

        def run(candidate: BacktestRequest, block_index: int) -> BacktestReport:
            return self._engine.run(candidate, list(blocks[block_index]), ticks, books)

        return self._audit(request, run, len(blocks))

    def _execute_pairs(self, request: OverfitAuditRequest) -> OverfitAuditReport:
        all_bars = self._feed.load_multi(request.backtest)
        aligned = align_bars_inner_join(all_bars)
        leg_a = request.backtest.pairs.leg_a
        ranges = _block_ranges(len(aligned[leg_a]), request.blocks)
        # Every leg is cut on the same row indices, otherwise the two series inside a
        # block would describe different time ranges and the spread would be built
        # from misaligned bars.
        sliced: dict[str, list[list[OhlcvBar]]] = {
            instrument_id: [list(series[start:end]) for start, end in ranges]
            for instrument_id, series in aligned.items()
        }
        _require_warmup(
            request.backtest.robot,
            tuple(tuple(sliced[leg_a][index]) for index in range(len(ranges))),
        )

        def run(candidate: BacktestRequest, block_index: int) -> BacktestReport:
            return self._engine.run_spread(
                candidate,
                {instrument_id: blocks[block_index] for instrument_id, blocks in sliced.items()},
            )

        return self._audit(request, run, len(ranges))

    def _audit(
        self,
        request: OverfitAuditRequest,
        run: BlockRunner,
        block_count: int,
    ) -> OverfitAuditReport:
        candidates = list(iter_param_grid(request.backtest))
        labels = tuple(candidate.label() for candidate in candidates)
        matrix: list[tuple[Decimal | None, ...]] = []
        for block_index in range(block_count):
            row: list[Decimal | None] = []
            for candidate in candidates:
                resolved = apply_selected(request.backtest, candidate)
                report = run(resolved, block_index)
                row.append(_return_fraction(report, request.backtest.starting_equity))
            matrix.append(tuple(row))
        return _report(request, labels, tuple(matrix), block_count)


def _return_fraction(report: BacktestReport, starting_equity: Decimal) -> Decimal | None:
    if report.ending_balance is None or starting_equity <= 0:
        return None
    return (report.ending_balance - starting_equity) / starting_equity


def _block_ranges(total: int, blocks: int) -> tuple[tuple[int, int], ...]:
    size = total // blocks
    if size < 1:
        raise ValueError(f"{total} bars cannot fill {blocks} blocks")
    ranges = [(index * size, (index + 1) * size) for index in range(blocks)]
    # The final block absorbs the integer-division remainder so no bar is dropped.
    last_start, _ = ranges[-1]
    ranges[-1] = (last_start, total)
    return tuple(ranges)


def _require_warmup(robot: RobotName, blocks: Sequence[Sequence[OhlcvBar]]) -> None:
    minimum = minimum_bars(robot)
    for index, block in enumerate(blocks):
        if len(block) < minimum:
            raise ValueError(
                f"block {index} holds {len(block)} bars but {robot.value} needs >= {minimum} "
                "so its indicators can warm up; use fewer blocks or more history"
            )


def _report(
    request: OverfitAuditRequest,
    labels: tuple[str, ...],
    matrix: tuple[tuple[Decimal | None, ...], ...],
    block_count: int,
) -> OverfitAuditReport:
    return audit_from_matrix(labels, matrix, block_count)


def audit_from_matrix(
    labels: tuple[str, ...],
    matrix: tuple[tuple[Decimal | None, ...], ...],
    block_count: int,
) -> OverfitAuditReport:
    """PBO + DSR from a `blocks x configurations` return matrix, whoever produced it."""
    numeric = _numeric_matrix(matrix)
    result = probability_of_backtest_overfitting(numeric)
    best = labels[index_of_best_configuration(matrix)]
    deflated = deflated_sharpe_for_winner(numeric, matrix)
    return OverfitAuditReport(
        pbo=result.pbo,
        split_count=result.split_count,
        configuration_count=result.configuration_count,
        blocks=block_count,
        block_returns=matrix,
        labels=labels,
        deflated_sharpe=deflated,
        notes=(
            f"PBO/CSCV over {block_count} contiguous blocks: {result.split_count} symmetric "
            "splits, parameters re-selected on each train half and ranked on the test half. "
            "A PBO near 0.5 means the in-sample winner is a coin flip; above 0.5 means the "
            f"selection actively hurts. Best mean block score: {best}. Every block is "
            "simulated from a flat start, so each one loses its own warm-up bars. "
            f"{deflated.summary_line()} — DSR asks a different question than PBO: whether the "
            f"winner's Sharpe is more than the best of {result.configuration_count} coin-flip "
            f"trials, judged on {block_count} block returns (see --pbo-blocks for a wider "
            "sample), and it never certifies profitability."
        ),
    )


def deflated_sharpe_for_winner(
    numeric: tuple[tuple[Decimal, ...], ...],
    matrix: tuple[tuple[Decimal | None, ...], ...],
) -> DeflatedSharpeResult:
    """Deflate the winning configuration's Sharpe on the PBO score matrix.

    One observation per block, one trial per grid configuration — the same evidence PBO
    ranks. A configuration whose block returns have zero variance gets a Sharpe of zero
    rather than being dropped from the trial set: the number of things that were tried is
    a fact about the search, not about how well each attempt happened to score, and
    shrinking it would flatter the winner.
    """
    columns = tuple(zip(*numeric, strict=True))
    trial_sharpes: list[Decimal] = []
    for column in columns:
        value = sharpe_ratio(column)
        trial_sharpes.append(Decimal("0") if value is None else value)
    winner = index_of_best_configuration(matrix)
    return deflated_sharpe_ratio(columns[winner], trial_sharpes)


def _numeric_matrix(
    matrix: tuple[tuple[Decimal | None, ...], ...],
) -> tuple[tuple[Decimal, ...], ...]:
    """A missing balance is scored worst, not dropped.

    `backtest_runner` returns `ending_balance=None` when the account report is empty.
    Substituting a floor keeps the matrix rectangular, so every configuration is
    ranked on identical evidence instead of one column quietly shortening.
    """
    if not matrix:
        raise ValueError("score matrix is empty")
    known = [value for row in matrix for value in row if value is not None]
    worst = min([*known, Decimal("-1")])
    return tuple(tuple(worst if value is None else value for value in row) for row in matrix)
