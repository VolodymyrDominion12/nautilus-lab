from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import pandas as pd
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.models import FillModel, LatencyModel, MakerTakerFeeModel
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, RiskEngineConfig
from nautilus_trader.model.data import Bar, BarType, FundingRateUpdate
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import TraderId, Venue
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Currency, Money

from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    PaperFill,
    PaperPosition,
    PaperSessionReport,
)
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.funding import FundingSnapshot
from nautilus_lab.domain.marking import OpenLot, unrealized_pnl
from nautilus_lab.domain.metrics import PERIODS_PER_YEAR, compute_metrics
from nautilus_lab.domain.order_book import OrderBookSnapshot
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.ticks import AggTrade
from nautilus_lab.domain.windowing import within_bars
from nautilus_lab.infrastructure.nautilus.bar_convert import datetime_to_nanos, to_engine_bars
from nautilus_lab.infrastructure.nautilus.funding_strategy import (
    FundingRobot,
    FundingRobotConfig,
)
from nautilus_lab.infrastructure.nautilus.instrument import resolve_instrument
from nautilus_lab.infrastructure.nautilus.signal_strategy import SignalRobot, SignalRobotConfig
from nautilus_lab.infrastructure.nautilus.spread_strategy import SpreadRobot, SpreadRobotConfig
from nautilus_lab.infrastructure.nautilus.synthetic_pairs import synthetic_funding_pair
from nautilus_lab.infrastructure.timeframe import interval_from_bar_type, nautilus_bar_type

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Ledger:
    """Raw engine reports a paper session needs. Kept out of `BacktestReport`.

    `BacktestReport` is a scoring artifact and stays small; the ledger is the audit
    trail (every fill, every position) and only paper sessions ask for it.
    """

    fills_report: object
    positions_report: object
    equity_curve: tuple[Decimal, ...]
    turnover: Decimal
    risk_breaches: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class _RunSpec:
    """One engine run, fully prepared: what to load, what to trade, who trades it."""

    request: BacktestRequest
    instruments: list[Instrument]
    data: list[Bar]
    strategy: SignalRobot | SpreadRobot
    # Last close per instrument id: what a position still open at the end is worth.
    marks: dict[str, Decimal]


