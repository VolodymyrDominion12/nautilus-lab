"""The dashboard's trade list and trade page: one session, two endpoints, real log rows.

The trade view is the same screen for a paper session and for a research backtest, so the
tests drive both: a session registered like `SessionRegistry.create` registers it, and a
bare run id from `reports/history/*.json` (`single_backtest.session_id`) that has no live
session behind it at all.

What these tests refuse to let slip:

* a list row must say **how** its money number was computed (`pnl_source`) and whether the
  size behind it is real (`qty_known`), because a backtest log carries no fills;
* a truncated window must be reported as truncated — the reader stops at a record cap, and
  a short list is otherwise indistinguishable from a run with few trades;
* the per-trade page must resolve the *same* id the list served, and answer 404 with what
  it did scan instead of an empty trade.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from nautilus_lab.api.app import create_app
from nautilus_lab.api.paper_streamer import (
    LiveBar,
    LiveFill,
    LivePaperConfig,
    LivePaperSessionManager,
)
from nautilus_lab.domain.decision_log import DecisionRecord
from nautilus_lab.infrastructure.settings import Settings

SESSION_ID = "ema-eth-159a09"
RUN_ID = "0d83e156-f6fd-483d-b21a-fe26721e1f8c"


def _cfg(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "decision_log_enabled": True,
        "decision_log_dir": "data/paper/decisions",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def _register(app: Any, *, session_id: str = SESSION_ID) -> LivePaperSessionManager:
    registry = app.state.lab.sessions
    manager = LivePaperSessionManager(
        LivePaperConfig(robot="ema", symbol="ETHUSDT", name="ema-eth"),
        decision_log=registry.decision_log_writer,
    )
    manager.session_id = session_id
    registry.sessions[session_id] = manager
    return manager


def _record(
    *,
    session_id: str,
    when: datetime,
    close: str,
    outcome: str,
    signal: str | None = None,
    reason: str | None = None,
    indicators: dict[str, str] | None = None,
    states: dict[str, Any] | None = None,
) -> DecisionRecord:
    return DecisionRecord(
        bar_end_utc=when,
        robot="ema",
        instrument_id="ETHUSDT",
        close_price=Decimal(close),
        regime="UP",
        signal=signal,
        signal_reason=reason,
        indicators=indicators or {},
        states=states or {},
        session_id=session_id,
        outcome=outcome,
    )


def _write_round_trip(writer: Any, session_id: str) -> None:
    writer.log(
        _record(
            session_id=session_id,
            when=datetime(2026, 9, 25, 14, 0, tzinfo=UTC),
            close="2650.0",
            outcome="ENTRY_OPENED",
            signal="BUY",
            reason="golden cross",
            indicators={"er": "0.7", "stop_loss": "2600.0", "take_profit": "2750.0"},
            states={"stop_loss": "2600.0", "take_profit": "2750.0"},
        )
    )
    writer.log(
        _record(
            session_id=session_id,
            when=datetime(2026, 9, 25, 15, 0, tzinfo=UTC),
            close="2700.0",
            outcome="HOLD_NOOP",
            indicators={"er": "0.75"},
        )
    )
    writer.log(
        _record(
            session_id=session_id,
            when=datetime(2026, 9, 25, 16, 0, tzinfo=UTC),
            close="2700.0",
            outcome="TAKE_PROFIT",
            signal="FLAT",
            reason="take profit hit",
            indicators={"er": "0.8"},
        )
    )


def test_trades_list_reconstructs_a_round_trip(tmp_path: Path) -> None:
    app = create_app(_cfg(), root=tmp_path)
    _register(app)
    _write_round_trip(app.state.lab.sessions.decision_log_writer, SESSION_ID)

    client = TestClient(app)
    body = client.get(f"/api/paper/sessions/{SESSION_ID}/trades").json()

    assert body["status"] == "ok"
    assert body["truncated"] is False
    assert body["records"] == 3
    assert len(body["trades"]) == 1
    trade = body["trades"][0]
    assert trade["id"] == f"{SESSION_ID}-trade-1"
    assert trade["side"] == "LONG"
    assert trade["status"] == "CLOSED"
    assert trade["entry_price"] == 2650.0
    assert trade["exit_price"] == 2700.0
    assert trade["exit_outcome"] == "TAKE_PROFIT"
    assert trade["stop_loss"] == 2600.0
    assert trade["take_profit"] == 2750.0
    assert trade["realized_pnl"] == 50.0
    assert trade["r_multiple"] == round(50.0 / 50.0, 2)
    assert trade["duration_bars"] == 3
    assert trade["decision_count"] == 3


def test_trades_list_admits_a_price_only_pnl(tmp_path: Path) -> None:
    """A backtest log has no fills: the number is price arithmetic on an assumed size.

    `realized_pnl` used to be presented alone, which reads as account PnL. The list now
    carries the basis, and the size behind it is explicitly unknown.
    """
    app = create_app(_cfg(), root=tmp_path)
    _register(app)
    _write_round_trip(app.state.lab.sessions.decision_log_writer, SESSION_ID)

    client = TestClient(app)
    trade = client.get(f"/api/paper/sessions/{SESSION_ID}/trades").json()["trades"][0]

    assert trade["pnl_source"] == "price_delta"
    assert trade["qty"] == 1.0
    assert trade["qty_known"] is False
    # Not 0.0: a fee nobody recorded is not a fee of zero.
    assert trade["fee"] is None
    assert trade["fee_known"] is False


def test_trades_list_reports_a_truncated_window(tmp_path: Path) -> None:
    app = create_app(_cfg(), root=tmp_path)
    _register(app)
    _write_round_trip(app.state.lab.sessions.decision_log_writer, SESSION_ID)

    client = TestClient(app)
    body = client.get(f"/api/paper/sessions/{SESSION_ID}/trades?limit=2").json()

    assert body["limit"] == 2
    assert body["records"] == 2
    assert body["truncated"] is True


def test_trade_page_returns_the_full_trade_with_indicators_on_both_ends(tmp_path: Path) -> None:
    app = create_app(_cfg(), root=tmp_path)
    _register(app)
    _write_round_trip(app.state.lab.sessions.decision_log_writer, SESSION_ID)
    client = TestClient(app)

    listed = client.get(f"/api/paper/sessions/{SESSION_ID}/trades").json()["trades"][0]
    body = client.get(f"/api/paper/sessions/{SESSION_ID}/trades/{listed['id']}").json()

    assert body["status"] == "ok"
    trade = body["trade"]
    assert trade["id"] == listed["id"]
    assert trade["indicators_at_entry"] == {
        "er": "0.7",
        "stop_loss": "2600.0",
        "take_profit": "2750.0",
    }
    assert trade["indicators_at_exit"] == {"er": "0.8"}
    assert trade["entry_reason"] == "golden cross"
    assert trade["exit_reason"] == "TAKE_PROFIT: take profit hit"
    # Every bar the trade lived through, so the page can draw its own timeline.
    assert [row["ts"] for row in trade["decisions"]] == [
        "2026-09-25T14:00:00+00:00",
        "2026-09-25T15:00:00+00:00",
        "2026-09-25T16:00:00+00:00",
    ]
    assert trade["excursion_basis"] == "decision closes"
    assert trade["mfe_close"] == 50.0


def test_trade_page_reports_an_unknown_id_with_what_it_scanned(tmp_path: Path) -> None:
    app = create_app(_cfg(), root=tmp_path)
    _register(app)
    _write_round_trip(app.state.lab.sessions.decision_log_writer, SESSION_ID)

    client = TestClient(app)
    res = client.get(f"/api/paper/sessions/{SESSION_ID}/trades/{SESSION_ID}-trade-99")

    assert res.status_code == 404
    detail = res.json()["detail"]
    assert f"{SESSION_ID}-trade-99" in detail
    assert "1 trades reconstructed" in detail


def test_trades_work_for_a_backtest_run_with_no_live_session(tmp_path: Path) -> None:
    """Backtest Details reads `single_backtest.session_id`: a log key, not a session."""
    app = create_app(_cfg(), root=tmp_path)
    _write_round_trip(app.state.lab.sessions.decision_log_writer, RUN_ID)
    client = TestClient(app)

    body = client.get(f"/api/paper/sessions/{RUN_ID}/trades").json()

    assert body["status"] == "ok"
    assert body["session_id"] == RUN_ID
    assert len(body["trades"]) == 1
    assert body["trades"][0]["id"] == f"{RUN_ID}-trade-1"


def test_trades_list_is_empty_for_a_key_nobody_logged(tmp_path: Path) -> None:
    app = create_app(_cfg(), root=tmp_path)
    client = TestClient(app)

    body = client.get("/api/paper/sessions/never-ran-000000/trades").json()

    assert body["status"] == "ok"
    assert body["trades"] == []
    assert body["truncated"] is False


def test_a_live_session_reports_pnl_and_fees_from_its_own_fills(tmp_path: Path) -> None:
    """The venue ledger outranks price arithmetic: it knows the size and both fees."""
    app = create_app(_cfg(), root=tmp_path)
    manager = _register(app)
    _write_round_trip(app.state.lab.sessions.decision_log_writer, SESSION_ID)
    manager.fills.extend(
        [
            LiveFill(
                id="fill-1",
                ts="2026-09-25 14:00:01",
                symbol="ETHUSDT",
                side="BUY",
                qty="0.5",
                price="2650.0",
                fee="0.6625",
                realized_pnl="0.00",
                reason="Open LONG (sl=2600.0 tp=2750.0)",
            ),
            LiveFill(
                id="fill-2",
                ts="2026-09-25 16:00:01",
                symbol="ETHUSDT",
                side="SELL",
                qty="0.5",
                price="2700.0",
                fee="0.6750",
                realized_pnl="+24.66",
                reason="Take profit hit",
            ),
        ]
    )

    client = TestClient(app)
    trade = client.get(f"/api/paper/sessions/{SESSION_ID}/trades").json()["trades"][0]

    assert trade["pnl_source"] == "fills"
    assert trade["realized_pnl"] == 24.66
    assert trade["qty"] == 0.5
    assert trade["qty_known"] is True
    assert trade["fee"] == round(0.6625 + 0.6750, 8)
    assert trade["fee_known"] is True


def test_trade_page_draws_the_live_session_s_own_bars(tmp_path: Path) -> None:
    """A live paper session streams its bars: the page must not need a catalog for them.

    A paper session on the VPS runs on Binance live bars and has no ingested parquet
    series behind it, so a chart that only reads the catalog shows nothing exactly where
    the user is looking at a real trade.
    """
    app = create_app(_cfg(), root=tmp_path)
    manager = _register(app)
    _write_round_trip(app.state.lab.sessions.decision_log_writer, SESSION_ID)
    manager.recent_bars.extend(
        [
            LiveBar(
                time=int(datetime(2026, 9, 25, 13, 59, tzinfo=UTC).timestamp()),
                open=2640.0,
                high=2651.0,
                low=2638.0,
                close=2650.0,
                volume=3.0,
                is_closed=True,
            ),
            LiveBar(
                time=int(datetime(2026, 9, 25, 14, 0, tzinfo=UTC).timestamp()),
                open=2650.0,
                high=2660.0,
                low=2649.0,
                close=2658.0,
                volume=4.0,
                is_closed=True,
            ),
            LiveBar(
                time=int(datetime(2026, 9, 25, 15, 0, tzinfo=UTC).timestamp()),
                open=2658.0,
                high=2705.0,
                low=2655.0,
                close=2700.0,
                volume=5.0,
                is_closed=True,
            ),
        ]
    )
    client = TestClient(app)
    trade_id = f"{SESSION_ID}-trade-1"

    body = client.get(f"/api/paper/sessions/{SESSION_ID}/trades/{trade_id}").json()

    chart = body["chart"]
    assert chart["source"] == "session"
    assert chart["instrument_id"] == "ETHUSDT"
    assert chart["bar_interval"] == "1m"
    assert [bar["close"] for bar in chart["bars"]] == [2650.0, 2658.0, 2700.0]
    # The window is padded by the trade's own bar spacing, so the candle a decision belongs
    # to is on the chart. A decision is stamped with the bar's END and a candle with its
    # open, and the chart drops a marker that lands on no candle — the pad is what keeps
    # the entry arrow visible instead of silently missing.
    entry_at = int(datetime.fromisoformat(body["trade"]["decisions"][0]["ts"]).timestamp())
    assert chart["bars"][0]["time"] < entry_at


def test_trade_page_takes_the_instrument_from_the_trade_itself(tmp_path: Path) -> None:
    """A link with no context still names the instrument — the log recorded it.

    An archived history entry carries `bar_interval: null`, so a link built from it asks for
    a chart with no interval. Refusing outright left the page saying "there is nothing to
    draw" next to a trade whose instrument was in the log all along; the interval now falls
    back to the API's configured one and the series check refuses a wrong series by price.
    """
    app = create_app(_cfg(), root=tmp_path)
    _write_round_trip(app.state.lab.sessions.decision_log_writer, SESSION_ID)
    client = TestClient(app)

    body = client.get(f"/api/paper/sessions/{SESSION_ID}/trades/{SESSION_ID}-trade-1").json()

    chart = body["chart"]
    assert chart["source"] == "none"
    assert chart["bars"] == []
    assert chart["instrument_id"] == "ETHUSDT"
    assert "ETHUSDT" in chart["note"]


def test_trade_page_omits_bars_when_none_are_asked_for(tmp_path: Path) -> None:
    app = create_app(_cfg(), root=tmp_path)
    _write_round_trip(app.state.lab.sessions.decision_log_writer, SESSION_ID)
    client = TestClient(app)

    body = client.get(f"/api/paper/sessions/{SESSION_ID}/trades/{SESSION_ID}-trade-1?bars=0").json()

    assert body["chart"] == {
        "source": "none",
        "note": "Chart bars were not requested.",
        "bars": [],
    }


def test_trade_page_refuses_bars_from_a_series_the_trade_was_not_taken_on(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A wrong catalog draws a confident chart under a trade it has nothing to do with.

    Every catalog of `ETH/USDT.SIM` is named the same, so the instrument id cannot tell them
    apart — the prices can. Found by opening the page: the entry marker sat on bars 1500
    dollars away from the entry, because the caller passed the default catalog for a run
    that used another one.
    """
    app = create_app(_cfg(), root=tmp_path)
    _write_round_trip(app.state.lab.sessions.decision_log_writer, SESSION_ID)
    monkeypatch.setattr(
        "nautilus_lab.api.catalog_service.load_catalog_bars",
        lambda **_: {
            "instrument_id": "ETHUSDT",
            "bar_type": "ETHUSDT-1-MINUTE-LAST-EXTERNAL",
            "bar_interval": "1m",
            "catalog_path": "catalog",
            "count": 1,
            "first_date": "2026-09-25T14:00:00+00:00",
            "last_date": "2026-09-25T14:00:00+00:00",
            "bars": [
                {
                    "time": 1_790_000_000,
                    "open": 22.0,
                    "high": 23.0,
                    "low": 21.0,
                    "close": 22.5,
                    "volume": 1.0,
                },
            ],
        },
    )
    client = TestClient(app)

    body = client.get(
        f"/api/paper/sessions/{SESSION_ID}/trades/{SESSION_ID}-trade-1",
        params={"instrument_id": "ETHUSDT", "bar_interval": "1m", "catalog_path": "catalog"},
    ).json()

    assert body["chart"]["source"] == "none"
    assert body["chart"]["bars"] == []
    assert "not the series this trade was taken on" in body["chart"]["note"]
    assert "2650" in body["chart"]["note"]


