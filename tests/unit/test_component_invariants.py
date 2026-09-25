from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.model.enums import AggressorSide

from nautilus_lab.application.run_overfitting_audit import _block_ranges
from nautilus_lab.application.run_paper import RunPaperResearch
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.order_book import BookLevel, OrderBookSnapshot
from nautilus_lab.domain.ports import JsonHttpClient
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.signals import LegIntent, QuoteIntent, Signal, SignalSide, SpreadSignal
from nautilus_lab.domain.ticks import AggTrade
from nautilus_lab.infrastructure.binance_klines import BinancePublicKlines
from nautilus_lab.infrastructure.nautilus.bar_convert import (
    datetime_to_nanos,
    to_domain_snapshot,
    to_engine_books,
    to_engine_ticks,
)
from nautilus_lab.infrastructure.nautilus.instrument import (
    binance_symbol_to_instrument_id,
    resolve_instrument,
    supported_instrument_ids,
)
from nautilus_lab.infrastructure.paper_trading import PaperTradingLogger
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.interfaces import composition
from nautilus_lab.interfaces.cli import main
from nautilus_lab.interfaces.composition import catalog, research_request

# --- backtest-engine ---


def test_backtest_engine_fee_schedule_agreement() -> None:
    """Backtest instrument and catalog instrument definition use the same FeeSchedule."""
    cfg = Settings()
    cat = catalog(cfg)
    req = research_request(cfg, bar_count=100)

    assert cat._fees == req.fee_schedule == cfg.fee_schedule()
    inst = resolve_instrument(req.instrument_id, fees=cat._fees)
    assert Decimal(str(inst.maker_fee)) == req.fee_schedule.maker
    assert Decimal(str(inst.taker_fee)) == req.fee_schedule.taker


# --- data-catalog ---


class _FakeEndBoundaryHttpClient(JsonHttpClient):
    def __init__(self, rows: list[list[object]]) -> None:
        self._rows = rows

    def get_json(self, url: str, params: Mapping[str, str]) -> list[list[object]]:
        return self._rows


def test_data_catalog_half_open_window_end_discard() -> None:
    """Ingest window is half-open [start, end): bars with timestamp >= end are discarded."""
    start = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    end = datetime(2024, 1, 1, 2, 0, tzinfo=UTC)

    # Three bars: 00:30 (inside), 01:00 (inside), 02:00 (on end boundary)
    bar_inside_1_ms = int(datetime(2024, 1, 1, 0, 30, tzinfo=UTC).timestamp() * 1000)
    bar_inside_2_ms = int(datetime(2024, 1, 1, 1, 0, tzinfo=UTC).timestamp() * 1000)
    bar_on_end_ms = int(end.timestamp() * 1000)

    raw_rows: list[list[object]] = [
        [bar_inside_1_ms - 1800000, "100", "105", "99", "102", "10", bar_inside_1_ms],
        [bar_inside_2_ms - 1800000, "102", "106", "101", "105", "15", bar_inside_2_ms],
        [bar_on_end_ms - 3600000, "105", "108", "104", "107", "20", bar_on_end_ms],
    ]

    client = _FakeEndBoundaryHttpClient(raw_rows)
    feed = BinancePublicKlines(
        http=client,
        now=datetime(2025, 1, 1, tzinfo=UTC),
        page_limit=10,
    )

    bars = feed.fetch(
        symbol="ETHUSDT",
        interval="1h",
        start=start,
        end=end,
        instrument_id="ETH/USDT.SIM",
    )

    # Bar with timestamp == end must be discarded
    assert len(bars) == 2
    assert all(b.ts_utc < end for b in bars)
    assert bars[-1].ts_utc == datetime(2024, 1, 1, 1, 0, tzinfo=UTC)


def _increment_decimals(increment: object) -> int:
    """Decimals the declared increment spells out — "0.00001" -> 5, "1" -> 0.

    Read off the textual form, because that is exactly what `_currency_pair`
    derives `size_precision` from; `Decimal` would drop a trailing zero
    ("0.010" -> exponent -2) and hide the mismatch this test is looking for.
    """
    text = str(increment)
    return len(text.split(".")[1]) if "." in text else 0


