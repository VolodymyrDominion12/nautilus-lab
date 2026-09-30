"""Compact records (docs/30, stage 5) and the margin distribution (stage 6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from nautilus_lab.application.decision_digest import build_digest
from nautilus_lab.application.decision_margins import extra_passes, margin_distribution
from nautilus_lab.application.decision_trace_codec import (
    legacy_indicators,
    record_to_dict,
    upgrade_row,
)
from nautilus_lab.application.trade_history import reconstruct_trades_from_decisions
from nautilus_lab.domain.decision_log import DecisionRecord
from nautilus_lab.domain.decision_trace import RecordKind, Stage, Verdict, step

T0 = datetime(2026, 7, 1, tzinfo=UTC)


def _record(**extra: Any) -> DecisionRecord:
    base: dict[str, Any] = {
        "bar_end_utc": T0,
        "robot": "regime",
        "instrument_id": "ETH/USDT.SIM",
        "close_price": Decimal("100"),
        "regime": "uptrend",
        "signal": None,
        "signal_reason": None,
        "indicators": {"ema": "99"},
        "states": {},
        "session_id": "s",
        "steps": (
            step(Stage.STRATEGY, "UptrendBreakout", Verdict.INFO, values={"ema": Decimal("99")}),
        ),
        "outcome": "NO_SIGNAL",
        "config_hash": "abc",
    }
    base.update(extra)
    return DecisionRecord(**base)


def test_indicators_are_derived_on_read_not_written_twice() -> None:
    record = _record()
    row = record_to_dict(record)
    assert "indicators" not in row
    assert "params" not in row
    # The same strings the writer used to store: derived from the steps, as before.
    assert upgrade_row(row)["indicators"] == legacy_indicators(record.steps)


def test_a_record_without_steps_still_writes_its_indicators() -> None:
    row = record_to_dict(_record(steps=()))
    assert row["indicators"] == {"ema": "99"}


def _row(ts: datetime, outcome: str, **extra: Any) -> dict[str, Any]:
    return {
        "schema": "decision_trace/1",
        "kind": extra.pop("kind", "bar_decision"),
        "ts": ts.isoformat(),
        "session_id": "s",
        "close": 100.0,
        "outcome": outcome,
        "signal": extra.pop("signal", None),
        "steps": extra.pop("steps", []),
        **extra,
    }


def test_run_header_carries_params_and_is_not_a_decision() -> None:
    header = record_to_dict(
        _record(
            kind=RecordKind.RUN_HEADER,
            outcome="RUN_HEADER",
            steps=(),
            indicators={},
            params={"fast_period": "10"},
        )
    )
    assert header["kind"] == "run_header"
    assert header["params"] == {"fast_period": "10"}
    rows = [
        header,
        _row(T0 + timedelta(hours=1), "ENTRY_OPENED", signal="buy"),
        _row(T0 + timedelta(hours=2), "EXIT", signal="flat"),
    ]
    digest = build_digest(rows)
    assert digest.params == {"fast_period": "10"}
    assert "RUN_HEADER" not in digest.outcomes
    assert digest.bars == 2
    (trade,) = reconstruct_trades_from_decisions(rows)
    assert trade["duration_bars"] == 2


def test_margin_distribution_groups_by_component_and_counts_passes() -> None:
    rows = [
        _row(
            T0 + timedelta(hours=i),
            "NO_SIGNAL",
            steps=[
                {"stage": "filter", "component": "vpin", "values": {"margin_pct": m}},
                {
                    "stage": "regime",
                    "component": "RegimeClassifier",
                    "values": {"er_margin_pct": 5},
                },
                {"stage": "execution", "component": "x", "values": {"margin_pct": 1}},
            ],
        )
        for i, m in enumerate([-12.0, -4.0, -1.0, 2.0])
    ]
    rows.append(_row(T0, "STOP_LOSS", kind="intrabar", steps=[]))
    dist = margin_distribution(rows)
    assert set(dist) == {"vpin.margin_pct", "RegimeClassifier.er_margin_pct"}
    vpin = dist["vpin.margin_pct"]
    assert vpin["total"] == 4
    assert vpin["passed"] == 1
    assert extra_passes(vpin["values"], 5) == 2


def test_exit_on_a_refused_reentry_bar_closes_the_trade() -> None:
    """ema ETH 2026-09-29: exit executed, entry blocked by max_drawdown -> trade closed."""
    exit_step = {
        "stage": "execution",
        "component": "paper_broker",
        "verdict": "emit",
        "result": "exit",
        "values": {"side": "LONG", "qty": 1.0, "price": 101.0},
    }
    rows = [
        _row(T0, "ENTRY_OPENED", signal="buy"),
        _row(T0 + timedelta(hours=1), "HOLD_NOOP", signal="buy"),
        _row(
            T0 + timedelta(hours=2),
            "ENTRY_BLOCKED_RISK",
            signal="sell",
            blocked_by="risk.max_drawdown",
            steps=[exit_step],
        ),
        _row(T0 + timedelta(hours=3), "ENTRY_BLOCKED_RISK", signal="sell"),
        _row(T0 + timedelta(hours=9), "ENTRY_OPENED", signal="sell"),
    ]
    trades = reconstruct_trades_from_decisions(rows)
    assert len(trades) == 2
    first = trades[0]
    assert first["status"] == "CLOSED"
    assert first["exit_time"] == (T0 + timedelta(hours=2)).isoformat()
    assert "max_drawdown" in first["exit_reason"]
    assert first["duration_bars"] == 3
