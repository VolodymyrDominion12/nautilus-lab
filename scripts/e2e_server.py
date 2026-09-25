"""The dashboard API on synthetic markets, for the browser smoke test (docs/27 E-2.4).

    uv run python scripts/e2e_server.py --port 8765 --origin http://127.0.0.1:4173

This is the real app from `create_app`, with its real routers, security gate,
WebSocket and live paper sessions. The only replacement is Binance: warm-up history
and the kline stream come from `synthetic_ohlcv` in this process, and the stream
replays one closed minute bar per tick. A CI runner then
needs no network, and the result does not depend on what the market did today.

Nothing is persisted. There are no journals and no portfolio, and the job store lives
in a temporary directory. A session started here is gone when the process exits. The
dashboard still reads the repository's own specs and existing reports.

`frontend/playwright.config.ts` starts this script. `tests/unit/test_e2e_server.py`
checks the same wiring without a browser, so the fixture breaks in `pytest` first.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import tempfile
import time
import zlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI

from nautilus_lab.api.app import create_app
from nautilus_lab.api.context import ROOT_DIR, LabContext
from nautilus_lab.api.job_store import JobStore
from nautilus_lab.api.jobs import JobManager
from nautilus_lab.api.live_sessions import SessionRegistry
from nautilus_lab.api.market_feed import FeedHub
from nautilus_lab.api.paper_streamer import WARMUP_BARS
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_ohlcv
from nautilus_lab.infrastructure.settings import Settings

#: `synthetic_ohlcv` spaces bars one minute apart, so only 1m markets are served.
BAR_SECONDS = 60
#: Closed bars the stream replays after the warm-up: 50 minutes at the default tick.
LIVE_BARS = 3_000
DEFAULT_TICK_SECONDS = 1.0


class SyntheticMarket:
    """One symbol: warm-up history, then the closed bars the stream replays after it.

    The whole sequence lies in the past and ends at the last closed minute.
    `synthetic_ohlcv` refuses future timestamps, and so does the session: a bar
    "from the future" is how a lookahead bug would look. Replaying already-closed
    bars quickly keeps both checks intact.
    """

    def __init__(self, symbol: str, *, now: float, history: int = WARMUP_BARS) -> None:
        count = history + LIVE_BARS
        # A stable seed per symbol: the same run replays the same prices.
        generated = synthetic_ohlcv(
            instrument_id=symbol, count=count, seed=zlib.crc32(symbol.encode())
        )
        # `synthetic_ohlcv` dates its bars in 2024. Moved as one block, so that the
        # last one opens at the last closed minute; spacing and prices stay as made.
        last_open = datetime.fromtimestamp(
            int(now // BAR_SECONDS) * BAR_SECONDS - BAR_SECONDS, tz=UTC
        )
        shift = last_open - generated[-1].ts_utc
        bars = [dataclasses.replace(bar, ts_utc=bar.ts_utc + shift) for bar in generated]
        self.history: list[OhlcvBar] = bars[:history]
        self.live: list[OhlcvBar] = bars[history:]


def kline_message(bar: OhlcvBar) -> str:
    """A closed Binance kline, as `paper_streamer.parse_kline_message` reads it."""
    return json.dumps(
        {
            "e": "kline",
            "s": bar.instrument_id,
            "k": {
                "t": int(bar.ts_utc.timestamp()) * 1000,
                "o": str(bar.open),
                "h": str(bar.high),
                "l": str(bar.low),
                "c": str(bar.close),
                "v": str(bar.volume),
                "x": True,
            },
        }
    )


class _Replay:
    """A `MessageSource` that hands out one closed bar per tick, then goes quiet."""

    def __init__(self, bars: list[OhlcvBar], tick_seconds: float) -> None:
        self._bars = iter(bars)
        self._tick = tick_seconds

    async def recv(self) -> str:
        await asyncio.sleep(self._tick)
        bar = next(self._bars, None)
        if bar is None:
            await asyncio.Event().wait()  # replay exhausted: a silent, open socket
        assert bar is not None  # noqa: S101 — unreachable, the wait above never returns
        return kline_message(bar)


class SyntheticMarkets:
    """The history loader and the feed `connect` for every symbol a session asks for."""

    def __init__(self, *, tick_seconds: float = DEFAULT_TICK_SECONDS) -> None:
        self.tick_seconds = tick_seconds
        self._markets: dict[str, SyntheticMarket] = {}

    def market(self, symbol: str) -> SyntheticMarket:
        key = symbol.upper()
        if key not in self._markets:
            self._markets[key] = SyntheticMarket(key, now=time.time())
        return self._markets[key]

    async def history(self, symbol: str, interval: str, count: int) -> list[OhlcvBar]:
        if interval != "1m":
            raise ValueError(f"the e2e server only synthesises 1m bars, not {interval!r}")
        return self.market(symbol).history[-count:]

    @asynccontextmanager
    async def connect(self, url: str) -> AsyncIterator[_Replay]:
        # MarketFeed.url: wss://.../<symbol>@kline_<interval>
        stream = url.rsplit("/", 1)[-1]
        symbol, _, interval = stream.partition("@kline_")
        if interval != "1m":
            raise ValueError(f"the e2e server only streams 1m bars, not {interval!r}")
        yield _Replay(self.market(symbol).live, self.tick_seconds)


def build_app(
    *,
    origins: str,
    workdir: Path,
    tick_seconds: float = DEFAULT_TICK_SECONDS,
) -> FastAPI:
    """The real API with synthetic markets and every write under `workdir`."""
    cfg = Settings(  # type: ignore[call-arg]
        _env_file=None,
        api_allowed_origins=origins,
        api_token="",
        lab_role="full",
        live_paper_journal="",
        live_paper_sessions_dir="",
        live_paper_portfolio="",
        live_paper_watchdog_seconds=0,
    )
    jobs = JobManager(
        reports_dir=workdir / "reports",
        python="python",
        store=JobStore(workdir / "jobs.sqlite"),
    )
    # ROOT_DIR, so the specs and strategies the dashboard lists are the real ones.
    app = create_app(cfg, root=ROOT_DIR, jobs=jobs)
    markets = SyntheticMarkets(tick_seconds=tick_seconds)
    ctx: LabContext = app.state.lab
    app.state.lab = dataclasses.replace(
        ctx,
        sessions=SessionRegistry(
            sessions_dir=None,
            history_loader=markets.history,
            feed_hub=FeedHub(connect=markets.connect, max_feeds=cfg.live_paper_max_feeds),
            max_sessions=cfg.live_paper_max_sessions,
        ),
    )
    app.state.synthetic_markets = markets
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--origin",
        action="append",
        default=[],
        help="dashboard origin allowed to call the API (repeatable)",
    )
    parser.add_argument("--tick", type=float, default=DEFAULT_TICK_SECONDS)
    args = parser.parse_args(argv)

    import uvicorn

    origins = ",".join(args.origin) or "http://127.0.0.1:4173,http://localhost:4173"
    with tempfile.TemporaryDirectory(prefix="nautilus-e2e-") as workdir:
        app = build_app(origins=origins, workdir=Path(workdir), tick_seconds=args.tick)
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
