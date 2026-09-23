from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from nautilus_lab.infrastructure.binance_ws import (
    BinanceAggTradeStream,
    KlinePayloadError,
    agg_trade_stream_url,
    parse_agg_trade_message,
)

AGG_FRAME: dict[str, Any] = {
    "e": "aggTrade",
    "E": 1789603200843,
    "s": "ETHUSDT",
    "a": 2082309801,
    "p": "2733.63000000",
    "q": "1.25000000",
    "f": 100,
    "l": 105,
    "T": 1789603200843,
    "m": False,
    "M": True,
}


def _stream(*messages: dict[str, Any]) -> BinanceAggTradeStream:
    class _FakeSocket:
        def __init__(self) -> None:
            self._frames = [json.dumps(item) for item in messages]

        def __enter__(self) -> _FakeSocket:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def recv(self) -> str:
            if not self._frames:
                raise AssertionError("stream asked for more frames than the fake holds")
            return self._frames.pop(0)

        def close(self) -> None:
            return None

    return BinanceAggTradeStream("ETHUSDT", connect_fn=lambda _url: _FakeSocket())


def test_agg_trade_stream_url_is_public_and_unauthenticated() -> None:
    assert agg_trade_stream_url("ETHUSDT") == "wss://stream.binance.com:9443/ws/ethusdt@aggTrade"


def test_parse_agg_trade_keeps_exact_price_and_direction() -> None:
    """`m` is the entire directional content of the event; it must survive exactly."""
    trade = parse_agg_trade_message(AGG_FRAME)

    assert trade.instrument_id == "ETH/USDT.SIM"
    assert trade.agg_id == 2082309801
    assert trade.price == "2733.63000000"
    assert trade.qty == "1.25000000"
    assert trade.is_buyer_maker is False
    assert trade.is_aggressive_buy is True
    assert trade.ts_utc == datetime.fromtimestamp(1789603200843 / 1000, tz=UTC)


def test_parse_agg_trade_unwraps_the_combined_stream_envelope() -> None:
    trade = parse_agg_trade_message({"stream": "ethusdt@aggTrade", "data": AGG_FRAME})
    assert trade.agg_id == 2082309801


def test_parse_agg_trade_refuses_to_guess_direction() -> None:
    """A missing or non-boolean maker flag is an error, never a default."""
    broken = dict(AGG_FRAME)
    broken.pop("m")
    with pytest.raises(KlinePayloadError, match="'m' must be a boolean"):
        parse_agg_trade_message(broken)

    with pytest.raises(KlinePayloadError, match="'m' must be a boolean"):
        parse_agg_trade_message({**AGG_FRAME, "m": "true"})


def test_parse_agg_trade_rejects_a_broken_frame() -> None:
    with pytest.raises(KlinePayloadError):
        parse_agg_trade_message({"e": "aggTrade"})  # no symbol

    with pytest.raises(KlinePayloadError, match="no symbol"):
        parse_agg_trade_message({**AGG_FRAME, "s": ""})


def test_stream_yields_trades_and_skips_a_replayed_id() -> None:
    """A repeated `agg_id` must not reach VPIN twice."""
    later = {**AGG_FRAME, "a": AGG_FRAME["a"] + 1, "T": AGG_FRAME["T"] + 500}
    replay = dict(AGG_FRAME)
    stream = _stream(AGG_FRAME, replay, later)

    trades = []
    for trade in stream.trades():
        trades.append(trade)
        if len(trades) == 2:
            stream.stop()

    assert [trade.agg_id for trade in trades] == [AGG_FRAME["a"], AGG_FRAME["a"] + 1]


def test_stream_stop_ends_the_loop() -> None:
    stream = _stream(AGG_FRAME)
    iterator = stream.trades()
    first = next(iterator)
    assert first.agg_id == AGG_FRAME["a"]
    stream.stop()
    with pytest.raises(StopIteration):
        next(iterator)