class NautilusResearchBacktest:
    """Low-level BacktestEngine with fees, latency, and slippage."""

    def run(
        self,
        request: BacktestRequest,
        bars: list[OhlcvBar],
        ticks: list[AggTrade] | None = None,
        books: list[OrderBookSnapshot] | None = None,
    ) -> BacktestReport:
        report, _ = self._execute(_single_run(request, bars, ticks, books))
        return report

    def run_paper(
        self,
        request: BacktestRequest,
        bars: list[OhlcvBar],
        ticks: list[AggTrade] | None = None,
        books: list[OrderBookSnapshot] | None = None,
    ) -> PaperSessionReport:
        """Same engine, same fees and latency, but the ledger comes back with it.

        Reusing the backtest engine on purpose: a second, hand-written paper matcher
        would drift from the numbers the research runs report, and the drift would be
        invisible until it mattered.
        """
        report, ledger = self._execute(_single_run(request, bars, ticks, books))
        traded = _traded(bars, request)
        return _paper_report(
            request,
            report,
            ledger,
            bar_count=len(traded),
            window_start=traded[0].ts_utc if traded else None,
            window_end=traded[-1].ts_utc if traded else None,
            mark_price=traded[-1].close if traded else None,
        )

    def run_spread(
        self,
        request: BacktestRequest,
        bars_by_instrument: dict[str, list[OhlcvBar]],
        funding: list[FundingSnapshot] | None = None,
    ) -> BacktestReport:
        spec = (
            _funding_run(request, bars_by_instrument, funding=funding)
            if request.robot is RobotName.FUNDING
            else _spread_run(request, bars_by_instrument)
        )
        report, _ = self._execute(spec)
        return report

    def run_paper_spread(
        self,
        request: BacktestRequest,
        bars_by_instrument: dict[str, list[OhlcvBar]],
        funding: list[FundingSnapshot] | None = None,
    ) -> PaperSessionReport:
        spec = (
            _funding_run(request, bars_by_instrument, funding=funding)
            if request.robot is RobotName.FUNDING
            else _spread_run(request, bars_by_instrument)
        )
        report, ledger = self._execute(spec)
        primary_id = (
            (request.funding_spot_id or "ETH/USDT.SIM")
            if request.robot is RobotName.FUNDING
            else request.pairs.leg_a
        )
        leg_primary = _traded(bars_by_instrument.get(primary_id, []), request)
        traded = [_traded(bars, request) for bars in bars_by_instrument.values()]
        starts = [bars[0].ts_utc for bars in traded if bars]
        ends = [bars[-1].ts_utc for bars in traded if bars]
        return _paper_report(
            request,
            report,
            ledger,
            bar_count=len(leg_primary),
            window_start=min(starts) if starts else None,
            window_end=max(ends) if ends else None,
            mark_price=leg_primary[-1].close if leg_primary else None,
        )

    def _execute(self, spec: _RunSpec) -> tuple[BacktestReport, _Ledger]:
        request = spec.request
        instruments = spec.instruments
        data = spec.data
        strategy = spec.strategy
        usdt = Currency.from_str("USDT")
        engine = BacktestEngine(
            config=BacktestEngineConfig(
                trader_id=TraderId("BACKTESTER-001"),
                logging=LoggingConfig(log_level="ERROR"),
                risk_engine=RiskEngineConfig(bypass=False),
            ),
        )
        try:
            engine.add_venue(
                venue=Venue("SIM"),
                oms_type=OmsType.NETTING,
                account_type=AccountType.MARGIN,
                starting_balances=[Money(request.starting_equity, usdt)],
                base_currency=usdt,
                default_leverage=Decimal(1),
                fill_model=FillModel(
                    prob_fill_on_limit=1.0,
                    prob_slippage=0.25,
                    random_seed=request.seed,
                ),
                fee_model=MakerTakerFeeModel(),
                latency_model=LatencyModel(base_latency_nanos=50_000_000),
                bar_execution=True,
            )
            for instrument in instruments:
                engine.add_instrument(instrument)
            engine.add_data(data)
            engine.add_strategy(strategy)
            engine.run()
            fills_report = engine.trader.generate_order_fills_report()
            positions = engine.trader.generate_positions_report()
            account = engine.trader.generate_account_report(venue=Venue("SIM"))
            realized = _ending_balance(account)
            open_pnl = unrealized_pnl(_open_lots(positions), spec.marks)
            accumulated_funding = getattr(strategy, "accumulated_funding", Decimal("0"))
            if realized is not None:
                realized = realized + accumulated_funding
            ending = None if realized is None else realized + open_pnl
            fees_paid = _fees_paid(fills_report)
            equity_curve = tuple(getattr(strategy, "equity_curve", ()))
            turnover = getattr(strategy, "turnover", Decimal("0"))
            risk_breaches = tuple(getattr(strategy, "risk_breaches", ()))
            traded_notional = _traded_notional(fills_report)
            metrics = compute_metrics(
                starting_equity=request.starting_equity,
                equity_curve=equity_curve,
                fees_paid=fees_paid,
                turnover=turnover,
                traded_notional=traded_notional,
                ending_equity=ending,
                periods_per_year=_periods_per_year(request),
            )
            saved_tearsheet: str | None = None
            if request.tearsheet_path:
                saved_tearsheet = _try_tearsheet(engine, request)

            report = BacktestReport(
                fills=len(fills_report),
                positions=len(positions),
                ending_balance=ending,
                notes=(
                    f"{request.robot.value} {request.source.value} backtest with fees "
                    f"(maker={request.fee_schedule.maker} taker={request.fee_schedule.taker}), "
                    "50ms latency, 25% one-tick slippage"
                ),
                metrics=metrics,
                tearsheet_path=saved_tearsheet,
                risk_breaches=risk_breaches,
                realized_balance=realized,
                unrealized_pnl=open_pnl,
            )
            ledger = _Ledger(
                fills_report=fills_report,
                positions_report=positions,
                equity_curve=equity_curve,
                turnover=turnover,
                risk_breaches=risk_breaches,
            )
            return report, ledger
        finally:
            engine.dispose()


def _open_lots(positions_report: object) -> list[OpenLot]:
    """Positions still open when the data ran out, as lots `domain.marking` can value."""
    lots: list[OpenLot] = []
    for position in _positions_from_report(positions_report):
        if not position.is_open or position.qty == 0:
            continue
        sign = Decimal("1") if position.side.startswith("L") else Decimal("-1")
        lots.append(
            OpenLot(
                instrument_id=position.instrument_id,
                signed_qty=abs(position.qty) * sign,
                avg_price=position.entry_price,
            )
        )
    return lots


