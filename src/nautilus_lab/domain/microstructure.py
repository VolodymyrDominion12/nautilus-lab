from __future__ import annotations

from decimal import Decimal

from nautilus_lab.domain.order_book import OrderBookSnapshot


def order_book_imbalance(snapshot: OrderBookSnapshot, *, depth: int = 10) -> Decimal:
    bids = snapshot.bids[:depth]
    asks = snapshot.asks[:depth]
    bid_vol = sum(level.size for level in bids)
    ask_vol = sum(level.size for level in asks)
    total = bid_vol + ask_vol
    if total <= 0:
        return Decimal("0")
    return Decimal(str((bid_vol - ask_vol) / total))


def weighted_order_flow_imbalance(
    current: OrderBookSnapshot,
    previous: OrderBookSnapshot,
    *,
    depth: int = 5,
) -> Decimal:
    obi_now = order_book_imbalance(current, depth=depth)
    obi_prev = order_book_imbalance(previous, depth=depth)
    return obi_now - obi_prev


def liquidity_fade_velocity(
    current: OrderBookSnapshot,
    previous: OrderBookSnapshot,
    *,
    depth: int = 5,
) -> Decimal:
    bid_now = sum(level.size for level in current.bids[:depth])
    ask_now = sum(level.size for level in current.asks[:depth])
    bid_prev = sum(level.size for level in previous.bids[:depth])
    ask_prev = sum(level.size for level in previous.asks[:depth])
    fade_bid = bid_prev - bid_now
    fade_ask = ask_prev - ask_now
    return Decimal(str(fade_bid - fade_ask))
