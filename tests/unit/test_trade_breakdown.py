import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from nautilus_lab.application.trade_breakdown import (
    Trade,
    bars_from_records,
    fold_of,
    gate_features,
    profit_factor,
    reconstruct_trades,
    render_cell_markdown,
    summarize,
    tag_trades,
)
from nautilus_lab.domain.entry_filters import EntryFilterParams

T0 = datetime(2026, 1, 1, tzinfo=UTC)
FEE = 0.00075


def _ts(hours: int) -> str:
    return (T0 + timedelta(hours=hours)).isoformat()


def _bar(hours: int, close: float, outcome: str = "NO_SIGNAL", **extra: object) -> dict[str, Any]:
    record: dict[str, Any] = {
        "kind": "bar_decision",
        "ts": _ts(hours),
        "close": str(close),
        "outcome": outcome,
        "bar": {"o": close, "h": close + 1, "l": close - 1, "c": close, "v": 1},
        "steps": [],
    }
    record.update(extra)
    return record


def _entry(hours: int, close: float, side: str, leg: str) -> dict[str, Any]:
    return _bar(
        hours,
        close,
        "ENTRY_OPENED",
        regime="uptrend" if side == "buy" else "downtrend",
        signal_reason=f"{leg} signal",
        steps=[{"stage": "strategy", "component": leg, "verdict": "emit", "result": side}],
    )


def _fill(hours: int, price: float, side: str, qty: float, stop: float) -> dict[str, Any]:
    return {
        "kind": "intrabar",
        "ts": _ts(hours),
        "outcome": "ENTRY_FILLED",
        "steps": [
            {
                "component": "fill",
                "values": {"side": side, "qty": qty, "fill_price": price, "fee": 1.5},
            },
            {"component": "protective_stop", "values": {"stop_loss": stop}},
        ],
    }


def _stop(hours: int, level: float) -> dict[str, Any]:
    return {
        "kind": "intrabar",
        "ts": _ts(hours),
        "outcome": "STOP_LOSS",
        "steps": [{"component": "stop_loss", "values": {"level": level}}],
    }


def test_fold_of_parses_session_file_names() -> None:
    assert fold_of("feb38c35-9f5a-4c71-ba8f-1dcf94088087-f3_2026-05-06.jsonl") == 3
    assert fold_of("summary.json") is None


def test_long_closed_by_bar_exit_and_short_by_stop() -> None:
    records = [
        (0, _entry(1, 100.0, "buy", "UptrendBreakout")),
        (0, _fill(1, 100.0, "LONG", 2.0, 98.0)),
        (0, _bar(5, 104.0, "EXIT", signal_reason="uptrend EMA exit")),
        (0, _entry(6, 104.0, "sell", "DowntrendBreakout")),
        (0, _fill(6, 104.0, "SHORT", 1.0, 106.0)),
        (0, _stop(7, 106.0)),
    ]
    rec = reconstruct_trades(records, taker_fee=FEE)
    long_trade, short_trade = rec.trades
    assert rec.open_at_end == 0
    assert long_trade.leg == "UptrendBreakout"
    assert long_trade.exit_reason == "uptrend EMA exit"
    assert long_trade.gross == pytest.approx(8.0)
    assert long_trade.r_multiple == pytest.approx(2.0)
    assert long_trade.exit_fee == pytest.approx(104.0 * 2.0 * FEE)
    assert long_trade.net == pytest.approx(8.0 - 1.5 - 104.0 * 2.0 * FEE)
    assert long_trade.hold_hours == pytest.approx(4.0)
    assert long_trade.hold_bucket == "2-6h"
    assert short_trade.side == "SHORT"
    assert short_trade.exit_reason == "STOP_LOSS"
    assert short_trade.r_multiple == pytest.approx(-1.0)


def test_reverse_closes_then_opens_and_open_positions_are_counted_per_fold() -> None:
    records = [
        (0, _entry(1, 100.0, "buy", "UptrendBreakout")),
        (0, _fill(1, 100.0, "LONG", 1.0, 99.0)),
        (0, _bar(3, 97.0, "REVERSE", signal_reason="flip")),
        (0, _fill(3, 97.0, "SHORT", 1.0, 98.0)),
        # fold 0 ends with the short still open; fold 1 starts flat
        (1, _entry(10, 90.0, "buy", "UptrendBreakout")),
        (1, _fill(10, 90.0, "LONG", 1.0, 89.0)),
    ]
    rec = reconstruct_trades(records, taker_fee=FEE)
    assert [t.exit_reason for t in rec.trades] == ["flip"]
    assert rec.trades[0].gross == pytest.approx(-3.0)
    assert rec.open_at_end == 2
    assert rec.outcomes["intrabar:ENTRY_FILLED"] == 3


