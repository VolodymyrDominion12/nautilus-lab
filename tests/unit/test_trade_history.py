from __future__ import annotations

from typing import Any

from nautilus_lab.application.trade_history import reconstruct_trades_from_decisions


def test_reconstruct_trades_single_complete_trade() -> None:
    logs: list[dict[str, Any]] = [
        {
            "ts": "2026-09-21T00:59:59.999000+00:00",
            "session_id": "test-session-1",
            "instrument": "ETH/USDT.SIM",
            "close": "2689.19",
            "regime": "uptrend",
            "signal": "buy",
            "signal_reason": "donchian breakout long",
            "indicators": {"er": "0.62", "stop_loss": "2650.0", "take_profit": "2750.0"},
            "states": {"stop_loss": "2650.0", "take_profit": "2750.0"},
            "outcome": "ENTRY_OPENED",
            "steps": [{"stage": "strategy", "verdict": "pass"}],
        },
        {
            "ts": "2026-09-21T01:59:59.999000+00:00",
            "session_id": "test-session-1",
            "instrument": "ETH/USDT.SIM",
            "close": "2710.00",
            "regime": "uptrend",
            "signal": None,
            "outcome": "HOLD_NOOP",
            "indicators": {"er": "0.65"},
            "states": {},
        },
        {
            "ts": "2026-09-21T02:59:59.999000+00:00",
            "session_id": "test-session-1",
            "instrument": "ETH/USDT.SIM",
            "close": "2729.41",
            "regime": "range",
            "signal": "flat",
            "signal_reason": "regime change to range",
            "outcome": "EXIT",
            "indicators": {"er": "0.16"},
            "states": {},
        },
    ]

    trades = reconstruct_trades_from_decisions(logs)
    assert len(trades) == 1
    trade = trades[0]

    assert trade["id"] == "test-session-1-trade-1"
    assert trade["symbol"] == "ETH/USDT.SIM"
    assert trade["side"] == "LONG"
    assert trade["status"] == "CLOSED"
    assert trade["entry_price"] == 2689.19
    assert trade["exit_price"] == 2729.41
    assert trade["entry_time"] == "2026-09-21T00:59:59.999000+00:00"
    assert trade["exit_time"] == "2026-09-21T02:59:59.999000+00:00"
    assert trade["stop_loss"] == 2650.0
    assert trade["take_profit"] == 2750.0
    assert trade["realized_pnl"] == round(2729.41 - 2689.19, 4)
    assert trade["realized_pnl_pct"] == round(((2729.41 - 2689.19) / 2689.19) * 100, 2)
    assert trade["duration_bars"] == 3
    assert trade["duration_seconds"] == 7200
    assert len(trade["decisions"]) == 3
    assert trade["indicators_at_entry"]["er"] == "0.62"
    assert trade["indicators_at_exit"]["er"] == "0.16"
    assert trade["r_multiple"] == round((2729.41 - 2689.19) / (2689.19 - 2650.0), 2)


def test_reconstruct_trades_open_trade() -> None:
    logs: list[dict[str, Any]] = [
        {
            "ts": "2026-09-21T00:59:59.999000+00:00",
            "session_id": "test-session-2",
            "instrument": "BTCUSDT",
            "close": "65000.0",
            "regime": "uptrend",
            "signal": "buy",
            "signal_reason": "ema cross",
            "outcome": "ENTRY_OPENED",
        },
        {
            "ts": "2026-09-21T01:59:59.999000+00:00",
            "session_id": "test-session-2",
            "instrument": "BTCUSDT",
            "close": "65500.0",
            "outcome": "HOLD_NOOP",
        },
    ]

    active_pos = {
        "mark_price": "65500.0",
        "unrealized_pnl": "500.00",
        "unrealized_pnl_pct": "+0.77%",
        "stop_loss": "64000.0",
        "take_profit": "67000.0",
    }

    trades = reconstruct_trades_from_decisions(logs, active_position=active_pos)
    assert len(trades) == 1
    trade = trades[0]

    assert trade["status"] == "OPEN"
    assert trade["entry_price"] == 65000.0
    assert trade["mark_price"] == 65500.0
    assert trade["realized_pnl"] == 500.00
    assert trade["stop_loss"] == 64000.0
    assert trade["take_profit"] == 67000.0
    assert trade["duration_bars"] == 2