def _periods_per_year(request: BacktestRequest) -> int | None:
    """Bars per year behind the equity curve, or None when it is not bar-sampled."""
    if request.robot is RobotName.ML_OBI:
        return None  # sampled on every book update, not once per bar
    try:
        return PERIODS_PER_YEAR.get(interval_from_bar_type(request.bar_type))
    except ValueError:
        return None


def _trade_start_ns(request: BacktestRequest) -> int | None:
    return None if request.trade_start is None else datetime_to_nanos(request.trade_start)


def _traded(bars: list[OhlcvBar], request: BacktestRequest) -> list[OhlcvBar]:
    """The bars a run actually trades: warm-up bars before `trade_start` excluded."""
    start = request.trade_start
    return bars if start is None else [bar for bar in bars if bar.ts_utc >= start]


def _last_closes(bars_by_instrument: dict[str, list[OhlcvBar]]) -> dict[str, Decimal]:
    return {key: bars[-1].close for key, bars in bars_by_instrument.items() if bars}


def _ending_balance(account_report: object) -> Decimal | None:
    import pandas as pd

    if not isinstance(account_report, pd.DataFrame) or account_report.empty:
        return None
    last = account_report.iloc[-1]
    for column in ("total", "balance", "free"):
        if column in account_report.columns:
            return Decimal(str(last[column]))
    return None


def _fees_paid(fills_report: object) -> Decimal:
    import pandas as pd

    if not isinstance(fills_report, pd.DataFrame) or fills_report.empty:
        return Decimal("0")
    for column in ("commissions", "commission", "fees"):
        if column not in fills_report.columns:
            continue
        total = Decimal("0")
        for value in fills_report[column]:
            text = str(value[0]) if isinstance(value, list) and value else str(value)
            amount = text.split()[0]
            total += Decimal(amount)
        return total
    return Decimal("0")


def _traded_notional(fills_report: object) -> Decimal:
    """Two-sided traded notional (entry AND exit fills) from the engine's fills report.

    This is the base for breakeven cost. The strategy's own `turnover` counter is
    NOT usable here: it accumulates entry notional only (signal_strategy.py adds it
    in the entry branch, and `_flatten()` closes positions without adding anything),
    so a breakeven computed from it would be roughly twice too optimistic.

    One row per filled order (`generate_order_fills_report`), so `avg_px * filled_qty`
    is the executed notional. Returns 0 when the report has no recognisable columns —
    breakeven then prints as undefined instead of inventing a number.
    """
    import pandas as pd

    if not isinstance(fills_report, pd.DataFrame) or fills_report.empty:
        return Decimal("0")
    price_column = next(
        (name for name in ("avg_px", "price", "last_px") if name in fills_report.columns),
        None,
    )
    quantity_column = next(
        (name for name in ("filled_qty", "quantity", "last_qty") if name in fills_report.columns),
        None,
    )
    if price_column is None or quantity_column is None:
        import logging

        logging.getLogger(__name__).warning(
            "Fills report has no usable price/quantity columns (%s); breakeven undefined.",
            ", ".join(str(name) for name in fills_report.columns),
        )
        return Decimal("0")
    total = Decimal("0")
    for price, quantity in zip(
        fills_report[price_column], fills_report[quantity_column], strict=True
    ):
        total += _to_decimal(price) * _to_decimal(quantity)
    return total


def _to_decimal(value: object) -> Decimal:
    """Nautilus reports mix Decimal, float and '0.5 USDT'-style strings."""
    text = str(value[0]) if isinstance(value, list) and value else str(value)
    token = text.split()[0] if text.split() else "0"
    try:
        return Decimal(token)
    except InvalidOperation:
        return Decimal("0")


def _try_tearsheet(engine: BacktestEngine, request: BacktestRequest) -> str | None:
    """Best-effort HTML tearsheet. A failure here must never fail the run."""
    path = request.tearsheet_path
    if path is None:
        return None
    try:
        from pathlib import Path

        from nautilus_trader.analysis.tearsheet import PLOTLY_AVAILABLE, create_tearsheet

        if not PLOTLY_AVAILABLE:
            _log.warning("Cannot generate tearsheet: plotly is missing.")
            return None
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        create_tearsheet(
            engine,
            output_path=path,
            title=f"nautilus-lab {request.robot.value} Backtest Results",
        )
        return path
    except Exception as exc:  # noqa: BLE001 — a tearsheet is optional; the run result is not
        _log.warning("Failed to generate tearsheet: %s", exc)
        return None