def test_fill_without_price_is_ignored() -> None:
    bad = _fill(1, 0.0, "LONG", 1.0, 99.0)
    rec = reconstruct_trades([(0, bad)], taker_fee=FEE)
    assert rec.trades == ()
    assert rec.open_at_end == 0


def test_gate_features_match_the_entry_filter_and_tag_alignment() -> None:
    rising = [_bar(h, 100.0 + h) for h in range(12)]
    bars = bars_from_records(rising + rising[:3], instrument_id="X")  # duplicates collapse
    assert len(bars) == 12
    params = EntryFilterParams(
        htf_trend=True,
        htf_ema_period=3,
        htf_slope_lookback=2,
        vol_expansion=True,
        vol_fast_period=2,
        vol_slow_period=4,
        min_vol_ratio=Decimal("1"),
    )
    features = gate_features(bars, params)
    assert features[T0][0] is None  # warming up
    slope, ratio = features[T0 + timedelta(hours=11)]
    assert slope is not None
    assert slope > 0
    assert ratio is not None
    trades = [
        Trade(
            fold=0,
            side=side,
            leg=None,
            regime=None,
            entry_reason=None,
            ts_in=T0 + timedelta(hours=11),
            px_in=111.0,
            qty=1.0,
            fee_in=0.0,
            stop=110.0,
            ts_out=T0 + timedelta(hours=12),
            px_out=112.0,
            exit_reason="x",
            exit_fee=0.0,
        )
        for side in ("LONG", "SHORT")
    ]
    long_tagged, short_tagged = tag_trades(trades, features)
    assert long_tagged.slope_aligned is True
    assert short_tagged.slope_aligned is False
    assert long_tagged.vol_ratio == pytest.approx(ratio)


def test_summarize_orders_groups_and_report_renders() -> None:
    records = [
        (0, _entry(1, 100.0, "buy", "UptrendBreakout")),
        (0, _fill(1, 100.0, "LONG", 1.0, 99.0)),
        (0, _bar(100, 110.0, "EXIT", signal_reason="uptrend EMA exit")),
        (0, _entry(101, 110.0, "buy", "UptrendBreakout")),
        (0, _fill(101, 110.0, "LONG", 1.0, 109.0)),
        (0, _stop(102, 109.0)),
    ]
    rec = reconstruct_trades(records, taker_fee=FEE)
    rows = summarize(rec.trades, lambda t: t.hold_bucket, order=(">3d", "<=2h"))
    assert [row.key for row in rows] == [">3d", "<=2h"]
    assert rows[0].win_rate == 1.0
    pf = profit_factor(rec.trades)
    assert pf is not None
    assert pf > 1
    text = render_cell_markdown("regime_BTC", rec, list(rec.trades))
    assert "## regime_BTC" in text
    assert "### by holding" in text
    assert render_cell_markdown("empty", rec, []).endswith(
        "No completed trades in the decision trace.\n"
    )


def _load_script() -> ModuleType:
    """scripts/ is not a package; load it the way `uv run python scripts/...` does."""
    path = Path(__file__).resolve().parents[2] / "scripts" / "batch_trade_breakdown.py"
    spec = importlib.util.spec_from_file_location("batch_trade_breakdown", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_script_writes_report_and_trades_csv(tmp_path: Path) -> None:
    decisions = tmp_path / "cells" / "regime_BTC" / "decisions"
    decisions.mkdir(parents=True)
    rows = [
        _entry(1, 100.0, "buy", "UptrendBreakout"),
        _fill(1, 100.0, "LONG", 1.0, 99.0),
        _bar(5, 103.0, "EXIT", signal_reason="uptrend EMA exit"),
    ]
    (decisions / "abc-f0_2026-01-01.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8"
    )
    (tmp_path / "cells" / "empty_ETH").mkdir()
    script = _load_script()
    assert script.main([str(tmp_path)]) == 0
    report = (tmp_path / "trade_breakdown.md").read_text(encoding="utf-8")
    assert "## regime_BTC" in report
    assert "empty_ETH" not in report
    lines = (tmp_path / "cells" / "regime_BTC" / "trades.csv").read_text().splitlines()
    assert len(lines) == 2
    assert lines[1].startswith("0,LONG,UptrendBreakout")
    assert script.main([str(tmp_path / "missing")]) == 1