def test_reversal_does_not_inherit_the_previous_trade_s_closure() -> None:
    """A reversal writes one close and one open at the same instant.

    The old code zipped trades with closing fills by position, so the previous position's
    realised PnL landed on the trade that opened in its place.
    """
    logs: list[dict[str, Any]] = [
        {
            "ts": "2026-09-25T14:00:00+00:00",
            "session_id": "s-1",
            "instrument": "ETHUSDT",
            "close": "2650.0",
            "signal": "buy",
            "outcome": "ENTRY_OPENED",
            "indicators": {"stop_loss": "2600.0"},
        },
        {
            "ts": "2026-09-25T15:00:00+00:00",
            "session_id": "s-1",
            "instrument": "ETHUSDT",
            "close": "2655.0",
            "signal": "sell",
            "outcome": "REVERSE",
        },
        {
            "ts": "2026-09-25T16:00:00+00:00",
            "session_id": "s-1",
            "instrument": "ETHUSDT",
            "close": "2640.0",
            "signal": "flat",
            "outcome": "STOP_LOSS",
        },
    ]
    fills = [
        {
            "ts": "2026-09-25 14:00:00",
            "qty": "1",
            "fee": "1.0",
            "realized_pnl": "0.00",
            "reason": "Open LONG (sl=2600.0)",
        },
        {
            "ts": "2026-09-25 15:00:00",
            "qty": "1",
            "fee": "1.0",
            "realized_pnl": "+5.00",
            "reason": "Reversed to SHORT",
        },
        {
            "ts": "2026-09-25 15:00:00",
            "qty": "1",
            "fee": "1.0",
            "realized_pnl": "0.00",
            "reason": "Open SHORT (sl=2700.0)",
        },
        {
            "ts": "2026-09-25 16:00:00",
            "qty": "1",
            "fee": "1.0",
            "realized_pnl": "+15.00",
            "reason": "Stop loss hit",
        },
    ]

    trades = reconstruct_trades_from_decisions(logs, fills=fills)

    assert [trade["side"] for trade in trades] == ["LONG", "SHORT"]
    assert trades[0]["realized_pnl"] == 5.0
    assert trades[0]["pnl_source"] == "fills"
    assert trades[1]["realized_pnl"] == 15.0
    assert trades[1]["pnl_source"] == "fills"
    assert trades[1]["fee"] == 2.0


def test_excursions_are_measured_on_closes_and_labelled_as_such() -> None:
    logs: list[dict[str, Any]] = [
        {
            "ts": "2026-09-25T14:00:00+00:00",
            "close": "100.0",
            "signal": "buy",
            "outcome": "ENTRY_OPENED",
        },
        {"ts": "2026-09-25T15:00:00+00:00", "close": "110.0", "outcome": "HOLD_NOOP"},
        {"ts": "2026-09-25T16:00:00+00:00", "close": "95.0", "outcome": "HOLD_NOOP"},
        {"ts": "2026-09-25T17:00:00+00:00", "close": "104.0", "signal": "flat", "outcome": "EXIT"},
    ]

    trade = reconstruct_trades_from_decisions(logs)[0]

    assert trade["excursion_basis"] == "decision closes"
    assert trade["mfe_close"] == 10.0
    assert trade["mae_close"] == -5.0
    assert trade["mfe_close_pct"] == 10.0
    assert trade["mae_close_pct"] == -5.0


