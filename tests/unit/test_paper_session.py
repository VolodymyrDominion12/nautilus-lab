from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from nautilus_lab.application.dtos import (
    BacktestRequest,
    PaperFill,
    PaperPosition,
    PaperSessionReport,
)
from nautilus_lab.application.run_paper import (
    PAPER_SUPPORTED_ROBOTS,
    RunPaperSession,
    require_paper_support,
)
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.errors import RobotNotWiredError
from nautilus_lab.domain.funding import FundingSnapshot
from nautilus_lab.domain.regime import BACKTEST_WIRED_ROBOTS, RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.paper_sessions import append_session, session_record
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.interfaces.composition import research_request

START = datetime(2024, 1, 1, tzinfo=UTC)


def _limits() -> RiskLimits:
    return RiskLimits(
        risk_per_trade=Decimal("0.005"),
        stop_pct=Decimal("0.01"),
        max_daily_loss=Decimal("0.02"),
        max_drawdown=Decimal("0.06"),
    )


def _bars(count: int, instrument_id: str = "ETH/USDT.SIM") -> list[OhlcvBar]:
    return [
        OhlcvBar(
            instrument_id=instrument_id,
            ts_utc=START + timedelta(hours=index),
            open=Decimal("2000"),
            high=Decimal("2010"),
            low=Decimal("1990"),
            close=Decimal("2000") + Decimal(index),
            volume=Decimal("10"),
        )
        for index in range(count)
    ]


def _request(
    robot: RobotName = RobotName.REGIME,
    *,
    bars: int = 200,
    mode: TradingMode = TradingMode.PAPER,
    **overrides: Any,
) -> BacktestRequest:
    cfg = Settings()
    base = research_request(cfg, bar_count=bars, robot=robot, source=BarOrigin.CATALOG)
    return replace(base, mode=mode, **overrides)


class _Feed:
    def __init__(self, bars: list[OhlcvBar]) -> None:
        self._bars = bars
        self.loaded = 0

    def load(self, request: BacktestRequest) -> list[OhlcvBar]:
        self.loaded += 1
        return list(self._bars)

    def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
        self.loaded += 1
        return {request.pairs.leg_a: list(self._bars), request.pairs.leg_b: list(self._bars)}


class _Engine:
    def __init__(self) -> None:
        self.single: tuple[int, int | None, int | None] | None = None
        self.spread: dict[str, int] | None = None
        self.request: BacktestRequest | None = None

    def run_paper(
        self,
        request: BacktestRequest,
        bars: list[OhlcvBar],
        ticks: list[Any] | None = None,
        books: list[Any] | None = None,
    ) -> PaperSessionReport:
        self.request = request
        self.single = (
            len(bars),
            None if ticks is None else len(ticks),
            None if books is None else len(books),
        )
        return _report(request, bars)

    def run_paper_spread(
        self,
        request: BacktestRequest,
        bars_by_instrument: dict[str, list[OhlcvBar]],
        funding: list[FundingSnapshot] | None = None,
    ) -> PaperSessionReport:
        self.spread = {key: len(value) for key, value in bars_by_instrument.items()}
        leg_a = bars_by_instrument[request.pairs.leg_a]
        return _report(request, leg_a)


def _report(request: BacktestRequest, bars: list[OhlcvBar]) -> PaperSessionReport:
    return PaperSessionReport(
        robot=request.robot,
        instrument_id=request.instrument_id,
        source=request.source.value,
        mode=request.mode,
        bar_count=len(bars),
        window_start=bars[0].ts_utc if bars else None,
        window_end=bars[-1].ts_utc if bars else None,
        starting_equity=request.starting_equity,
        ending_equity=request.starting_equity,
    )


# --- session wiring ---


def test_paper_session_window_is_the_most_recent_bars_not_the_whole_catalog() -> None:
    """`--bars` bounds the session: a rehearsal runs the tail, not the full history."""
    feed = _Feed(_bars(500))
    engine = _Engine()
    use_case = RunPaperSession(engine, feed)

    use_case.execute(_request(bars=200))

    assert engine.single is not None
    # 200 traded bars, plus the regime robot's 150 warm-up bars right before them.
    assert engine.single[0] == 350
    assert engine.request is not None
    assert engine.request.trade_start == feed._bars[-200].ts_utc


def test_paper_session_refuses_live_mode() -> None:
    use_case = RunPaperSession(_Engine(), _Feed(_bars(200)))
    with pytest.raises(Exception, match="Live trading is disabled"):
        use_case.execute(_request(mode=TradingMode.LIVE))


def test_paper_session_refuses_a_shorter_window_than_warmup() -> None:
    use_case = RunPaperSession(_Engine(), _Feed(_bars(200)))
    with pytest.raises(ValueError, match="warm up"):
        use_case.execute(_request(bars=10))


def test_paper_supported_set_is_exactly_the_wired_set() -> None:
    """Every wired robot must be runnable in paper, and nothing else may claim to be."""
    assert PAPER_SUPPORTED_ROBOTS == BACKTEST_WIRED_ROBOTS
    for robot in BACKTEST_WIRED_ROBOTS:
        require_paper_support(robot)


