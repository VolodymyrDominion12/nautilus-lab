"""Live paper terminal survives a restart: journal, resume, autostart."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from nautilus_lab.api.live_paper_boot import (
    autostart_config,
    boot_live_paper,
    journal_from_settings,
)
from nautilus_lab.api.paper_streamer import (
    LivePaperConfig,
    LivePaperSessionManager,
    config_from_dict,
    config_to_dict,
)
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.regime import RegimeParams
from nautilus_lab.infrastructure.live_paper_journal import LivePaperJournal
from nautilus_lab.infrastructure.settings import Settings

T0 = datetime(2026, 9, 24, 10, tzinfo=UTC)


def _config() -> LivePaperConfig:
    return LivePaperConfig(
        symbol="ETHUSDT",
        interval="1h",
        starting_equity=Decimal("10000"),
        risk_per_trade=Decimal("0.02"),
        stop_pct=Decimal("0.02"),
        take_profit_multiple=Decimal("2"),
        regime=RegimeParams(er_period=15),
    )


def _manager(journal: LivePaperJournal | None, **kwargs: object) -> LivePaperSessionManager:
    manager = LivePaperSessionManager(journal=journal, **kwargs)  # type: ignore[arg-type]
    # No socket in unit tests: the stream task is the only thing that touches the network.
    manager._launch_stream = lambda: None  # type: ignore[method-assign]
    return manager


def _bar(ts: datetime, *, high: str, low: str, close: str) -> OhlcvBar:
    return OhlcvBar(
        instrument_id="ETHUSDT",
        ts_utc=ts,
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("10"),
    )


def _close_bar(manager: LivePaperSessionManager, ts: datetime, close: str) -> None:
    manager.process_kline_update(
        time_sec=int(ts.timestamp()),
        open_price=Decimal(close),
        high_price=Decimal(close) + 1,
        low_price=Decimal(close) - 1,
        close_price=Decimal(close),
        volume=Decimal("5"),
        is_closed=True,
    )


def test_config_round_trips_through_the_journal_format() -> None:
    config = _config()
    raw = json.loads(json.dumps(config_to_dict(config)))
    restored = config_from_dict(raw)
    assert restored == config
    assert isinstance(restored.stop_pct, Decimal)
    assert restored.regime.er_period == 15


def test_nothing_to_resume_without_a_file_or_after_a_manual_stop(tmp_path: Path) -> None:
    journal = LivePaperJournal(tmp_path / "live.jsonl")
    assert journal.load_resumable() is None

    manager = _manager(journal)
    asyncio.run(manager.start(_config()))
    assert journal.load_resumable() is not None
    asyncio.run(manager.stop())
    assert journal.load_resumable() is None, "a session a person stopped is final"


def test_restart_resumes_account_position_fills_and_equity(tmp_path: Path) -> None:
    journal = LivePaperJournal(tmp_path / "live.jsonl")
    first = _manager(journal)
    asyncio.run(first.start(_config()))
    _close_bar(first, T0, "3000")
    first._open_position_internal("LONG", Decimal("3000"))
    _close_bar(first, T0 + timedelta(hours=1), "3010")
    first.update_stops(Decimal("2950"), Decimal("3200"))
    # The process dies here: no stop(), no session_stop in the journal.

    second = _manager(LivePaperJournal(tmp_path / "live.jsonl"))
    outcome = asyncio.run(boot_live_paper(second, autostart=None))

    assert outcome == "resumed"
    assert second.is_active
    assert second.session_id == first.session_id
    assert second.config == first.config
    assert second.balance == first.balance
    assert second.fees_paid == first.fees_paid
    assert second.position is not None
    assert second.position.side == "LONG"
    assert second._pos_qty == first._pos_qty
    assert second._pos_sl == Decimal("2950")
    assert second._pos_tp == Decimal("3200")
    assert [f.id for f in second.fills] == [f.id for f in first.fills]
    assert len(second.equity_history) == 2
    assert second.to_state_dict()["resumed_at"] is not None


def test_stop_hit_while_offline_is_filled_at_its_level(tmp_path: Path) -> None:
    journal = LivePaperJournal(tmp_path / "live.jsonl")
    first = _manager(journal)
    asyncio.run(first.start(_config()))
    _close_bar(first, T0, "3000")
    first._open_position_internal("LONG", Decimal("3000"))
    stop = first._pos_sl
    assert stop is not None
    _close_bar(first, T0 + timedelta(hours=1), "3005")

    history = [
        _bar(T0 + timedelta(hours=1), high="3006", low="3004", close="3005"),  # already seen
        _bar(T0 + timedelta(hours=2), high="3010", low=str(stop - 5), close="2990"),  # gap
        _bar(T0 + timedelta(hours=3), high="2995", low="2980", close="2985"),
    ]

    async def loader(symbol: str, interval: str, count: int) -> list[OhlcvBar]:
        return history

    second = _manager(LivePaperJournal(tmp_path / "live.jsonl"), history_loader=loader)
    asyncio.run(boot_live_paper(second, autostart=None))
    asyncio.run(second._warm_up_from_history())

    assert second.position is None
    assert second.fills[-1].reason == "stop_loss"
    assert Decimal(second.fills[-1].price) == stop
    assert second.fills[-1].ts == "2026-09-24 12:00:00", "filled at the bar that hit it"
    # ...and that fill is in the journal, so a second restart does not reopen it.
    third = _manager(LivePaperJournal(tmp_path / "live.jsonl"))
    asyncio.run(boot_live_paper(third, autostart=None))
    assert third.position is None
    assert third.balance == second.balance


def test_torn_last_line_is_skipped_not_fatal(tmp_path: Path) -> None:
    path = tmp_path / "live.jsonl"
    journal = LivePaperJournal(path)
    manager = _manager(journal)
    asyncio.run(manager.start(_config()))
    _close_bar(manager, T0, "3000")
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type": "snapshot", "session_id": "')  # died mid-write
    session = journal.load_resumable()
    assert session is not None
    assert session.session_id == manager.session_id


def test_boot_prefers_resume_over_autostart_and_autostarts_otherwise(tmp_path: Path) -> None:
    fresh = _manager(LivePaperJournal(tmp_path / "empty.jsonl"))
    assert asyncio.run(boot_live_paper(fresh, autostart=_config())) == "started"
    assert fresh.is_active and fresh.session_id is not None

    again = _manager(LivePaperJournal(tmp_path / "empty.jsonl"))
    other = LivePaperConfig(symbol="BTCUSDT")
    assert asyncio.run(boot_live_paper(again, autostart=other)) == "resumed"
    assert again.config.symbol == "ETHUSDT", "the running ledger continues; no second one"

    idle = _manager(None)
    assert asyncio.run(boot_live_paper(idle, autostart=None)) == "idle"
    assert not idle.is_active


def test_unknown_robot_in_journal_fails_resume_without_crashing(tmp_path: Path) -> None:
    path = tmp_path / "live.jsonl"
    LivePaperJournal(path).append(
        "session_start", "abc", {"config": {"symbol": "ETHUSDT", "robot": "no_such_robot"}}
    )
    manager = _manager(LivePaperJournal(path))
    assert asyncio.run(boot_live_paper(manager, autostart=None)) == "resume_failed"
    assert not manager.is_active


def test_autostart_and_journal_come_from_settings(tmp_path: Path) -> None:
    off = Settings(_env_file=None)  # type: ignore[call-arg]
    assert autostart_config(off) is None
    assert journal_from_settings(off, root=tmp_path) is None

    on = Settings(
        _env_file=None,  # type: ignore[call-arg]
        live_paper_autostart=True,
        live_paper_symbol="btcusdt",
        live_paper_interval="4h",
        live_paper_robot="ema",
        live_paper_journal="data/paper/live_events.jsonl",
        risk_per_trade=Decimal("0.003"),
        taker_fee=Decimal("0.0007"),
    )
    config = autostart_config(on)
    assert config is not None
    assert (config.symbol, config.interval, config.robot) == ("BTCUSDT", "4h", "ema")
    assert config.risk_per_trade == Decimal("0.003"), "risk comes from the tested settings"
    assert config.taker_fee == Decimal("0.0007")
    journal = journal_from_settings(on, root=tmp_path)
    assert journal is not None
    assert journal.path == tmp_path / "data/paper/live_events.jsonl"


def test_in_memory_session_writes_nothing(tmp_path: Path) -> None:
    manager = _manager(None)
    asyncio.run(manager.start(_config()))
    _close_bar(manager, T0, "3000")
    assert manager.to_state_dict()["persisted"] is False
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("event_count", [1, 3])
def test_every_closed_bar_is_journalled(tmp_path: Path, event_count: int) -> None:
    path = tmp_path / "live.jsonl"
    manager = _manager(LivePaperJournal(path))
    asyncio.run(manager.start(_config()))
    for index in range(event_count):
        _close_bar(manager, T0 + timedelta(hours=index), "3000")
    kinds = [json.loads(line)["type"] for line in path.read_text().splitlines()]
    assert kinds[0] == "session_start"
    points = [
        json.loads(line)
        for line in path.read_text().splitlines()
        if json.loads(line).get("equity_point")
    ]
    assert len(points) == event_count