def _paper_report(
    request: BacktestRequest,
    report: BacktestReport,
    ledger: _Ledger,
    *,
    bar_count: int,
    window_start: datetime | None,
    window_end: datetime | None,
    mark_price: Decimal | None,
) -> PaperSessionReport:
    """Assemble the paper ledger, marking any still-open position against the last close."""
    positions = _positions_from_report(ledger.positions_report)
    open_position = next((position for position in positions if position.is_open), None)
    # Every open leg is marked (a pairs session ends holding two), not just the first.
    unrealized = report.unrealized_pnl
    return PaperSessionReport(
        robot=request.robot,
        instrument_id=request.instrument_id,
        source=request.source.value,
        mode=request.mode,
        bar_count=bar_count,
        window_start=window_start,
        window_end=window_end,
        starting_equity=request.starting_equity,
        # The paper ledger shows the realized balance and the open PnL side by side;
        # `report.ending_balance` already adds them, so it would count the mark twice.
        ending_equity=report.realized_balance,
        equity_curve=ledger.equity_curve,
        fills=_fills_from_report(ledger.fills_report),
        positions=positions,
        fees_paid=report.metrics.fees_paid if report.metrics is not None else Decimal("0"),
        turnover=ledger.turnover,
        traded_notional=report.metrics.traded_notional
        if report.metrics is not None
        else Decimal("0"),
        metrics=report.metrics,
        risk_breaches=ledger.risk_breaches,
        open_position=open_position,
        unrealized_pnl=unrealized,
        mark_price=mark_price,
    )


def _fills_from_report(fills_report: object) -> tuple[PaperFill, ...]:
    """One `PaperFill` per executed order. Unknown columns are skipped, not guessed."""
    if not isinstance(fills_report, pd.DataFrame) or fills_report.empty:
        return ()
    required = {"side", "filled_qty", "avg_px", "commissions", "ts_last"}
    missing = required - set(fills_report.columns)
    if missing:
        _log.warning(
            "Fills report lacks %s; paper ledger will be empty rather than invented.",
            ", ".join(sorted(missing)),
        )
        return ()
    fills: list[PaperFill] = []
    for _, row in fills_report.iterrows():
        commissions = row["commissions"]
        commission = Decimal("0")
        if isinstance(commissions, list):
            for entry in commissions:
                commission += _to_decimal(entry)
        else:
            commission = _to_decimal(commissions)
        fills.append(
            PaperFill(
                ts_utc=_as_utc(row["ts_last"]),
                instrument_id=str(row.get("instrument_id", "")),
                side=str(row["side"]).upper(),
                qty=_to_decimal(row["filled_qty"]),
                price=_to_decimal(row["avg_px"]),
                commission=commission,
                liquidity=str(row.get("liquidity_side", "")),
                is_reduce_only=bool(row.get("is_reduce_only", False)),
            )
        )
    return tuple(fills)


def _positions_from_report(positions_report: object) -> tuple[PaperPosition, ...]:
    """One `PaperPosition` per netted position the engine opened.

    A position without a close timestamp is still open when the window ends; its
    `realized_pnl` is what the engine booked so far, and marking it is the caller's job.
    """
    if not isinstance(positions_report, pd.DataFrame) or positions_report.empty:
        return ()
    required = {"instrument_id", "side", "quantity", "avg_px_open", "ts_opened"}
    missing = required - set(positions_report.columns)
    if missing:
        _log.warning(
            "Positions report lacks %s; paper ledger will omit positions.",
            ", ".join(sorted(missing)),
        )
        return ()
    positions: list[PaperPosition] = []
    for _, row in positions_report.iterrows():
        raw_close = row.get("ts_closed")
        closed = _optional_utc(raw_close)
        exit_price = None if closed is None else _to_decimal(row.get("avg_px_close", 0))
        positions.append(
            PaperPosition(
                instrument_id=str(row["instrument_id"]),
                side=str(row["side"]).upper(),
                qty=_to_decimal(row["quantity"]),
                entry_price=_to_decimal(row["avg_px_open"]),
                opened_utc=_as_utc(row["ts_opened"]),
                exit_price=exit_price,
                closed_utc=closed,
                realized_pnl=_to_decimal(row.get("realized_pnl", 0)),
                is_open=closed is None,
            )
        )
    return tuple(positions)