def test_paper_refuses_robots_without_an_adapter() -> None:
    for robot in (RobotName.GLFT, RobotName.TRI_SCAN):
        with pytest.raises(RobotNotWiredError):
            require_paper_support(robot)


def test_paper_session_routes_pairs_to_the_spread_engine() -> None:
    feed = _Feed(_bars(400))
    engine = _Engine()
    use_case = RunPaperSession(engine, feed)

    use_case.execute(_request(RobotName.PAIRS, bars=300))

    assert engine.spread is not None
    assert set(engine.spread.values()) == {300}
    assert engine.single is None


def test_paper_session_requires_a_book_feed_for_ml_obi() -> None:
    use_case = RunPaperSession(_Engine(), _Feed(_bars(200)))
    with pytest.raises(ValueError, match="OrderBook feed"):
        use_case.execute(_request(RobotName.ML_OBI))


def test_paper_session_requires_a_tick_feed_for_tick_filters() -> None:
    use_case = RunPaperSession(_Engine(), _Feed(_bars(200)))
    with pytest.raises(ValueError, match="Tick feed"):
        use_case.execute(_request(use_tick_vpin=True))


# --- report arithmetic ---


def test_net_pnl_marks_an_open_position_and_keeps_realized_separate() -> None:
    fill = PaperFill(
        ts_utc=START,
        instrument_id="ETH/USDT.SIM",
        side="BUY",
        qty=Decimal("2"),
        price=Decimal("2000"),
        commission=Decimal("4"),
        liquidity="TAKER",
        is_reduce_only=False,
    )
    closed = PaperPosition(
        instrument_id="ETH/USDT.SIM",
        side="LONG",
        qty=Decimal("1"),
        entry_price=Decimal("2000"),
        opened_utc=START,
        exit_price=Decimal("2100"),
        closed_utc=START + timedelta(hours=1),
        realized_pnl=Decimal("100"),
    )
    still_open = PaperPosition(
        instrument_id="ETH/USDT.SIM",
        side="LONG",
        qty=Decimal("2"),
        entry_price=Decimal("2000"),
        opened_utc=START + timedelta(hours=2),
        is_open=True,
    )
    report = PaperSessionReport(
        robot=RobotName.REGIME,
        instrument_id="ETH/USDT.SIM",
        source="catalog",
        mode=TradingMode.PAPER,
        bar_count=10,
        window_start=START,
        window_end=START + timedelta(hours=10),
        starting_equity=Decimal("10000"),
        ending_equity=Decimal("10100"),
        fills=(fill,),
        positions=(closed, still_open),
        open_position=still_open,
        unrealized_pnl=Decimal("50"),
        mark_price=Decimal("2025"),
    )

    assert report.closed_positions == (closed,)
    assert report.realized_pnl == Decimal("100")
    assert report.net_pnl == Decimal("150")
    assert report.return_fraction == Decimal("150") / Decimal("10000")
    assert "paper regime" in report.summary_line()
    assert "no exchange submission" in report.summary_line()
    assert "open_qty=2" in report.summary_line()


# --- session log ---


def _session_report() -> PaperSessionReport:
    fill = PaperFill(
        ts_utc=START,
        instrument_id="ETH/USDT.SIM",
        side="BUY",
        qty=Decimal("1.5"),
        price=Decimal("2000.5"),
        commission=Decimal("3"),
        liquidity="TAKER",
        is_reduce_only=False,
    )
    return PaperSessionReport(
        robot=RobotName.EMA,
        instrument_id="ETH/USDT.SIM",
        source="catalog",
        mode=TradingMode.PAPER,
        bar_count=200,
        window_start=START,
        window_end=START + timedelta(hours=200),
        starting_equity=Decimal("100000"),
        ending_equity=Decimal("99000"),
        fills=(fill,),
        positions=(),
        fees_paid=Decimal("3"),
        traded_notional=Decimal("3000.75"),
        risk_breaches=(("daily loss circuit breaker", 2),),
    )


def test_session_record_keeps_decimals_as_strings() -> None:
    record = session_record(_session_report(), created_at="2026-01-01T00:00:00+00:00")
    assert record["starting_equity"] == "100000"
    assert record["fills"][0]["qty"] == "1.5"
    assert record["fills"][0]["price"] == "2000.5"
    assert record["risk_breaches"] == {"daily loss circuit breaker": 2}
    assert record["fill_count"] == 1
    # the record must be JSON-serialisable without a Decimal encoder
    json.dumps(record)


def test_append_session_is_append_only(tmp_path: Path) -> None:
    target = tmp_path / "sessions.jsonl"
    append_session(_session_report(), created_at="2026-01-01T00:00:00+00:00", path=target)
    append_session(_session_report(), created_at="2026-01-02T00:00:00+00:00", path=target)

    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["created_at"] for line in lines] == [
        "2026-01-01T00:00:00+00:00",
        "2026-01-02T00:00:00+00:00",
    ]