def test_trade_page_accepts_bars_that_do_contain_the_trade(
    tmp_path: Path, monkeypatch: Any
) -> None:
    app = create_app(_cfg(), root=tmp_path)
    _write_round_trip(app.state.lab.sessions.decision_log_writer, SESSION_ID)
    monkeypatch.setattr(
        "nautilus_lab.api.catalog_service.load_catalog_bars",
        lambda **_: {
            "instrument_id": "ETHUSDT",
            "bar_type": "ETHUSDT-1-MINUTE-LAST-EXTERNAL",
            "bar_interval": "1m",
            "catalog_path": "catalog",
            "count": 1,
            "first_date": "2026-09-25T14:00:00+00:00",
            "last_date": "2026-09-25T14:00:00+00:00",
            "bars": [
                {
                    "time": 1_790_000_000,
                    "open": 2640.0,
                    "high": 2660.0,
                    "low": 2638.0,
                    "close": 2650.0,
                    "volume": 1.0,
                },
                {
                    "time": 1_790_003_600,
                    "open": 2650.0,
                    "high": 2710.0,
                    "low": 2649.0,
                    "close": 2700.0,
                    "volume": 1.0,
                },
            ],
        },
    )
    client = TestClient(app)

    body = client.get(
        f"/api/paper/sessions/{SESSION_ID}/trades/{SESSION_ID}-trade-1",
        params={"instrument_id": "ETHUSDT", "bar_interval": "1m", "catalog_path": "catalog"},
    ).json()

    assert body["chart"]["source"] == "catalog"
    assert len(body["chart"]["bars"]) == 2
