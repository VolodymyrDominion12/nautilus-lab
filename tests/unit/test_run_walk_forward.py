from datetime import datetime
from decimal import Decimal

import pytest

from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    WalkForwardRequest,
    selected_from_request,
)
from nautilus_lab.application.run_walk_forward import RunWalkForward
from nautilus_lab.application.score import in_sample_score
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.errors import InvalidWindowError
from nautilus_lab.domain.order_book import OrderBookSnapshot
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.ticks import AggTrade
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.domain.walk_forward import WalkForwardWindow
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_ohlcv


def _limits() -> RiskLimits:
    return RiskLimits(
        risk_per_trade=Decimal("0.005"),
        stop_pct=Decimal("0.01"),
        max_daily_loss=Decimal("0.02"),
        max_drawdown=Decimal("0.06"),
    )


def test_walk_forward_selects_on_in_sample_and_reports_out_of_sample() -> None:
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=200, seed=3)
    is_start = bars[0].ts_utc

    class RecordingEngine:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int, datetime, int]] = []

        def run(
            self,
            request: BacktestRequest,
            folded: list[OhlcvBar],
            ticks: list[AggTrade] | None = None,
            books: list[OrderBookSnapshot] | None = None,
        ) -> BacktestReport:
            self.calls.append((request.fast_ema, request.slow_ema, folded[0].ts_utc, len(folded)))
            in_sample = folded[0].ts_utc == is_start
            if request.fast_ema == 5:
                balance = Decimal("120000") if in_sample else Decimal("90000")
            elif request.fast_ema == 10 and request.slow_ema == 20:
                balance = Decimal("110000") if in_sample else Decimal("105000")
            else:
                balance = Decimal("100000")
            return BacktestReport(fills=1, positions=1, ending_balance=balance, notes="fake")

        def run_spread(
            self,
            request: BacktestRequest,
            bars_by_instrument: dict[str, list[OhlcvBar]],
            *args: object,
            **kwargs: object,
        ) -> BacktestReport:
            raise AssertionError("spread engine must not run")

    class FixedFeed:
        def load(self, request: BacktestRequest) -> list[OhlcvBar]:
            return bars

        def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
            return {request.instrument_id: bars}

    engine = RecordingEngine()
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=200,
        starting_equity=Decimal("100000"),
        risk=_limits(),
        robot=RobotName.EMA,
        fast_ema=10,
        slow_ema=20,
    )
    report = RunWalkForward(engine, FixedFeed()).execute(WalkForwardRequest(backtest=request))

    assert report.selected.fast_ema == 5
    assert report.selected.slow_ema == 20
    assert report.in_sample.ending_balance == Decimal("120000")
    assert report.out_of_sample.ending_balance == Decimal("90000")
    assert report.candidates_tried == 4
    assert "out-of-sample" in report.notes
    last = engine.calls[-1]
    assert last[0] == 5
    assert last[1] == 20
    assert last[2] != is_start


def test_in_sample_score_ranks_missing_balance_last() -> None:
    missing = BacktestReport(fills=0, positions=0, ending_balance=None, notes="")
    present = BacktestReport(fills=0, positions=0, ending_balance=Decimal("1"), notes="")
    assert in_sample_score(missing) < in_sample_score(present)


def test_selected_from_request_copies_regime_fields() -> None:
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=200,
        starting_equity=Decimal("100000"),
        risk=_limits(),
    )
    selected = selected_from_request(request)
    assert selected.donchian_period == request.regime.donchian_period
    assert selected.bb_k == request.regime.bb_k


# --- multi-window ------------------------------------------------------------------


def _balance_for(bars_slice: list[OhlcvBar]) -> Decimal:
    """Balance keyed to the window's first bar, so each fold gets a distinct result."""
    return Decimal("100000") + Decimal(bars_slice[0].ts_utc.toordinal() % 100)


class _WindowEngine:
    def __init__(self) -> None:
        self.calls = 0

    def run(
        self,
        request: BacktestRequest,
        folded: list[OhlcvBar],
        ticks: list[AggTrade] | None = None,
        books: list[OrderBookSnapshot] | None = None,
    ) -> BacktestReport:
        self.calls += 1
        return BacktestReport(
            fills=len(folded),
            positions=1,
            ending_balance=_balance_for(folded),
            notes="fake",
        )

    def run_spread(
        self,
        request: BacktestRequest,
        bars_by_instrument: dict[str, list[OhlcvBar]],
        *args: object,
        **kwargs: object,
    ) -> BacktestReport:
        raise AssertionError("spread engine must not run")


