from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from nautilus_trader.model.data import Bar, BarType, BookOrder, OrderBookDepth10, TradeTick
from nautilus_trader.model.enums import AggressorSide, OrderSide
from nautilus_trader.model.identifiers import TradeId
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Price, Quantity

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.order_book import BookLevel, OrderBookSnapshot
from nautilus_lab.domain.ticks import AggTrade

_log = logging.getLogger(__name__)


def datetime_to_nanos(ts: datetime) -> int:
    return int(ts.timestamp() * 1_000_000_000)


def nanos_to_datetime(ts_event: int) -> datetime:
    return datetime.fromtimestamp(ts_event / 1_000_000_000, tz=UTC)


def to_engine_bars(
    bars: list[OhlcvBar],
    *,
    bar_type: BarType,
    instrument: CurrencyPair,
) -> list[Bar]:
    return [
        Bar(
            bar_type=bar_type,
            open=Price(bar.open, precision=instrument.price_precision),
            high=Price(bar.high, precision=instrument.price_precision),
            low=Price(bar.low, precision=instrument.price_precision),
            close=Price(bar.close, precision=instrument.price_precision),
            volume=Quantity(bar.volume, precision=instrument.size_precision),
            ts_event=datetime_to_nanos(bar.ts_utc),
            ts_init=datetime_to_nanos(bar.ts_utc),
        )
        for bar in bars
    ]


def to_domain_bar(bar: Bar, instrument_id: str) -> OhlcvBar:
    return OhlcvBar(
        instrument_id=instrument_id,
        ts_utc=nanos_to_datetime(bar.ts_event),
        open=_as_decimal(bar.open),
        high=_as_decimal(bar.high),
        low=_as_decimal(bar.low),
        close=_as_decimal(bar.close),
        volume=_as_decimal(bar.volume),
    )


def _as_decimal(value: object) -> Decimal:
    converter = getattr(value, "as_decimal", None)
    if callable(converter):
        converted = converter()
        return converted if isinstance(converted, Decimal) else Decimal(str(converted))
    return Decimal(str(value))


def to_engine_ticks(
    trades: list[AggTrade],
    *,
    instrument: CurrencyPair,
) -> list[TradeTick]:
    """Convert domain trades into engine ticks, dropping sizes the venue cannot carry.

    `AggTrade` keeps price and quantity as the exact strings Binance sent (see
    `domain/ticks.py`), while Nautilus requires a real number, and its `trade_id` must
    be a `TradeId` rather than a `str`. Both mistakes were in this one function, so
    every tick-filtered run failed on the first trade — and nothing caught it earlier
    because no tick series existed in the catalog to feed it.

    A third, subtler case: many ETHUSDT prints are smaller than the instrument's 0.001
    size increment, so `Quantity` rounds them to zero and `TradeTick` refuses them
    outright with "'size' not a positive integer, was 0". One such print used to abort
    the whole run. They are skipped and counted out loud, because dropping volume
    silently would quietly bias the flow features built on top of them.
    """
    ticks: list[TradeTick] = []
    dropped = 0
    for trade in trades:
        size = Quantity(_as_decimal(trade.qty), precision=instrument.size_precision)
        if _as_decimal(size) <= 0:
            dropped += 1
            continue
        ticks.append(
            TradeTick(
                instrument_id=instrument.id,
                price=Price(_as_decimal(trade.price), precision=instrument.price_precision),
                size=size,
                aggressor_side=(
                    AggressorSide.SELLER if trade.is_buyer_maker else AggressorSide.BUYER
                ),
                trade_id=TradeId(str(trade.agg_id)),
                ts_event=datetime_to_nanos(trade.ts_utc),
                ts_init=datetime_to_nanos(trade.ts_utc),
            )
        )
    if dropped:
        _log.warning(
            "dropped %d of %d ticks below the %s size increment; they carry no "
            "representable volume rather than zero",
            dropped,
            len(trades),
            instrument.size_increment,
        )
    return ticks


#: `OrderBookDepth10` is a fixed ten-level container. Binance snapshots arrive with up
#: to 20 levels a side, and passing them straight through raises
#: "bids length greater than maximum 10", killing every run that feeds books.
BOOK_DEPTH = 10


def to_engine_books(
    snapshots: list[OrderBookSnapshot],
    *,
    instrument: CurrencyPair,
) -> list[OrderBookDepth10]:
    """Convert domain snapshots into ten-level engine snapshots.

    Levels beyond the tenth are dropped: the engine type cannot carry them, and the
    microstructure features read at most the top five. The truncation is stated here
    rather than left implicit in a crash.
    """
    return [
        OrderBookDepth10(
            instrument_id=instrument.id,
            bids=[
                BookOrder(
                    side=OrderSide.BUY,
                    price=Price(level.price, precision=instrument.price_precision),
                    size=Quantity(level.size, precision=instrument.size_precision),
                    order_id=0,
                )
                for level in snapshot.bids[:BOOK_DEPTH]
            ],
            asks=[
                BookOrder(
                    side=OrderSide.SELL,
                    price=Price(level.price, precision=instrument.price_precision),
                    size=Quantity(level.size, precision=instrument.size_precision),
                    order_id=0,
                )
                for level in snapshot.asks[:BOOK_DEPTH]
            ],
            bid_counts=[1] * min(len(snapshot.bids), BOOK_DEPTH),
            ask_counts=[1] * min(len(snapshot.asks), BOOK_DEPTH),
            flags=0,
            sequence=0,
            ts_event=datetime_to_nanos(snapshot.ts_utc),
            ts_init=datetime_to_nanos(snapshot.ts_utc),
        )
        for snapshot in snapshots
    ]


def to_domain_snapshot(depth: OrderBookDepth10, instrument_id: str) -> OrderBookSnapshot:
    """Convert an engine depth snapshot back into the domain type.

    `OrderBookDepth10` is a fixed-width container: fewer than ten supplied levels are
    padded with zero-price, zero-size orders. Those rows are container filler, not
    market data — kept, they make `OrderBookSnapshot.validate()` fail ("asks must be
    ascending") on the strategy's first book event and push empty levels into the
    imbalance metrics — so they are dropped here.
    """
    return OrderBookSnapshot(
        instrument_id=instrument_id,
        ts_utc=nanos_to_datetime(depth.ts_event),
        bids=_domain_levels(depth.bids),
        asks=_domain_levels(depth.asks),
    )


def _domain_levels(levels: Sequence[BookOrder]) -> tuple[BookLevel, ...]:
    return tuple(
        BookLevel(price=_as_decimal(level.price), size=_as_decimal(level.size))
        for level in levels
        if _as_decimal(level.size) > 0
    )
