"""Decision-log gaps found in the 2026-09-29 sweep (docs/30), one test per gap.

* meta_label wrote records with no steps: a rejected entry looked like "no signal";
* vpin_momentum never said which threshold VPIN had to reach (0.62 max vs 0.70);
* a backtest trade had no stop level, no size and no entry fill, so the trade page drew
  no SL line and reported no R;
* a ratchet exit was logged as a bare EXIT;
* the bar after every entry was counted as ENTRY_BLOCKED_RISK ("order already working").
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from nautilus_lab.application.decision_digest import build_digest
from nautilus_lab.application.decision_narrative import render_narrative
from nautilus_lab.application.trade_history import reconstruct_trades_from_decisions
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.decision_trace import Stage, Verdict, margin_pct
from nautilus_lab.domain.meta_label_strategy import MetaLabelStrategy
from nautilus_lab.domain.signals import Signal, SignalSide
from nautilus_lab.domain.vpin import BarVpin, vpin_threshold
from nautilus_lab.domain.vpin_momentum import VpinMomentum

ORIGIN = datetime(2026, 7, 15, tzinfo=UTC)


def _bars(count: int) -> list[OhlcvBar]:
    bars: list[OhlcvBar] = []
    price = Decimal("100")
    for index in range(count):
        price += Decimal("1")
        bars.append(
            OhlcvBar(
                instrument_id="ETH/USDT.SIM",
                ts_utc=ORIGIN + timedelta(hours=index),
                open=price,
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price,
                volume=Decimal("10"),
            )
        )
    return bars


class _BuyAt:
    """A primary robot that fires one BUY on bar `at` and explains every bar."""

    def __init__(self, at: int) -> None:
        self._at = at
        self._seen = 0
        self.last_trace: tuple[Any, ...] = ()

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        from nautilus_lab.domain.decision_trace import step

        self._seen += 1
        fired = self._seen == self._at
        self.last_trace = (
            step(Stage.STRATEGY, "Primary", Verdict.EMIT if fired else Verdict.INFO),
        )
        if not fired:
            return None
        return Signal(
            instrument_id=bar.instrument_id,
            side=SignalSide.BUY,
            bar_ts_utc=bar.ts_utc,
            reason="primary buy",
        )


class _Fixed:
    def __init__(self, probability: Decimal) -> None:
        self._p = probability

    def predict_success(self, features: tuple[Decimal, ...]) -> Decimal:
        return self._p


def _run_meta(probability: Decimal, *, at: int = 60) -> list[tuple[Signal | None, tuple[Any, ...]]]:
    strategy = MetaLabelStrategy(
        instrument_id="ETH/USDT.SIM",
        primary=_BuyAt(at),
        classifier=_Fixed(probability),
        threshold=Decimal("0.55"),
    )
    out = []
    for bar in _bars(at + 2):
        signal = strategy.on_bar(bar)
        out.append((signal, strategy.last_trace))
    return out


def test_margin_pct_is_signed_share_of_the_threshold() -> None:
    assert margin_pct(Decimal("0.62"), Decimal("0.70")) == (
        (Decimal("0.62") - Decimal("0.70")) / Decimal("0.70") * 100
    )
    assert margin_pct(Decimal("1"), Decimal("0")) is None
    assert margin_pct(None, Decimal("1")) is None


def test_a_zero_threshold_has_no_margin_but_keeps_its_numbers() -> None:
    """A missing `*_margin_pct` must trace back to a zero threshold, not to lost data.

    Every funding record in the 2026-10 corpus with the default `min_net_apy=0` has no
    `apy_margin_pct` (11 223 of 11 223), which looks like a logging hole until you read the
    step: the raw `net_apy` and the `min_net_apy` it was compared against are both there,
    so the *measure* is undefined while the evidence is intact (docs/35 §7, L-11).
    """
    from nautilus_lab.domain.funding import FundingCashAndCarry, FundingParams, FundingSnapshot

    robot = FundingCashAndCarry(
        spot_id="ETH/USDT.SIM",
        perp_id="ETHUSDT-PERP.SIM",
        params=FundingParams(min_net_apy=Decimal("0")),
    )
    robot.on_funding(
        FundingSnapshot(
            instrument="ETHUSDT-PERP.SIM",
            funding_rate=Decimal("0.0004"),
            mark_price=Decimal("2600"),
            index_price=Decimal("2599"),
            ts_utc=ORIGIN,
        ),
        is_open=False,
    )
    values = dict(robot.last_trace[-1].values)
    thresholds = dict(robot.last_trace[-1].thresholds or {})
    assert values.get("apy_margin_pct") is None, "a zero threshold has no percentage scale"
    assert values.get("net_apy") is not None, "the measured value must stay in the step"
    assert thresholds.get("min_net_apy") == Decimal("0"), "the threshold must stay too"


def test_meta_label_logs_a_rejected_primary_signal_as_a_block() -> None:
    signal, trace = _run_meta(Decimal("0.40"))[59]
    assert signal is None
    assert [s.component for s in trace] == ["Primary", "meta_label"]
    meta = trace[-1]
    assert meta.stage is Stage.FILTER
    assert meta.verdict is Verdict.BLOCK
    assert meta.values["primary_side"] == "buy"
    assert meta.values["p_success"] == Decimal("0.40")
    assert meta.values["margin_pct"] < 0
    assert meta.thresholds["threshold"] == Decimal("0.55")


def test_meta_label_logs_an_accepted_signal_as_a_pass() -> None:
    signal, trace = _run_meta(Decimal("0.70"))[59]
    assert signal is not None
    assert signal.side is SignalSide.BUY
    assert trace[-1].verdict is Verdict.PASS
    assert trace[-1].result == "accept"


def test_meta_label_quiet_bars_carry_the_primary_trace_only() -> None:
    _signal, trace = _run_meta(Decimal("0.70"))[10]
    assert [s.component for s in trace] == ["Primary"]


def test_vpin_step_names_its_threshold_and_margin() -> None:
    vpin = BarVpin(bucket_volume=Decimal("5"), toxic_threshold=Decimal("0.7"))
    assert vpin_threshold(vpin) == Decimal("0.7")
    robot = VpinMomentum(instrument_id="ETH/USDT.SIM", vpin=vpin)
    for bar in _bars(200):
        robot.on_bar(bar)
    step_ = next(s for s in robot.last_trace if s.component == "vpin")
    assert step_.thresholds["toxic_threshold"] == Decimal("0.7")
    if "vpin" in step_.values:
        assert "margin_pct" in step_.values


def test_vpin_threshold_is_none_for_a_test_double() -> None:
    assert vpin_threshold(object()) is None


# --- records as the backtest now writes them (JSON rows) --------------------------------


def _row(ts: datetime, outcome: str, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema": "decision_trace/1",
        "kind": extra.pop("kind", "bar_decision"),
        "ts": ts.isoformat(),
        "session_id": "s1",
        "robot": "regime",
        "instrument": "ETH/USDT.SIM",
        "close": extra.pop("close", 100.0),
        "regime": extra.pop("regime", "uptrend"),
        "signal": extra.pop("signal", None),
        "signal_reason": None,
        "indicators": {},
        "states": extra.pop("states", {}),
        "outcome": outcome,
        "blocked_by": None,
        "steps": extra.pop("steps", []),
    }
    row.update(extra)
    return row


def _entry_bar(ts: datetime) -> dict[str, Any]:
    return _row(
        ts,
        "ENTRY_OPENED",
        signal="buy",
        close=100.0,
        steps=[
            {
                "stage": "execution",
                "component": "paper_broker",
                "verdict": "emit",
                "result": "entry",
                "values": {"side": "LONG", "qty": 2.0, "price": 100.0, "stop_distance": 5.0},
            }
        ],
    )


def _fill(ts: datetime) -> dict[str, Any]:
    return _row(
        ts,
        "ENTRY_FILLED",
        kind="intrabar",
        close=101.0,
        states={"stop_loss": "96.0"},
        steps=[
            {
                "stage": "execution",
                "component": "fill",
                "verdict": "emit",
                "result": "entry_filled",
                "values": {
                    "side": "LONG",
                    "qty": 2.0,
                    "fill_price": 101.0,
                    "decision_price": 100.0,
                    "slippage_bps": 100.0,
                    "fee": 0.15,
                    "fill_delay_s": 3600,
                },
            },
            {
                "stage": "execution",
                "component": "protective_stop",
                "verdict": "emit",
                "result": "stop_placed",
                "values": {"stop_loss": 96.0, "risk_per_unit": 5.0, "risk_pct": -4.95},
            },
        ],
    )


def test_trade_takes_size_fill_and_initial_stop_from_the_lifecycle_records() -> None:
    t0 = ORIGIN
    rows = [
        _entry_bar(t0),
        _row(t0 + timedelta(hours=1), "PENDING_FILL", close=101.0),
        _fill(t0 + timedelta(hours=1)),
        _row(t0 + timedelta(hours=2), "HOLD_NOOP", close=104.0, states={"stop_loss": "99.0"}),
        _row(t0 + timedelta(hours=3), "RATCHET_EXIT", close=110.0),
    ]
    (trade,) = reconstruct_trades_from_decisions(rows)
    assert trade["status"] == "CLOSED"
    assert trade["exit_outcome"] == "RATCHET_EXIT"
    assert trade["qty"] == 2.0
    assert trade["qty_known"] is True
    assert trade["entry_fill_price"] == 101.0
    assert trade["entry_slippage_bps"] == 100.0
    assert trade["fee"] == 0.15
    assert trade["fee_known"] is True
    assert trade["initial_stop_loss"] == 96.0
    assert trade["stop_loss"] == 99.0  # the ratchet moved it
    # R against the stop the trade opened with: (110 - 100) / (100 - 96)
    assert trade["r_multiple"] == 2.5
    # The fill row is in the timeline but is not a bar held.
    assert trade["duration_bars"] == 4
    assert trade["realized_pnl"] == 20.0


def test_digest_counts_vetoed_signals_with_forward_returns() -> None:
    rows = []
    for index in range(30):
        ts = ORIGIN + timedelta(hours=index)
        if index == 2:
            rows.append(
                _row(
                    ts,
                    "SIGNAL_VETOED",
                    close=100.0,
                    steps=[
                        {
                            "stage": "filter",
                            "component": "meta_label",
                            "verdict": "block",
                            "result": "reject",
                            "values": {"p_success": 0.4, "primary_side": "buy"},
                            "thresholds": {"threshold": 0.55},
                        }
                    ],
                )
            )
        else:
            rows.append(_row(ts, "NO_SIGNAL", close=100.0 + index))
    digest = build_digest(rows, horizons=(1, 4))
    assert digest.outcomes["SIGNAL_VETOED"] == 1
    assert digest.forward["vetoed"]["+1"].n == 1
    assert digest.forward["vetoed"]["+1"].mean_pct is not None
    assert digest.forward["vetoed"]["+1"].mean_pct > 0


def test_digest_reports_a_filter_just_short_of_its_threshold_as_a_near_miss() -> None:
    rows = [
        _row(
            ORIGIN,
            "NO_SIGNAL",
            steps=[
                {
                    "stage": "filter",
                    "component": "vpin",
                    "verdict": "info",
                    "result": "normal",
                    "values": {"vpin": 0.68, "margin_pct": -2.86},
                    "thresholds": {"toxic_threshold": 0.7},
                }
            ],
        )
    ]
    digest = build_digest(rows)
    assert digest.near_misses == 1


def test_narrative_speaks_the_size_arithmetic() -> None:
    """A sizing step must read as the arithmetic, not fall through to the plan wording."""
    sized = render_narrative(
        _row(
            ORIGIN,
            "ENTRY_OPENED",
            steps=[
                {
                    "stage": "plan",
                    "component": "sizing",
                    "verdict": "emit",
                    "result": "sized",
                    "values": {
                        "equity": 10000,
                        "price": 2600,
                        "atr": 48.2,
                        "stop_distance": 96.4,
                        "risk_fraction": 0.01,
                        "risk_cash": 100.0,
                        "qty": 1.03,
                    },
                    "thresholds": {"risk_per_trade": 0.01, "qty_step": 0.01},
                }
            ],
        )
    )
    assert "equity 10000 × ризик 0.01 = 100" in sized
    assert "1.03 од." in sized
    assert "стеля 1× notional" not in sized, "the cap did not bind here"

    capped = render_narrative(
        _row(
            ORIGIN,
            "ENTRY_OPENED",
            steps=[
                {
                    "stage": "plan",
                    "component": "sizing",
                    "verdict": "emit",
                    "result": "sized at the 1x notional cap",
                    "values": {
                        "equity": 10000,
                        "risk_cash": 100.0,
                        "stop_distance": 16.17,
                        "risk_fraction": 0.01,
                        "qty_risk_based": 6.18,
                        "qty": 2.31,
                        "notional": 9999.99,
                        "notional_cap_hit": True,
                    },
                    "thresholds": {"qty_step": 0.01},
                }
            ],
        )
    )
    assert "стеля 1× notional" in capped, "a capped size must say the cap decided it"
    assert "6.18 до 2.31" in capped, "and by how much"
    assert "None" not in capped

    zero = render_narrative(
        _row(
            ORIGIN,
            "ENTRY_BLOCKED_RISK",
            steps=[
                {
                    "stage": "plan",
                    "component": "sizing",
                    "verdict": "block",
                    "result": "sized quantity is 0",
                    "values": {"risk_cash": 100.0, "stop_distance": 260.0, "qty": 0},
                    "thresholds": {"qty_step": 1},
                }
            ],
        )
    )
    assert "Розмір 0" in zero
    assert "кроку 1" in zero


def test_narrative_speaks_the_entry_filters_not_the_flow_reading() -> None:
    """The entry filters (docs/32) must not be narrated as a VPIN flow reading.

    Their steps carry `slope`/`vol_ratio`, not `vpin`, so the generic filter branch rendered
    the documented filters as `«HTF_TREND buy None / sell None — потік нормальний.»` —
    wrong numbers and wrong text, for exactly the switches a batch is run to test
    (docs/35 §7, L-13). Every branch is fed with the real steps `entry_filters.py` builds.
    """
    from nautilus_lab.domain.entry_filters import EntryFilter, EntryFilterParams
    from nautilus_lab.domain.signals import SignalSide

    entry_filter = EntryFilter(
        EntryFilterParams(
            htf_trend=True,
            vol_expansion=True,
            htf_ema_period=5,
            htf_slope_lookback=3,
            vol_fast_period=3,
            vol_slow_period=6,
        )
    )
    price = Decimal("100")
    for index in range(30):
        price += Decimal("1")
        entry_filter.update(
            OhlcvBar(
                instrument_id="ETH/USDT.SIM",
                ts_utc=ORIGIN + timedelta(hours=index),
                open=price,
                high=price + Decimal("2"),
                low=price - Decimal("2"),
                close=price,
                volume=Decimal("10"),
            )
        )
    # A rising series with a SELL side: both gates refuse, each in its own words.
    verdict = entry_filter.evaluate(SignalSide.SELL)
    row = _row(ORIGIN, "SIGNAL_VETOED")
    row["steps"] = [
        {
            "stage": item.stage.value,
            "component": item.component,
            "verdict": item.verdict.value,
            "result": item.result,
            "values": dict(item.values),
            "thresholds": dict(item.thresholds or {}),
        }
        for item in verdict.steps
    ]
    text = render_narrative(row)
    assert "None" not in text, f"a filter narrative must never print a missing value: {text}"
    assert "потік нормальний" not in text, "the flow wording belongs to the VPIN filter"
    assert "Фільтр тренду (HTF)" in text
    assert "нахил EMA5" in text
    assert "Фільтр волатильності" in text


def test_narrative_speaks_the_new_steps() -> None:
    fill = render_narrative(_fill(ORIGIN))
    assert "прослизання +100" in fill
    assert "Захисний стоп 96" in fill
    assert "вхідний ордер виконано" in fill

    vetoed = render_narrative(
        _row(
            ORIGIN,
            "SIGNAL_VETOED",
            steps=[
                {
                    "stage": "filter",
                    "component": "meta_label",
                    "verdict": "block",
                    "result": "reject",
                    "values": {"p_success": 0.4, "primary_side": "buy", "margin_pct": -27.3},
                    "thresholds": {"threshold": 0.55},
                }
            ],
        )
    )
    assert "ВІДХИЛЕНО" in vetoed
    assert "0.55" in vetoed

    ratchet = render_narrative(
        _row(
            ORIGIN,
            "RATCHET_EXIT",
            steps=[
                {
                    "stage": "plan",
                    "component": "ratchet",
                    "verdict": "emit",
                    "result": "exit",
                    "values": {"stop": 99.0, "prior_stop": 99.0, "close": 98.0, "adverse": 97.5},
                }
            ],
        )
    )
    assert "Ратчет-стоп 99" in ratchet
    assert "закрито ратчет-стопом" in ratchet

    pending = render_narrative(
        _row(
            ORIGIN,
            "PENDING_FILL",
            steps=[
                {
                    "stage": "gate",
                    "component": "execution.order_working",
                    "verdict": "info",
                    "result": "order not filled yet",
                    "values": {"order_id": "O-1", "order_side": "BUY"},
                }
            ],
        )
    )
    assert "ще не виконано" in pending

    vpin = render_narrative(
        _row(
            ORIGIN,
            "NO_SIGNAL",
            steps=[
                {
                    "stage": "filter",
                    "component": "vpin",
                    "verdict": "info",
                    "result": "normal",
                    "values": {"vpin": 0.62, "margin_pct": -11.4},
                    "thresholds": {"toxic_threshold": 0.7},
                }
            ],
        )
    )
    assert "поріг 0.7" in vpin
