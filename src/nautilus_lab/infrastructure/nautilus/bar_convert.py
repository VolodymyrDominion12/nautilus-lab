from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Price, Quantity

from nautilus_lab.domain.bars import OhlcvBar


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
