"""One Binance kline socket per symbol+interval, shared by every session that trades it.

Two robots on ETHUSDT 1h used to mean two sockets, two slightly different streams of
the same bars and twice the connections counted against the public limit. A feed
reads the stream once and hands every message to all its subscribers, so sessions on
one market see exactly the same bars — the precondition for comparing them at all.

The socket opens when the first session subscribes and closes when the last one
leaves. A subscriber that raises is logged and kept: one broken session must not
starve the others of data.

Every feed remembers when it started, when its last message arrived and when its last
*closed* bar arrived. A socket can stay "connected" while delivering nothing; those
timestamps are what `api/health.py` judges liveness by (docs/27 E-1.5).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from nautilus_lab.api.paper_streamer import BINANCE_WS_STREAM_URL, parse_kline_message

logger = logging.getLogger(__name__)

FeedKey = tuple[str, str]


class FeedSubscriber(Protocol):
    config: Any

    async def on_market_update(self, update: dict[str, Any]) -> None: ...


class MessageSource(Protocol):
    """An open stream of raw messages (a websocket, or a fake in tests)."""

    async def recv(self) -> str | bytes: ...


#: Opens a stream for a URL; used as `async with connect(url) as source`.
Connect = Callable[[str], AbstractAsyncContextManager[MessageSource]]
#: Wall-clock seconds; injected so tests can move time.
Clock = Callable[[], float]


def _default_connect(url: str) -> AbstractAsyncContextManager[MessageSource]:
    import websockets

    connection: AbstractAsyncContextManager[MessageSource] = websockets.connect(
        url, ping_interval=20, ping_timeout=10
    )
    return connection


def feed_key(symbol: str, interval: str) -> FeedKey:
    return symbol.upper(), interval


class MarketFeed:
    def __init__(self, key: FeedKey, *, connect: Connect, clock: Clock = time.time) -> None:
        self.key = key
        self.subscribers: list[FeedSubscriber] = []
        self.connected = False
        self.messages = 0
        self.reconnects = 0
        self.started_at: float | None = None
        self.last_message_at: float | None = None
        self.last_closed_at: float | None = None
        self._connect = connect
        self._clock = clock
        self._task: asyncio.Task[None] | None = None

    @property
    def url(self) -> str:
        symbol, interval = self.key
        return f"{BINANCE_WS_STREAM_URL}/{symbol.lower()}@kline_{interval}"

    def start(self) -> None:
        if self._task is None or self._task.done():
            if self.started_at is None:
                self.started_at = self._clock()
            self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        self.connected = False

    async def dispatch(self, raw: str | bytes) -> None:
        update = parse_kline_message(raw)
        if update is None:
            return
        self.messages += 1
        now = self._clock()
        self.last_message_at = now
        if update.get("is_closed"):
            self.last_closed_at = now
        for subscriber in list(self.subscribers):
            try:
                await subscriber.on_market_update(dict(update))
            except Exception:
                logger.exception("Session on %s failed on a market update", self.key)

    async def _messages(self, source: MessageSource) -> AsyncIterator[str | bytes]:
        while True:
            yield await source.recv()

    async def _run(self) -> None:
        backoff = 1
        while True:
            try:
                async with self._connect(self.url) as source:
                    self.connected = True
                    backoff = 1
                    logger.info("Market feed connected: %s", self.url)
                    async for raw in self._messages(source):
                        await self.dispatch(raw)
            except asyncio.CancelledError:
                self.connected = False
                raise
            except Exception as exc:  # noqa: BLE001 — any feed error means reconnect
                self.connected = False
                self.reconnects += 1
                logger.warning("Feed %s error: %s. Reconnecting in %ss", self.key, exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)


class FeedHub:
    """Feeds by symbol+interval; a feed lives exactly as long as it has subscribers."""

    def __init__(
        self, *, connect: Connect | None = None, max_feeds: int = 5, clock: Clock = time.time
    ) -> None:
        self.feeds: dict[FeedKey, MarketFeed] = {}
        self.max_feeds = max_feeds
        self._connect = connect or _default_connect
        self._clock = clock

    def can_add(self, symbol: str, interval: str) -> bool:
        return feed_key(symbol, interval) in self.feeds or len(self.feeds) < self.max_feeds

    def subscribe(self, subscriber: FeedSubscriber) -> MarketFeed:
        key = feed_key(subscriber.config.symbol, subscriber.config.interval)
        feed = self.feeds.get(key)
        if feed is None:
            if len(self.feeds) >= self.max_feeds:
                raise ValueError(
                    f"at most {self.max_feeds} symbol+interval feeds at once; "
                    f"stop a session on another market before adding {key[0]} {key[1]}"
                )
            feed = MarketFeed(key, connect=self._connect, clock=self._clock)
            self.feeds[key] = feed
        if subscriber not in feed.subscribers:
            feed.subscribers.append(subscriber)
        feed.start()
        return feed

    def unsubscribe(self, subscriber: FeedSubscriber) -> None:
        for key, feed in list(self.feeds.items()):
            if subscriber in feed.subscribers:
                feed.subscribers.remove(subscriber)
            if not feed.subscribers:
                feed.stop()
                del self.feeds[key]

    def status(self) -> list[dict[str, Any]]:
        return [
            {
                "symbol": key[0],
                "interval": key[1],
                "connected": feed.connected,
                "sessions": len(feed.subscribers),
                "messages": feed.messages,
                "reconnects": feed.reconnects,
                "started_at": feed.started_at,
                "last_message_at": feed.last_message_at,
                "last_closed_at": feed.last_closed_at,
            }
            for key, feed in self.feeds.items()
        ]
