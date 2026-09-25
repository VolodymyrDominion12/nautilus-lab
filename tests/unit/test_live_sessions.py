"""Several live paper sessions: registry, shared feeds, portfolio file, benchmark."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from nautilus_lab.api.live_paper_boot import (
    boot_sessions,
    load_portfolio,
    parse_portfolio,
    registry_from_settings,
)
from nautilus_lab.api.live_sessions import SessionRegistry
from nautilus_lab.api.market_feed import FeedHub
from nautilus_lab.api.paper_streamer import (
    LivePaperConfig,
    LivePaperSessionManager,
    default_session_name,
)
from nautilus_lab.api.security import ApiSecurity
from nautilus_lab.infrastructure.live_paper_journal import LivePaperJournal
from nautilus_lab.infrastructure.settings import Settings

T0 = datetime(2026, 9, 24, 10, tzinfo=UTC)


def _kline(ts: datetime, close: str, *, closed: bool = True, symbol: str = "ETHUSDT") -> str:
    ms = int(ts.timestamp() * 1000)
    return json.dumps(
        {
            "e": "kline",
            "s": symbol,
            "k": {"t": ms, "o": close, "h": close, "l": close, "c": close, "v": "5", "x": closed},
        }
    )


class FakeSource:
    """A socket that delivers queued messages, then waits forever."""

    def __init__(self, queue: asyncio.Queue[str]) -> None:
        self.queue = queue

    async def recv(self) -> str:
        return await self.queue.get()


class FakeMarket:
    def __init__(self) -> None:
        self.queues: dict[str, asyncio.Queue[str]] = {}
        self.opened: list[str] = []

    def queue(self, url: str) -> asyncio.Queue[str]:
        return self.queues.setdefault(url, asyncio.Queue())

    def connect(self, url: str) -> object:
        @asynccontextmanager
        async def _open() -> AsyncIterator[FakeSource]:
            self.opened.append(url)
            yield FakeSource(self.queue(url))

        return _open()


def _registry(tmp_path: Path | None, market: FakeMarket, **kwargs: object) -> SessionRegistry:
    return SessionRegistry(
        sessions_dir=None if tmp_path is None else tmp_path / "sessions",
        feed_hub=FeedHub(connect=market.connect),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


def _config(name: str, robot: str = "ema", symbol: str = "ETHUSDT") -> LivePaperConfig:
    return LivePaperConfig(
        name=name,
        robot=robot,
        symbol=symbol,
        interval="1h",
        starting_equity=Decimal("10000"),
        fast_ema=2,
        slow_ema=3,
    )


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def test_default_names_are_stable_and_readable() -> None:
    assert default_session_name("regime", "ETHUSDT", "1h") == "regime-eth"
    assert default_session_name("ema", "btcusdt", "15m") == "ema-btc-15m"


def test_two_sessions_share_one_feed_and_see_the_same_bars(tmp_path: Path) -> None:
    market = FakeMarket()

    async def scenario() -> tuple[SessionRegistry, list[LivePaperSessionManager]]:
        registry = _registry(tmp_path, market)
        a = await registry.create(_config("ema-a"))
        b = await registry.create(_config("hold-eth", robot="hold"))
        await _settle()
        url = next(iter(market.queues)) if market.queues else ""
        for hour in range(6):
            market.queue(url).put_nowait(_kline(T0 + timedelta(hours=hour), str(3000 + hour)))
        await _settle()
        await asyncio.sleep(0.05)
        return registry, [a, b]

    _registry_used, (a, b) = asyncio.run(scenario())
    assert len(market.opened) == 1, "one socket for two sessions on ETHUSDT 1h"
    assert [bar.time for bar in a.recent_bars] == [bar.time for bar in b.recent_bars]
    assert len(a.recent_bars) == 6
    assert b.position is not None, "hold buys and keeps"
    assert b.position.side == "LONG", "hold buys and keeps"
    assert b.position.stop_loss is None, "the benchmark has no stop"
    assert b.current_equity > 0


def test_names_are_unique_among_running_sessions_and_limits_hold(tmp_path: Path) -> None:
    market = FakeMarket()

    async def scenario() -> None:
        registry = _registry(tmp_path, market, max_sessions=2)
        await registry.create(_config("one"))
        with pytest.raises(ValueError, match="already running"):
            await registry.create(_config("one"))
        await registry.create(_config("two"))
        with pytest.raises(ValueError, match="at most 2 sessions"):
            await registry.create(_config("three"))
        await registry.stop("one")
        await registry.create(_config("one"))  # a stopped name may be reused

    asyncio.run(scenario())


def test_feed_limit_counts_markets_not_sessions(tmp_path: Path) -> None:
    market = FakeMarket()

    async def scenario() -> None:
        registry = SessionRegistry(
            sessions_dir=None,
            feed_hub=FeedHub(connect=market.connect, max_feeds=1),  # type: ignore[arg-type]
        )
        await registry.create(_config("a"))
        await registry.create(_config("b"))  # same market: fine
        with pytest.raises(ValueError, match="symbol\\+interval"):
            await registry.create(_config("c", symbol="BTCUSDT"))

    asyncio.run(scenario())


def test_stopping_one_session_leaves_the_others_and_closes_idle_feeds(tmp_path: Path) -> None:
    market = FakeMarket()

    async def scenario() -> tuple[SessionRegistry, FeedHub]:
        hub = FeedHub(connect=market.connect)  # type: ignore[arg-type]
        registry = SessionRegistry(sessions_dir=tmp_path / "s", feed_hub=hub)
        await registry.create(_config("eth-a"))
        await registry.create(_config("eth-b"))
        await registry.create(_config("btc", symbol="BTCUSDT"))
        await _settle()
        await registry.stop("btc")
        await registry.stop("eth-a")
        return registry, hub

    registry, hub = asyncio.run(scenario())
    assert [m.config.name for m in registry.active()] == ["eth-b"]
    assert list(hub.feeds) == [("ETHUSDT", "1h")]


def test_pause_blocks_entries_but_not_exits(tmp_path: Path) -> None:
    market = FakeMarket()

    async def scenario() -> LivePaperSessionManager:
        registry = _registry(tmp_path, market)
        manager = await registry.create(_config("p", robot="hold"))
        await registry.set_paused("p", True)
        manager.process_kline_update(
            time_sec=int(T0.timestamp()),
            open_price=Decimal("3000"),
            high_price=Decimal("3000"),
            low_price=Decimal("3000"),
            close_price=Decimal("3000"),
            volume=Decimal("1"),
            is_closed=True,
        )
        return manager

    manager = asyncio.run(scenario())
    assert manager.position is None
    assert manager.status_message == "Paused: entry skipped"
    assert manager.to_state_dict()["paused"] is True


def test_restart_resumes_every_session_and_the_portfolio_does_not_duplicate(
    tmp_path: Path,
) -> None:
    market = FakeMarket()
    portfolio = [_config("regime-eth", robot="regime"), _config("hold-eth", robot="hold")]

    async def first_run() -> list[str]:
        registry = _registry(tmp_path, market)
        outcomes = await registry.reconcile(portfolio)
        await registry.create(_config("adhoc"))
        await registry.stop("adhoc")
        return outcomes

    async def second_run() -> tuple[SessionRegistry, list[str], list[str]]:
        registry = _registry(tmp_path, market)
        restored = await registry.restore()
        reconciled = await registry.reconcile([*portfolio, _config("adhoc")])
        return registry, restored, reconciled

    first = asyncio.run(first_run())
    assert [line.split()[0] for line in first] == ["started", "started"]
    registry, restored, reconciled = asyncio.run(second_run())
    assert sorted(line.split()[1] for line in restored) == ["hold-eth", "regime-eth"]
    assert reconciled[0] == "running regime-eth"
    assert reconciled[1] == "running hold-eth"
    assert reconciled[2].startswith("skipped adhoc: stopped by a person")
    assert len(registry.active()) == 2


def test_changed_parameters_in_the_file_are_reported_not_applied(tmp_path: Path) -> None:
    market = FakeMarket()

    async def scenario() -> list[str]:
        registry = _registry(tmp_path, market)
        await registry.reconcile([_config("x", robot="ema")])
        return await registry.reconcile([_config("x", robot="regime")])

    outcome = asyncio.run(scenario())
    assert outcome[0].startswith("kept x:")


def test_single_file_session_from_before_is_resumed_and_named(tmp_path: Path) -> None:
    legacy = tmp_path / "live_events.jsonl"
    old = LivePaperSessionManager(journal=LivePaperJournal(legacy))
    old._launch_stream = lambda: None  # type: ignore[method-assign]
    asyncio.run(old.start(LivePaperConfig(symbol="ETHUSDT", interval="1h", robot="regime")))
    market = FakeMarket()

    async def upgraded() -> tuple[SessionRegistry, list[str]]:
        registry = SessionRegistry(
            sessions_dir=tmp_path / "sessions",
            legacy_journal=legacy,
            feed_hub=FeedHub(connect=market.connect),  # type: ignore[arg-type]
        )
        await registry.restore()
        return registry, await registry.reconcile([_config("regime-eth", robot="regime")])

    registry, outcome = asyncio.run(upgraded())
    assert outcome == ["running regime-eth"], "the running session is recognised, not doubled"
    manager = registry.find("regime-eth")
    assert manager is not None
    assert manager.session_id == old.session_id
    assert manager.journal is not None
    assert manager.journal.path == legacy


def test_summaries_compare_each_robot_with_the_benchmark(tmp_path: Path) -> None:
    market = FakeMarket()

    async def scenario() -> list[dict[str, object]]:
        registry = _registry(tmp_path, market)
        robot = await registry.create(_config("ema-eth"))
        bench = await registry.create(_config("hold-eth", robot="hold"))
        robot.balance = Decimal("10300")
        bench.balance = Decimal("10100")
        await registry.create(_config("gone"))
        await registry.stop("gone")
        return registry.summaries()

    rows = {row["name"]: row for row in asyncio.run(scenario())}
    assert rows["ema-eth"]["return_pct"] == 3.0
    assert rows["ema-eth"]["vs_benchmark_pp"] == 2.0
    assert rows["hold-eth"]["vs_benchmark_pp"] is None
    assert rows["gone"]["status"] == "stopped"


def test_portfolio_warns_when_all_robots_on_a_symbol_point_one_way(tmp_path: Path) -> None:
    market = FakeMarket()

    async def scenario() -> dict[str, object]:
        registry = _registry(tmp_path, market)
        for name in ("a", "b"):
            manager = await registry.create(_config(name))
            manager._open_position_internal("LONG", Decimal("3000"))
        await registry.create(_config("hold-eth", robot="hold"))
        return registry.portfolio()

    view = asyncio.run(scenario())
    assert view["exposure"] == {"ETHUSDT": {"long": 2, "short": 0, "flat": 0}}
    assert view["warnings"] == ["all 2 robots on ETHUSDT are long"]
    assert view["sessions_active"] == 3


def test_portfolio_file_is_parsed_strictly() -> None:
    cfg = Settings(_env_file=None, risk_per_trade=Decimal("0.003"))  # type: ignore[call-arg]
    configs = parse_portfolio(
        {
            "defaults": {"starting_equity": 5000},
            "sessions": [
                {"name": "regime-eth", "robot": "regime", "symbol": "ETHUSDT", "interval": "1h"},
                {"name": "hold-eth", "robot": "hold", "symbol": "ethusdt", "notes": "benchmark"},
            ],
        },
        cfg,
    )
    assert [c.name for c in configs] == ["regime-eth", "hold-eth"]
    assert configs[0].starting_equity == Decimal("5000")
    assert configs[0].risk_per_trade == Decimal("0.003"), "risk comes from the tested settings"
    assert configs[1].symbol == "ETHUSDT"
    assert configs[1].notes == "benchmark"
    assert configs[0].created_from == "portfolio"
    for bad, message in [
        ({"sessions": [{"robot": "ema"}]}, "name"),
        ({"sessions": [{"name": "a", "robot": "ema", "risk_per_trad": 1}]}, "unknown keys"),
        ({"sessions": [{"name": "a", "robot": "pairs"}]}, "not available live"),
        ({"sessions": [{"name": "a", "robot": "ema"}, {"name": "a", "robot": "ema"}]}, "dup"),
        ({"robots": []}, "sessions"),
    ]:
        with pytest.raises(ValueError, match=message):
            parse_portfolio(bad, cfg)


def test_boot_uses_the_file_and_falls_back_to_autostart(tmp_path: Path) -> None:
    (tmp_path / "portfolio.yaml").write_text(
        "sessions:\n  - {name: ema-eth, robot: ema, symbol: ETHUSDT, interval: 1h}\n",
        encoding="utf-8",
    )
    with_file = Settings(
        _env_file=None,  # type: ignore[call-arg]
        live_paper_portfolio="portfolio.yaml",
        live_paper_autostart=True,
    )
    assert [c.name for c in load_portfolio(with_file, root=tmp_path)] == ["ema-eth"]
    autostart = Settings(_env_file=None, live_paper_autostart=True)  # type: ignore[call-arg]
    assert [c.name for c in load_portfolio(autostart, root=tmp_path)] == ["regime-eth"]
    off = Settings(_env_file=None)  # type: ignore[call-arg]
    assert load_portfolio(off, root=tmp_path) == []

    broken = Settings(
        _env_file=None,  # type: ignore[call-arg]
        live_paper_portfolio="missing.yaml",
        live_paper_journal="data/paper/live_events.jsonl",
    )
    registry = registry_from_settings(broken, root=tmp_path, history_loader=None)
    assert registry.sessions_dir == tmp_path / "data/paper/sessions"
    outcome = asyncio.run(boot_sessions(registry, broken, root=tmp_path))
    assert outcome[-1].startswith("portfolio error"), "a bad file is reported, never fatal"


def test_paper_role_allows_the_session_controls_and_nothing_else() -> None:
    paper = ApiSecurity.from_values(origins="", token="", role="paper")
    for path in [
        "/api/paper/sessions",
        "/api/paper/sessions/regime-eth/stop",
        "/api/paper/sessions/regime-eth-a1b2c3/pause",
        "/api/paper/sessions/x/resume",
        "/api/paper/sessions/x/close-position",
        "/api/paper/sessions/x/update-stops",
    ]:
        assert paper.refusal(method="POST", path=path, origin=None, presented_token=None) is None
    for path in ["/api/paper/sessions/x/delete", "/api/paper/sessions/../settings/stop"]:
        assert paper.refusal(method="POST", path=path, origin=None, presented_token=None)