class _SingleSeriesFeed:
    def __init__(self, bars: list[OhlcvBar]) -> None:
        self._bars = bars

    def load(self, request: BacktestRequest) -> list[OhlcvBar]:
        return self._bars

    def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
        return {request.instrument_id: self._bars}


def _multi_request(bars: list[OhlcvBar], *, folds: int = 3) -> WalkForwardRequest:
    return WalkForwardRequest(
        backtest=BacktestRequest(
            mode=TradingMode.RESEARCH,
            instrument_id="ETH/USDT.SIM",
            bar_count=len(bars),
            starting_equity=Decimal("100000"),
            risk=_limits(),
            robot=RobotName.EMA,
            source=BarOrigin.CATALOG,
        ),
        in_sample_fraction=Decimal("0.5"),
        folds=folds,
    )


def test_execute_multi_runs_one_walk_forward_per_fold_with_sliding_selection() -> None:
    """The point of the feature: each fold must select on its own in-sample window."""
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=900, seed=5)
    engine = _WindowEngine()
    request = _multi_request(bars)

    report = RunWalkForward(engine, _SingleSeriesFeed(bars)).execute_multi(request)

    assert len(report.folds) == 3
    assert [fold.index for fold in report.folds] == [0, 1, 2]

    in_sample_starts = [fold.window.in_sample_start for fold in report.folds]
    assert in_sample_starts == sorted(in_sample_starts)
    assert len(set(in_sample_starts)) == 3, "folds must not re-read the same selection data"

    out_of_sample_starts = [fold.window.out_of_sample_start for fold in report.folds]
    assert out_of_sample_starts == sorted(out_of_sample_starts)
    for earlier, later in zip(report.folds, report.folds[1:], strict=False):
        assert earlier.window.out_of_sample_end <= later.window.out_of_sample_start

    # Every fold really ran a grid search on its in-sample block, plus one OOS run.
    assert engine.calls == 3 * (report.folds[0].candidates_tried + 1)


def test_execute_multi_derives_returns_and_baseline_per_fold() -> None:
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=900, seed=5)
    engine = _WindowEngine()
    request = _multi_request(bars)

    report = RunWalkForward(engine, _SingleSeriesFeed(bars)).execute_multi(request)

    for fold in report.folds:
        expected = (
            _balance_for([_bar_at(bars, fold.window.out_of_sample_start)]) - Decimal("100000")
        ) / Decimal("100000")
        assert fold.oos_return == expected
        assert fold.buy_and_hold_return is not None
        assert fold.out_of_sample.fills > 0

    assert report.profitable_folds + (len(report.folds) - report.profitable_folds) == 3
    assert report.mean_oos_return is not None
    assert report.median_oos_return is not None
    assert report.mean_buy_and_hold_return is not None
    assert report.total_oos_fills == sum(fold.out_of_sample.fills for fold in report.folds)
    assert "multi-window walk-forward" in report.notes
    assert "mean_oos=" in report.summary_line()


def _bar_at(bars: list[OhlcvBar], ts_utc: datetime) -> OhlcvBar:
    for bar in bars:
        if bar.ts_utc == ts_utc:
            return bar
    raise AssertionError(f"no bar at {ts_utc.isoformat()}")


def test_execute_multi_rejects_a_single_fold() -> None:
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=400, seed=5)
    use_case = RunWalkForward(_WindowEngine(), _SingleSeriesFeed(bars))
    with pytest.raises(ValueError, match="folds >= 2"):
        use_case.execute_multi(_multi_request(bars, folds=1))


def test_execute_multi_rejects_an_explicit_window() -> None:
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=400, seed=5)
    use_case = RunWalkForward(_WindowEngine(), _SingleSeriesFeed(bars))
    request = WalkForwardRequest(
        backtest=_multi_request(bars).backtest,
        window=WalkForwardWindow(
            in_sample_start=bars[0].ts_utc,
            in_sample_end=bars[100].ts_utc,
            out_of_sample_start=bars[100].ts_utc,
            out_of_sample_end=bars[-1].ts_utc,
        ),
        folds=2,
    )
    with pytest.raises(InvalidWindowError, match="derive their own windows"):
        use_case.execute_multi(request)