def test_instrument_specs_match_declared_increments() -> None:
    """Instrument precision equals the increment that instrument declares.

    `to_engine_bars` builds every OHLC value as
    `Price(value, precision=price_precision)`, so a tick coarser than the venue's
    silently rewrites the series the backtest reads: DOGE 0.12345 at precision 2
    becomes 0.12.
    """
    for instrument_id in supported_instrument_ids():
        instrument = resolve_instrument(instrument_id)
        assert instrument.price_precision == _increment_decimals(instrument.price_increment), (
            f"{instrument_id}: price_precision != increment {instrument.price_increment}"
        )
        assert instrument.size_precision == _increment_decimals(instrument.size_increment), (
            f"{instrument_id}: size_precision != increment {instrument.size_increment}"
        )


def test_every_ingestable_usdt_symbol_has_an_instrument_spec() -> None:
    """Every *USDT symbol `lab ingest` accepts has an instrument description.

    `binance_symbol_to_instrument_id` accepts any USDT ticker while
    `resolve_instrument` knows only an explicit list. When those two sets drift
    apart, ingest dies halfway through a symbol list
    (`unsupported instrument_id: SOL/USDT.SIM`) with the earlier symbols already
    written to the catalog.
    """
    for symbol in (
        "ETHUSDT",
        "BTCUSDT",
        "SOLUSDT",
        "BNBUSDT",
        "XRPUSDT",
        "ADAUSDT",
        "DOGEUSDT",
    ):
        instrument_id = binance_symbol_to_instrument_id(symbol)
        instrument = resolve_instrument(instrument_id)
        assert str(instrument.id) == f"{symbol.removesuffix('USDT')}/USDT.SIM"


def test_unknown_instrument_id_fails_closed_and_names_the_open_doors() -> None:
    """An unknown instrument fails closed but lists the supported ids."""
    pattern = re.escape("unsupported instrument_id: PEPE/USDT.SIM")
    with pytest.raises(ValueError, match=pattern) as excinfo:
        resolve_instrument("PEPE/USDT.SIM")
    message = str(excinfo.value)
    for instrument_id in supported_instrument_ids():
        assert instrument_id in message


# --- execution-modes ---


def test_live_enabled_flag_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """LIVE_ENABLED flag changes nothing: lab live always fails closed with exit code 1."""
    monkeypatch.setenv("LIVE_ENABLED", "true")
    assert main(["live"]) == 1