def _as_utc(value: object) -> datetime:
    """A ledger row without a timestamp is unusable: stop rather than drop it silently."""
    resolved = _optional_utc(value)
    if resolved is None:
        raise ValueError(f"engine report row has no usable timestamp: {value!r}")
    return resolved


def _optional_utc(value: object) -> datetime | None:
    """Report timestamps arrive as pandas Timestamps, datetimes, strings, or NaT/None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        # NaT subclasses datetime in pandas; `pd.isna` is the only honest test.
        if pd.isna(value):
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"nat", "none"}:
            return None
        try:
            stamp = pd.Timestamp(text)
        except (TypeError, ValueError):
            return None
        return None if pd.isna(stamp) else stamp.to_pydatetime().astimezone(UTC)
    return None


def _single_run(
    request: BacktestRequest,
    bars: list[OhlcvBar],
    ticks: list[AggTrade] | None,
    books: list[OrderBookSnapshot] | None,
) -> _RunSpec:
    """Everything `_execute` needs for a single-instrument run."""
    if request.robot is RobotName.PAIRS:
        raise ValueError("pairs robot requires run_spread with two instruments")
    instrument = resolve_instrument(request.instrument_id, fees=request.fee_schedule)
    bar_type = BarType.from_str(request.bar_type)
    engine_bars = to_engine_bars(bars, bar_type=bar_type, instrument=instrument)
    # The taker split cannot ride inside a Nautilus `Bar`, so it is handed to the
    # strategy as a lookup keyed by the bar event timestamp. The key is built with
    # the same `datetime_to_nanos` that `to_engine_bars` uses, which makes the join
    # exact rather than approximate.
    taker_buy_by_ns = {
        datetime_to_nanos(bar.ts_utc): bar.taker_buy_base_volume
        for bar in bars
        if bar.taker_buy_base_volume is not None
    }
    strategy = SignalRobot(
        SignalRobotConfig(
            instrument_id=instrument.id,
            bar_type=bar_type,
            robot=request.robot.value,
            fast_period=request.fast_ema,
            slow_period=request.slow_ema,
            er_period=request.regime.er_period,
            trend_ema_period=request.regime.trend_ema_period,
            slope_lookback=request.regime.slope_lookback,
            enter_trend_er=request.regime.enter_trend_er,
            exit_trend_er=request.regime.exit_trend_er,
            donchian_period=request.regime.donchian_period,
            bb_period=request.regime.bb_period,
            bb_k=request.regime.bb_k,
            risk_per_trade=request.risk.risk_per_trade,
            stop_pct=request.risk.stop_pct,
            max_daily_loss=request.risk.max_daily_loss,
            max_drawdown=request.risk.max_drawdown,
            max_open_positions=request.risk.max_open_positions,
            kelly_fraction=request.risk.kelly_fraction,
            max_var_99=request.risk.max_var_99,
            use_bar_vpin=request.use_bar_vpin,
            vpin_bucket_volume=request.vpin_bucket_volume,
            vpin_toxic_threshold=request.vpin_toxic_threshold,
            vpin_momentum_ema_period=request.vpin_momentum_ema_period,
            vpin_momentum_atr_multiple=request.vpin_momentum_atr_multiple,
            formulaic_model_path=request.formulaic_model_path,
            formulaic_threshold=request.formulaic_threshold,
            meta_label_model_path=request.meta_label_model_path,
            meta_label_threshold=request.meta_label_threshold,
            adaptive_period=request.adaptive_params.base_period,
            adaptive_er_period=request.adaptive_params.er_period,
            adaptive_selectivity=request.adaptive_params.selectivity,
            adaptive_slope_lookback=request.adaptive_params.slope_lookback,
            use_vol_scaling=request.risk_overlay.use_vol_scaling,
            vol_scaling_target=request.risk_overlay.vol_scaling_target,
            vol_model=request.risk_overlay.vol_model,
            vol_refit_every=request.risk_overlay.vol_refit_every,
            use_fractional_kelly=request.risk_overlay.use_fractional_kelly,
            kelly_min_trades=request.risk_overlay.kelly_min_trades,
            use_cvar_breaker=request.risk_overlay.use_cvar_breaker,
            max_cvar_99=request.risk_overlay.max_cvar_99,
            use_ratchet=request.risk_overlay.use_ratchet,
            ratchet_arm_pct=request.risk_overlay.ratchet_arm_pct,
            use_protective_stop=request.risk_overlay.use_protective_stop,
            # Tick-level filters: before these three lines existed `--tick-vpin` and
            # `--hawkes` loaded the tick series and then built the robot without them.
            use_tick_vpin=request.use_tick_vpin,
            use_hawkes=request.use_hawkes,
            hawkes_baseline=request.hawkes_baseline,
            hawkes_alpha=request.hawkes_alpha,
            hawkes_beta=request.hawkes_beta,
            hawkes_toxic_threshold=request.hawkes_toxic_threshold,
            ml_obi_model_path=request.ml_obi_model_path,
            ml_obi_threshold=request.ml_obi_threshold,
            trade_start_ns=_trade_start_ns(request),
            drawdown_cooldown_days=request.risk_overlay.drawdown_cooldown_days,
        ),
        taker_buy_base_volume_by_ns=taker_buy_by_ns or None,
    )

    # Every caller loads the whole tick/book series; only the part the bars cover may
    # reach the engine (an in-sample run must not see out-of-sample ticks).
    ticks = within_bars(ticks, bars) if ticks else None
    books = within_bars(books, bars) if books else None

    engine_ticks = []
    if ticks:
        from nautilus_lab.infrastructure.nautilus.bar_convert import to_engine_ticks

        engine_ticks = to_engine_ticks(ticks, instrument=instrument)

    engine_books = []
    if books:
        from nautilus_lab.infrastructure.nautilus.bar_convert import to_engine_books

        engine_books = to_engine_books(books, instrument=instrument)

    return _RunSpec(
        request=request,
        instruments=[instrument],
        data=[*engine_bars, *engine_ticks, *engine_books],
        strategy=strategy,
        marks=_last_closes({str(instrument.id): bars}),
    )


def _spread_run(
    request: BacktestRequest,
    bars_by_instrument: dict[str, list[OhlcvBar]],
) -> _RunSpec:
    """Everything `_execute` needs for the two-leg pairs run."""
    leg_a = request.pairs.leg_a
    leg_b = request.pairs.leg_b
    bars_a = bars_by_instrument.get(leg_a)
    bars_b = bars_by_instrument.get(leg_b)
    if bars_a is None or bars_b is None:
        raise ValueError(f"missing bars for pair {leg_a}/{leg_b}")
    instrument_a = resolve_instrument(leg_a, fees=request.fee_schedule)
    instrument_b = resolve_instrument(leg_b, fees=request.fee_schedule)
    interval = interval_from_bar_type(request.bar_type)
    bar_type_a = BarType.from_str(nautilus_bar_type(leg_a, interval))
    bar_type_b = BarType.from_str(nautilus_bar_type(leg_b, interval))
    data_a = to_engine_bars(bars_a, bar_type=bar_type_a, instrument=instrument_a)
    data_b = to_engine_bars(bars_b, bar_type=bar_type_b, instrument=instrument_b)
    strategy = SpreadRobot(
        SpreadRobotConfig(
            leg_a_id=instrument_a.id,
            leg_b_id=instrument_b.id,
            bar_type_a=bar_type_a,
            bar_type_b=bar_type_b,
            pairs=request.pairs,
            risk_per_trade=request.risk.risk_per_trade,
            stop_pct=request.risk.stop_pct,
            max_daily_loss=request.risk.max_daily_loss,
            max_drawdown=request.risk.max_drawdown,
            max_open_positions=request.risk.max_open_positions,
            kelly_fraction=request.risk.kelly_fraction,
            max_var_99=request.risk.max_var_99,
            use_vol_scaling=request.risk_overlay.use_vol_scaling,
            vol_scaling_target=request.risk_overlay.vol_scaling_target,
            use_fractional_kelly=request.risk_overlay.use_fractional_kelly,
            kelly_min_trades=request.risk_overlay.kelly_min_trades,
            use_cvar_breaker=request.risk_overlay.use_cvar_breaker,
            max_cvar_99=request.risk_overlay.max_cvar_99,
            trade_start_ns=_trade_start_ns(request),
            drawdown_cooldown_days=request.risk_overlay.drawdown_cooldown_days,
        ),
    )
    return _RunSpec(
        request=request,
        instruments=[instrument_a, instrument_b],
        data=[*data_a, *data_b],
        strategy=strategy,
        marks=_last_closes({str(instrument_a.id): bars_a, str(instrument_b.id): bars_b}),
    )


def _funding_run(
    request: BacktestRequest,
    bars_by_instrument: dict[str, list[OhlcvBar]],
    *,
    funding: list[FundingSnapshot] | None = None,
) -> _RunSpec:
    """Everything `_execute` needs for the funding cash-and-carry run."""
    spot_id = request.funding_spot_id or "ETH/USDT.SIM"
    perp_id = request.funding_perp_id or "ETHUSDT-PERP.SIM"
    bars_spot = bars_by_instrument.get(spot_id)
    bars_perp = bars_by_instrument.get(perp_id)
    if bars_spot is None or bars_perp is None:
        raise ValueError(f"missing bars for funding pair {spot_id}/{perp_id}")
    instrument_spot = resolve_instrument(spot_id, fees=request.fee_schedule)
    instrument_perp = resolve_instrument(perp_id, fees=request.fee_schedule)
    interval = interval_from_bar_type(request.bar_type)
    bar_type_spot = BarType.from_str(nautilus_bar_type(spot_id, interval))
    bar_type_perp = BarType.from_str(nautilus_bar_type(perp_id, interval))
    data_spot = to_engine_bars(bars_spot, bar_type=bar_type_spot, instrument=instrument_spot)
    data_perp = to_engine_bars(bars_perp, bar_type=bar_type_perp, instrument=instrument_perp)

    funding_snapshots = funding
    if funding_snapshots is None and request.source is BarOrigin.SYNTHETIC:
        _, funding_snapshots = synthetic_funding_pair(
            spot_id=spot_id,
            perp_id=perp_id,
            count=request.bar_count,
            seed=request.seed,
        )

    if funding_snapshots:
        # Same rule as ticks and books (audit A4): a run only sees settlements inside
        # its own bar span. Uncut, every fold accrued the whole series' payments, so an
        # in-sample window ending 2025-11-22 banked ~900 settlements dated after it.
        funding_snapshots = within_bars(funding_snapshots, bars_perp)

    funding_data: list[FundingRateUpdate] = []
    if funding_snapshots:
        for snap in funding_snapshots:
            ts_ns = datetime_to_nanos(snap.ts_utc)
            funding_data.append(
                FundingRateUpdate(
                    instrument_id=instrument_perp.id,
                    rate=snap.funding_rate,
                    ts_event=ts_ns,
                    ts_init=ts_ns,
                    interval=480,
                )
            )

    strategy = FundingRobot(
        FundingRobotConfig(
            leg_spot_id=instrument_spot.id,
            leg_perp_id=instrument_perp.id,
            bar_type_spot=bar_type_spot,
            bar_type_perp=bar_type_perp,
            params=request.funding,
            risk_per_trade=request.risk.risk_per_trade,
            stop_pct=request.risk.stop_pct,
            max_daily_loss=request.risk.max_daily_loss,
            max_drawdown=request.risk.max_drawdown,
            max_open_positions=request.risk.max_open_positions,
            kelly_fraction=request.risk.kelly_fraction,
            max_var_99=request.risk.max_var_99,
            use_vol_scaling=request.risk_overlay.use_vol_scaling,
            vol_scaling_target=request.risk_overlay.vol_scaling_target,
            use_fractional_kelly=request.risk_overlay.use_fractional_kelly,
            kelly_min_trades=request.risk_overlay.kelly_min_trades,
            use_cvar_breaker=request.risk_overlay.use_cvar_breaker,
            max_cvar_99=request.risk_overlay.max_cvar_99,
            qty_step_spot=instrument_spot.size_increment.as_decimal(),
            qty_step_perp=instrument_perp.size_increment.as_decimal(),
            trade_start_ns=_trade_start_ns(request),
            drawdown_cooldown_days=request.risk_overlay.drawdown_cooldown_days,
            quote_currency="USDT",
        ),
    )
    return _RunSpec(
        request=request,
        instruments=[instrument_spot, instrument_perp],
        data=[*data_spot, *data_perp, *funding_data],
        strategy=strategy,
        marks=_last_closes(
            {str(instrument_spot.id): bars_spot, str(instrument_perp.id): bars_perp}
        ),
    )