def test_a_short_trade_flips_the_sign_of_its_excursions() -> None:
    logs: list[dict[str, Any]] = [
        {
            "ts": "2026-09-25T14:00:00+00:00",
            "close": "100.0",
            "signal": "sell",
            "outcome": "ENTRY_OPENED",
        },
        {"ts": "2026-09-25T15:00:00+00:00", "close": "108.0", "outcome": "HOLD_NOOP"},
        {"ts": "2026-09-25T16:00:00+00:00", "close": "92.0", "outcome": "HOLD_NOOP"},
        {"ts": "2026-09-25T17:00:00+00:00", "close": "96.0", "signal": "flat", "outcome": "EXIT"},
    ]

    trade = reconstruct_trades_from_decisions(logs)[0]

    assert trade["side"] == "SHORT"
    assert trade["mfe_close"] == 8.0
    assert trade["mae_close"] == -8.0
    assert trade["realized_pnl"] == 4.0


def test_a_trade_without_a_size_says_so_instead_of_reporting_zero_fees() -> None:
    logs: list[dict[str, Any]] = [
        {
            "ts": "2026-09-25T14:00:00+00:00",
            "close": "100.0",
            "signal": "buy",
            "outcome": "ENTRY_OPENED",
        },
        {"ts": "2026-09-25T15:00:00+00:00", "close": "101.0", "outcome": "EXIT"},
    ]

    trade = reconstruct_trades_from_decisions(logs)[0]

    assert trade["fee"] is None
    assert trade["fee_known"] is False
    assert trade["qty_known"] is False
    assert trade["qty"] == 1.0


def test_a_log_holding_several_passes_is_not_read_as_one_timeline() -> None:
    """A walk-forward writes every fold under one session id, so the clock restarts mid-file.

    A real log in this repository holds six replays of the same seven hours. Sorting that
    flat paired the entry of one pass with the entry of the next and produced one-bar
    "trades" whose entry price equalled their exit price — trades nobody made.
    """
    one_pass = [
        {
            "ts": "2024-01-01T00:49:00+00:00",
            "session_id": "run-1",
            "instrument": "ETHUSDT",
            "close": "100.0",
            "signal": "buy",
            "outcome": "ENTRY_OPENED",
        },
        {
            "ts": "2024-01-01T03:38:00+00:00",
            "session_id": "run-1",
            "instrument": "ETHUSDT",
            "close": "150.0",
            "signal": "flat",
            "outcome": "EXIT",
        },
    ]
    logs = one_pass + one_pass

    trades = reconstruct_trades_from_decisions(logs)

    assert len(trades) == 2
    assert [trade["window_index"] for trade in trades] == [1, 2]
    assert [trade["realized_pnl"] for trade in trades] == [50.0, 50.0]
    # Ids stay unique across passes: the list is what the trade page is addressed by.
    assert len({trade["id"] for trade in trades}) == 2


def test_a_single_pass_is_still_one_window() -> None:
    logs = [
        {
            "ts": "2024-01-01T00:49:00+00:00",
            "close": "100.0",
            "signal": "buy",
            "outcome": "ENTRY_OPENED",
        },
        {"ts": "2024-01-01T03:38:00+00:00", "close": "150.0", "signal": "flat", "outcome": "EXIT"},
    ]

    trades = reconstruct_trades_from_decisions(logs)

    assert {trade["window_index"] for trade in trades} == {1}


def test_reverse_ordered_input_is_sorted_rather_than_shredded_per_row() -> None:
    """A caller that read newest-first must not get one window per record."""
    logs = [
        {"ts": f"2024-01-01T0{hour}:00:00+00:00", "close": str(100 + hour), "outcome": "HOLD_NOOP"}
        for hour in range(9, 0, -1)
    ]
    logs.insert(0, {"ts": "2024-01-01T09:30:00+00:00", "close": "150.0", "outcome": "EXIT"})
    logs.append(
        {
            "ts": "2024-01-01T00:30:00+00:00",
            "close": "100.0",
            "signal": "buy",
            "outcome": "ENTRY_OPENED",
        }
    )

    trades = reconstruct_trades_from_decisions(logs)

    assert len(trades) == 1
    assert trades[0]["window_index"] == 1