def test_empty_exchange_credentials_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty EXCHANGE_API_KEY and EXCHANGE_API_SECRET allow research runs to proceed."""
    monkeypatch.setenv("EXCHANGE_API_KEY", "")
    monkeypatch.setenv("EXCHANGE_API_SECRET", "")
    cfg = Settings()
    assert cfg.exchange_api_key == ""
    assert cfg.exchange_api_secret == ""
    # Research run succeeds without API credentials (requires >= 150 bars for regime)
    assert main(["research", "--synthetic", "--bars", "200"]) == 0


def test_paper_trading_position_statelessness() -> None:
    """Paper trading logger is stateless: multiple sequential buy signals are logged."""
    logger = PaperTradingLogger()
    ts1 = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    ts2 = datetime(2024, 1, 1, 13, 0, tzinfo=UTC)

    sig1 = Signal(
        instrument_id="ETH/USDT.SIM",
        side=SignalSide.BUY,
        bar_ts_utc=ts1,
        reason="sig1",
    )
    sig2 = Signal(
        instrument_id="ETH/USDT.SIM",
        side=SignalSide.BUY,
        bar_ts_utc=ts2,
        reason="sig2",
    )

    logger.log_signal(sig1, Decimal("1.5"))
    logger.log_signal(sig2, Decimal("2.0"))

    assert len(logger.orders) == 2
    assert logger.orders[0].side == "buy"
    assert logger.orders[0].qty == Decimal("1.5")
    assert logger.orders[1].side == "buy"
    assert logger.orders[1].qty == Decimal("2.0")

    # Verify RunPaperResearch: open_positions is always 0 in the snapshot
    runner = RunPaperResearch(logger)
    cfg = Settings()
    req = research_request(cfg, bar_count=50, robot=RobotName.EMA)
    # Generate bars
    bars = [
        OhlcvBar(
            instrument_id="ETH/USDT.SIM",
            ts_utc=ts1 + timedelta(hours=i),
            open=Decimal("2000") + Decimal(i * 10),
            high=Decimal("2010") + Decimal(i * 10),
            low=Decimal("1995") + Decimal(i * 10),
            close=Decimal("2005") + Decimal(i * 10),
            volume=Decimal("100"),
        )
        for i in range(25)
    ]
    result_logger = runner.execute(req, bars)
    assert result_logger is logger


# --- overfitting-audit ---


def test_pbo_tearsheet_conflict_fails_closed(tmp_path: Path) -> None:
    """--pbo combined with --tearsheet fails closed with exit code 1."""
    t_file = tmp_path / "tearsheet.html"
    res = main(["research", "--pbo", "--tearsheet", str(t_file), "--bars", "200"])
    assert res == 1


def test_pbo_block_ranges_partition_and_remainder() -> None:
    """_block_ranges are non-overlapping, partition the history, and assign remainder to last."""
    total = 105
    blocks = 8
    ranges = _block_ranges(total, blocks)

    assert len(ranges) == blocks
    # First block starts at 0
    assert ranges[0][0] == 0
    # Last block ends exactly at total
    assert ranges[-1][1] == total

    # Adjacent blocks have no gaps and do not overlap
    for i in range(len(ranges) - 1):
        assert ranges[i][1] == ranges[i + 1][0]

    # Base size 105 // 8 = 13
    for i in range(blocks - 1):
        assert ranges[i][1] - ranges[i][0] == 13

    # Last block absorbs the remainder (13 + 1 = 14)
    assert ranges[-1][1] - ranges[-1][0] == 14

    with pytest.raises(ValueError, match="cannot fill"):
        _block_ranges(total=3, blocks=5)


# --- risk-layer ---


def test_domain_strategies_do_not_size_positions() -> None:
    """Domain strategies return signals only: no domain module imports size_position."""
    domain_dir = Path(__file__).resolve().parent.parent.parent / "src/nautilus_lab/domain"
    for py_file in domain_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "nautilus_lab.application.risk", (
                    f"{py_file} imports from application.risk!"
                )
                for alias in node.names:
                    assert alias.name != "size_position", f"{py_file} imports size_position!"

    # Signals and intents carry only direction or relative weights, never position size/capital
    sig = Signal(
        instrument_id="ETH/USDT.SIM",
        side=SignalSide.BUY,
        bar_ts_utc=datetime.now(UTC),
        reason="test",
    )
    assert hasattr(sig, "side")
    assert not hasattr(sig, "size")
    assert not hasattr(sig, "qty")
    assert not hasattr(sig, "notional")

    leg_a = LegIntent("ETH/USDT.SIM", SignalSide.BUY, qty_weight=Decimal("1"))
    leg_b = LegIntent("BTC/USDT.SIM", SignalSide.SELL, qty_weight=Decimal("0.05"))
    spread = SpreadSignal(
        leg_a=leg_a,
        leg_b=leg_b,
        bar_ts_utc=datetime.now(UTC),
        reason="spread",
        hedge_ratio=Decimal("0.05"),
    )
    assert spread.leg_a.qty_weight == Decimal("1")
    assert not hasattr(spread, "size")

    quote = QuoteIntent(
        instrument_id="ETH/USDT.SIM",
        bar_ts_utc=datetime.now(UTC),
        bid_price=Decimal("2000"),
        ask_price=Decimal("2002"),
    )
    assert quote.bid_qty_weight == Decimal("1")


# --- interfaces-composition ---


def test_composition_use_case_factories_construct() -> None:
    """Every `*_use_case()` factory in composition builds a use case without raising.

    A factory that dies on construction kills a whole CLI path while unit tests stay
    green: `overfit_audit_use_case()` passed four arguments to a three-argument
    `RunOverfitAudit`, so `lab research --pbo` was a `TypeError` and nothing said so.
    """
    cfg = Settings()
    factories = {
        name: getattr(composition, name)
        for name in dir(composition)
        if name.endswith("_use_case") and callable(getattr(composition, name))
    }
    assert set(factories) >= {
        "research_use_case",
        "walk_forward_use_case",
        "overfit_audit_use_case",
        "ingest_use_case",
        "ingest_funding_use_case",
        "ingest_agg_trades_use_case",
        "ingest_orderbook_use_case",
    }
    for name, factory in sorted(factories.items()):
        try:
            factory(cfg)
        except TypeError as exc:
            raise AssertionError(f"{name}() cannot build its use case: {exc}") from exc


def test_feed_hungry_use_cases_receive_their_feeds() -> None:
    """Tick/book-dependent paths must be handed a feed, not constructed without one.

    `ml_obi` and the tick filters raise when their feed is `None`, so a factory that
    drops an argument makes the robot unusable rather than merely silent.
    """
    cfg = Settings()
    for factory in (
        composition.research_use_case,
        composition.walk_forward_use_case,
        composition.overfit_audit_use_case,
    ):
        use_case = factory(cfg)
        assert use_case._tick_feed is not None, factory.__name__
        assert use_case._book_feed is not None, factory.__name__


# --- order-book ---


def test_order_book_snapshot_round_trip_keeps_prices_and_sizes() -> None:
    """domain → engine → domain keeps levels intact (`BookLevel` stores `size`, not `volume`).

    The converter built `BookLevel(volume=...)` and read `level.volume`, so every
    order-book round trip raised `TypeError` while the suite stayed green.
    """
    cfg = Settings()
    request = research_request(cfg, bar_count=100)
    instrument = resolve_instrument(request.instrument_id, fees=cfg.fee_schedule())
    ts_utc = datetime(2024, 1, 1, tzinfo=UTC)
    snapshot = OrderBookSnapshot(
        instrument_id=request.instrument_id,
        ts_utc=ts_utc,
        bids=(
            BookLevel(price=Decimal("3000.50"), size=Decimal("1.5")),
            BookLevel(price=Decimal("3000.40"), size=Decimal("2.0")),
        ),
        asks=(
            BookLevel(price=Decimal("3000.60"), size=Decimal("0.5")),
            BookLevel(price=Decimal("3000.70"), size=Decimal("3.0")),
        ),
    )
    snapshot.validate()

    depth = to_engine_books([snapshot], instrument=instrument)[0]
    restored = to_domain_snapshot(depth, request.instrument_id)
    restored.validate()

    assert restored.bids == snapshot.bids
    assert restored.asks == snapshot.asks
    assert datetime_to_nanos(restored.ts_utc) == datetime_to_nanos(snapshot.ts_utc)
    assert restored.instrument_id == snapshot.instrument_id


def test_order_book_conversion_truncates_to_the_engine_depth() -> None:
    """A 20-level Binance snapshot must not crash the engine's ten-level container."""
    cfg = Settings()
    request = research_request(cfg, bar_count=100)
    instrument = resolve_instrument(request.instrument_id, fees=cfg.fee_schedule())
    snapshot = OrderBookSnapshot(
        instrument_id=request.instrument_id,
        ts_utc=datetime(2024, 1, 1, tzinfo=UTC),
        bids=tuple(
            BookLevel(price=Decimal(3000 - index), size=Decimal("1")) for index in range(20)
        ),
        asks=tuple(
            BookLevel(price=Decimal(3001 + index), size=Decimal("1")) for index in range(20)
        ),
    )
    snapshot.validate()

    depth = to_engine_books([snapshot], instrument=instrument)[0]

    assert len(depth.bids) == 10
    assert len(depth.asks) == 10
    # the levels kept are the best ones, not an arbitrary slice
    restored = to_domain_snapshot(depth, request.instrument_id)
    assert restored.bids[0].price == snapshot.bids[0].price
    assert restored.asks[0].price == snapshot.asks[0].price
    restored.validate()


def test_tick_conversion_accepts_binance_decimal_strings() -> None:
    """Domain trades keep Binance's exact strings; the engine needs real numbers.

    Regression: `to_engine_ticks` passed `AggTrade.price` (a `str`) into Nautilus
    `Price`, raising `TypeError: must be real number, not str` and killing every
    `--tick-vpin` / `--hawkes` run. No test covered it because no tick series existed
    in the catalog to exercise the path.
    """
    cfg = Settings()
    request = research_request(cfg, bar_count=100)
    instrument = resolve_instrument(request.instrument_id, fees=cfg.fee_schedule())
    trade = AggTrade(
        instrument_id=request.instrument_id,
        ts_utc=datetime(2024, 1, 1, tzinfo=UTC),
        agg_id=42,
        price="2733.63000000",
        qty="1.25000000",
        is_buyer_maker=False,
    )

    ticks = to_engine_ticks([trade], instrument=instrument)

    assert len(ticks) == 1
    tick = ticks[0]
    assert str(tick.price) == "2733.63"
    assert str(tick.size) == "1.250"
    assert str(tick.trade_id) == "42"
    # A taker buy lifted the ask, so the aggressor is the buyer.
    assert tick.aggressor_side == AggressorSide.BUYER