def test_ml_obi_walk_forward_hands_books_to_every_run_and_loads_them_once() -> None:
    """Before: walk-forward never loaded the book series, so ml_obi could not trade."""
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=600, seed=5)
    received: list[list[OrderBookSnapshot] | None] = []

    class BookEngine(_WindowEngine):
        def run(
            self,
            request: BacktestRequest,
            folded: list[OhlcvBar],
            ticks: list[AggTrade] | None = None,
            books: list[OrderBookSnapshot] | None = None,
        ) -> BacktestReport:
            received.append(books)
            return super().run(request, folded, ticks, books)

    class Feed:
        def load(self, request: BacktestRequest) -> list[OhlcvBar]:
            return bars

        def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
            return {request.instrument_id: bars}

    book_series: list[OrderBookSnapshot] = []

    class BookFeed:
        loads = 0

        def load(self, request: BacktestRequest) -> list[OrderBookSnapshot]:
            BookFeed.loads += 1
            return book_series

    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=600,
        starting_equity=Decimal("100000"),
        risk=_limits(),
        robot=RobotName.ML_OBI,
    )
    use_case = RunWalkForward(BookEngine(), Feed(), book_feed=BookFeed())
    use_case.execute_multi(WalkForwardRequest(backtest=request, folds=2))

    assert received
    assert all(books is book_series for books in received)
    assert BookFeed.loads == 1


def test_ml_obi_walk_forward_without_book_feed_fails_closed() -> None:
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=600, seed=5)

    class Feed:
        def load(self, request: BacktestRequest) -> list[OhlcvBar]:
            return bars

        def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
            return {request.instrument_id: bars}

    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=600,
        starting_equity=Decimal("100000"),
        risk=_limits(),
        robot=RobotName.ML_OBI,
    )
    with pytest.raises(ValueError, match="OrderBook feed"):
        RunWalkForward(_WindowEngine(), Feed()).execute(WalkForwardRequest(backtest=request))


def _recording_run(calls: list[tuple[BacktestRequest, list[OhlcvBar]]]) -> _WindowEngine:
    class Recorder(_WindowEngine):
        def run(
            self,
            request: BacktestRequest,
            folded: list[OhlcvBar],
            ticks: list[AggTrade] | None = None,
            books: list[OrderBookSnapshot] | None = None,
        ) -> BacktestReport:
            calls.append((request, folded))
            return super().run(request, folded, ticks, books)

    return Recorder()


def _ema_request() -> BacktestRequest:
    return BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=400,
        starting_equity=Decimal("100000"),
        risk=_limits(),
        robot=RobotName.EMA,
    )


class _Feed:
    def __init__(self, bars: list[OhlcvBar]) -> None:
        self._bars = bars

    def load(self, request: BacktestRequest) -> list[OhlcvBar]:
        return self._bars

    def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
        return {request.instrument_id: self._bars}


def test_oos_run_is_warmed_on_the_bars_right_before_the_window() -> None:
    """OOS used to start cold and spend its first bars warming indicators."""
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=400, seed=11)
    calls: list[tuple[BacktestRequest, list[OhlcvBar]]] = []
    report = RunWalkForward(_recording_run(calls), _Feed(bars)).execute(
        WalkForwardRequest(backtest=_ema_request())
    )

    oos_request, oos_bars = calls[-1]
    oos_start = report.window.out_of_sample_start
    assert oos_request.trade_start is not None
    assert oos_request.trade_start >= oos_start
    warm = [bar for bar in oos_bars if bar.ts_utc < oos_request.trade_start]
    assert len(warm) == 50  # EMA warm-up minimum
    # In-sample selection runs are never shifted: they trade from their first bar.
    assert all(request.trade_start is None for request, _ in calls[:-1])


def test_oos_warmup_can_be_switched_off() -> None:
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=400, seed=11)
    calls: list[tuple[BacktestRequest, list[OhlcvBar]]] = []
    RunWalkForward(_recording_run(calls), _Feed(bars)).execute(
        WalkForwardRequest(backtest=_ema_request(), oos_warmup_bars=0)
    )
    oos_request, _ = calls[-1]
    assert oos_request.trade_start is None
