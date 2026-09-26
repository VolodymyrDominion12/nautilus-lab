"""decision_trace/1: every closed bar explains itself, and the explanation is true.

The v0 log was written before execution (no outcome), left the regime robot's
indicators empty, and said nothing when a strategy held. These tests pin the chain
bar -> regime -> filters -> strategy -> plan -> gates -> execution for the robots the
paper terminal can run, and that tracing never changes a single signal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from nautilus_lab.api.paper_streamer import LivePaperConfig, LivePaperSessionManager
from nautilus_lab.application.decision_analysis import analyze_records, resolve_question
from nautilus_lab.application.decision_digest import build_digest, build_prompt, digest_markdown
from nautilus_lab.application.decision_narrative import render_narrative
from nautilus_lab.application.decision_trace_codec import record_to_dict, upgrade_row
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.decision_log import DecisionRecord
from nautilus_lab.domain.decision_trace import Outcome, Stage, Verdict
from nautilus_lab.domain.donchian import UptrendBreakout
from nautilus_lab.domain.mean_reversion import RangeMeanReversion
from nautilus_lab.domain.regime import RegimeParams
from nautilus_lab.domain.regime_router import RegimeRouter
from nautilus_lab.domain.signals import Signal, SignalSide
from nautilus_lab.infrastructure.decision_log_writer import JsonlDecisionLogWriter
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_ohlcv
from nautilus_lab.infrastructure.settings import Settings

T0 = datetime(2026, 9, 1, tzinfo=UTC)


class MemoryLog:
    def __init__(self) -> None:
        self.records: list[DecisionRecord] = []

    def log(self, record: DecisionRecord) -> None:
        self.records.append(record)

    def rows(self) -> list[dict[str, Any]]:
        return [record_to_dict(r) for r in self.records]


def _bar(i: int, close: str, *, high: str | None = None, low: str | None = None) -> OhlcvBar:
    price = Decimal(close)
    return OhlcvBar(
        instrument_id="ETHUSDT",
        ts_utc=T0 + timedelta(hours=i),
        open=price,
        high=Decimal(high) if high else price + Decimal("1"),
        low=Decimal(low) if low else price - Decimal("1"),
        close=price,
        volume=Decimal("10"),
    )


def _feed(manager: LivePaperSessionManager, bar: OhlcvBar) -> list[str]:
    return manager.process_kline_update(
        time_sec=int(bar.ts_utc.timestamp()),
        open_price=bar.open,
        high_price=bar.high,
        low_price=bar.low,
        close_price=bar.close,
        volume=bar.volume,
        is_closed=True,
    )


def _session(robot: str, **config: Any) -> tuple[LivePaperSessionManager, MemoryLog]:
    log = MemoryLog()
    manager = LivePaperSessionManager(
        LivePaperConfig(symbol="ETHUSDT", robot=robot, **config), decision_log=log
    )
    manager.is_active = True
    manager.session_id = f"{robot}-test"
    return manager, log


# ------------------------------------------------------------------------ robots


def test_regime_robot_logs_er_and_slope_after_warm_up() -> None:
    """v0 bug: the regime robot's `indicators` were always empty."""
    manager, log = _session("regime", auto_trade=False)
    for bar in synthetic_ohlcv(instrument_id="ETHUSDT", count=120, seed=3):
        _feed(manager, bar)

    last = log.records[-1]
    regime_steps = [s for s in last.steps if s.stage is Stage.REGIME]
    assert regime_steps, "a warmed-up regime robot must explain its regime"
    assert {"er", "slope"} <= set(regime_steps[0].values)
    assert "applied_er" in regime_steps[0].thresholds
    assert "er" in last.indicators
    assert "slope" in last.indicators
    assert last.regime in {"uptrend", "downtrend", "range"}


def test_early_bars_are_warm_up_not_no_signal() -> None:
    manager, log = _session("regime")
    for bar in synthetic_ohlcv(instrument_id="ETHUSDT", count=5, seed=3):
        _feed(manager, bar)
    assert {r.outcome for r in log.records} == {Outcome.WARMUP.value}
    assert all(r.regime == "WARMUP" for r in log.records)
    assert "прогрів" in (log.records[0].narrative or "")


def test_every_closed_bar_gives_one_record_with_consecutive_seq() -> None:
    manager, log = _session("ema", fast_ema=5, slow_ema=10)
    bars = synthetic_ohlcv(instrument_id="ETHUSDT", count=60, seed=7)
    for bar in bars:
        _feed(manager, bar)
    decisions = [r for r in log.records if r.kind.value == "bar_decision"]
    assert len(decisions) == len(bars)
    assert [r.bar_seq for r in decisions] == list(range(1, len(bars) + 1))
    assert all(r.schema == "decision_trace/1" and r.narrative for r in decisions)


def test_tracing_does_not_change_any_signal() -> None:
    """The trace is read-only: a traced robot and the same robot's signals are identical."""
    params = RegimeParams()
    bars = synthetic_ohlcv(instrument_id="ETHUSDT", count=400, seed=11)
    first, second = (
        RegimeRouter(instrument_id="ETHUSDT", params=params),
        RegimeRouter(instrument_id="ETHUSDT", params=params),
    )
    a = [first.on_bar(b) for b in bars]
    b = []
    for bar in bars:
        b.append(second.on_bar(bar))
        _ = second.last_trace  # reading the trace between bars must not matter
    assert [(s.side, s.reason) if s else None for s in a] == [
        (s.side, s.reason) if s else None for s in b
    ]
    assert any(s is not None for s in a)


def test_donchian_hold_reports_distance_to_breakout() -> None:
    leg = UptrendBreakout(instrument_id="ETHUSDT", channel_period=3, ema_period=2)
    for i, close in enumerate(["100", "101", "102", "103"]):
        leg.on_bar(_bar(i, close, high=str(int(close) + 1)))
    signal = leg.on_bar(_bar(4, "103.5", high="103.6"))
    assert signal is None
    (info,) = leg.last_trace
    assert info.verdict is Verdict.INFO
    assert info.values["prior_high"] == Decimal("104")
    assert Decimal(str(info.values["dist_to_breakout_pct"])) < 0


def test_range_leg_reports_bands_and_z() -> None:
    leg = RangeMeanReversion(instrument_id="ETHUSDT", period=5, band_k=Decimal("2"))
    for i, close in enumerate(["100", "101", "99", "100", "101"]):
        leg.on_bar(_bar(i, close))
    leg.on_bar(_bar(5, "100.4"))
    (item,) = leg.last_trace
    assert {"mean", "upper", "lower", "z"} <= set(item.values)


# ------------------------------------------------------------------------ outcomes


def _signal(side: SignalSide, reason: str = "test") -> Signal:
    return Signal(instrument_id="ETHUSDT", side=side, bar_ts_utc=T0, reason=reason)


def test_risk_block_is_recorded_with_the_breaker_and_its_numbers() -> None:
    manager, _ = _session("ema")
    manager._peak_equity = manager.current_equity * Decimal("2")  # 50% drawdown

    result = manager._execute_signal(_signal(SignalSide.BUY), Decimal("100"))

    assert result.outcome is Outcome.ENTRY_BLOCKED_RISK
    assert result.blocked_by == "risk.max_drawdown"
    gate = result.steps[-1]
    assert gate.verdict is Verdict.BLOCK
    assert gate.values["value"] == Decimal("0.5")
    assert gate.thresholds["limit"] == manager.config.max_drawdown


def test_entry_and_reverse_carry_the_fill_ids() -> None:
    manager, _ = _session("ema")
    opened = manager._execute_signal(_signal(SignalSide.BUY), Decimal("100"))
    assert opened.outcome is Outcome.ENTRY_OPENED
    assert opened.fill_ids == [manager.fills[-1].id]

    reversed_ = manager._execute_signal(_signal(SignalSide.SELL), Decimal("101"))
    assert reversed_.outcome is Outcome.REVERSE
    assert reversed_.fill_ids == [f.id for f in manager.fills[-2:]]
    assert [s.result for s in reversed_.steps if s.stage is Stage.EXECUTION] == ["exit", "entry"]


def test_same_side_signal_is_a_noop_not_a_trade() -> None:
    manager, _ = _session("ema")
    manager._execute_signal(_signal(SignalSide.BUY), Decimal("100"))
    again = manager._execute_signal(_signal(SignalSide.BUY), Decimal("100"))
    assert again.outcome is Outcome.HOLD_NOOP
    assert again.fill_ids == []


def test_regime_change_flatten_is_not_a_plain_exit() -> None:
    manager, _ = _session("regime")
    manager._execute_signal(_signal(SignalSide.BUY), Decimal("100"))
    flat = manager._execute_signal(
        _signal(SignalSide.FLAT, "regime change to range"), Decimal("100")
    )
    assert flat.outcome is Outcome.FLATTEN_REGIME_CHANGE


def test_paused_and_auto_trade_off_are_distinct_outcomes() -> None:
    manager, _ = _session("ema")
    manager.paused = True
    assert (
        manager._execute_signal(_signal(SignalSide.BUY), Decimal("100")).outcome
        is Outcome.ENTRY_SKIPPED_PAUSED
    )
    manager.paused = False
    manager.config.auto_trade = False
    result = manager._decide(_signal(SignalSide.BUY), Decimal("100"), ())
    assert result.outcome is Outcome.AUTO_TRADE_OFF
    assert manager.position is None


def test_bar_record_is_written_after_execution() -> None:
    """The v0 record was written before `_apply_signal` and could not know the outcome."""
    manager, log = _session("hold")
    _feed(manager, _bar(0, "100"))
    first = log.records[-1]
    assert first.outcome == Outcome.ENTRY_OPENED.value
    assert first.fill_ids == (manager.fills[-1].id,)
    assert first.account["position"] == "FLAT"  # the account the decision was made on

    _feed(manager, _bar(1, "101"))
    assert log.records[-1].outcome == Outcome.HOLD_NOOP.value


def test_stop_loss_is_an_intrabar_record_in_the_same_log() -> None:
    manager, log = _session("ema", auto_trade=False)
    manager._open_position_internal("LONG", Decimal("100"))
    stop = manager._pos_sl
    assert stop is not None
    manager.process_kline_update(
        time_sec=int(T0.timestamp()),
        open_price=Decimal("100"),
        high_price=Decimal("100"),
        low_price=stop - Decimal("1"),
        close_price=stop,
        volume=Decimal("1"),
        is_closed=False,
    )
    (event,) = [r for r in log.records if r.kind.value == "intrabar"]
    assert event.outcome == Outcome.STOP_LOSS.value
    assert event.fill_ids == (manager.fills[-1].id,)
    assert "Стоп-лос" in (event.narrative or "")


def test_pause_change_is_recorded() -> None:
    manager, log = _session("ema")
    manager.record_pause_change(True)
    assert log.records[-1].outcome == Outcome.PAUSED.value


def test_a_failing_decision_log_never_stops_trading() -> None:
    class Broken:
        def log(self, record: DecisionRecord) -> None:
            raise OSError("disk full")

    manager = LivePaperSessionManager(
        LivePaperConfig(symbol="ETHUSDT", robot="hold"), decision_log=Broken()
    )
    manager.is_active = True
    _feed(manager, _bar(0, "100"))
    assert manager.position is not None


# ------------------------------------------------------------------------ narrative


def test_narrative_explains_a_blocked_entry_in_ukrainian() -> None:
    manager, log = _session("hold")
    manager._peak_equity = manager.current_equity * Decimal("2")
    _feed(manager, _bar(0, "100"))
    text = log.records[-1].narrative or ""
    assert "Бенчмарк" in text
    assert "ЗАБЛОКУВАВ" in text
    assert "просідання" in text
    assert text.endswith("Підсумок: вхід заблоковано ризиком.")


def test_v0_rows_are_upgraded_and_still_readable() -> None:
    v0 = {
        "ts": "2026-09-25T12:00:00+00:00",
        "robot": "regime",
        "instrument": "ETHUSDT",
        "close": "2650.5",
        "regime": "uptrend",
        "signal": "buy",
        "signal_reason": "donchian breakout long",
        "indicators": {},
        "states": {},
    }
    row = upgrade_row(v0)
    assert row["outcome"] == "UNKNOWN_V0"
    assert row["steps"] == []
    text = render_narrative(row)
    assert "UPTREND" in text
    assert "BUY" in text


# ------------------------------------------------------------------------ writer + digest


def _writer(tmp_path: Path) -> JsonlDecisionLogWriter:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, decision_log_enabled=True, decision_log_dir="data/paper/decisions"
    )
    return JsonlDecisionLogWriter(settings, root=tmp_path)


def test_writer_round_trip_and_outcome_filter(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    manager, _ = _session("ema", fast_ema=3, slow_ema=6)
    manager.decision_log = writer
    for bar in synthetic_ohlcv(instrument_id="ETHUSDT", count=40, seed=5):
        _feed(manager, bar)

    everything = writer.get_recent_logs("ema-test", lines=1000)
    assert len(everything) == 40
    assert everything[-1]["schema"] == "decision_trace/1"
    assert isinstance(everything[-1]["steps"][0]["values"]["fast_ema"], float)
    warm = writer.get_recent_logs("ema-test", lines=1000, outcomes=["warmup"])
    assert warm
    assert all(r["outcome"] == "WARMUP" for r in warm)


def _rows_for_digest() -> list[dict[str, Any]]:
    rows = []
    closes = [100, 101, 102, 103, 104, 103, 102, 101]
    for i, close in enumerate(closes):
        outcome = "NO_SIGNAL"
        signal = None
        blocked_by = None
        if i == 1:
            outcome, signal = "ENTRY_OPENED", "buy"
        if i == 4:
            outcome, signal, blocked_by = "ENTRY_BLOCKED_RISK", "sell", "risk.max_daily_loss"
        rows.append(
            {
                "schema": "decision_trace/1",
                "kind": "bar_decision",
                "ts": (T0 + timedelta(hours=i)).isoformat(),
                "session_id": "regime-eth-1",
                "robot": "regime",
                "instrument": "ETHUSDT",
                "close": str(close),
                "regime": "uptrend" if i < 4 else "range",
                "signal": signal,
                "outcome": outcome,
                "blocked_by": blocked_by,
                "bar_seq": i + 1,
                "steps": [],
            }
        )
    return rows


def test_digest_counts_and_signs_forward_returns() -> None:
    digest = build_digest(_rows_for_digest(), horizons=(1, 2))
    assert digest.outcomes["ENTRY_OPENED"] == 1
    assert digest.blocked_by == {"risk.max_daily_loss": 1}
    # BUY at 101 -> 102 (+1 bar): positive.
    assert digest.forward["executed"]["+1"].mean_pct == pytest.approx(0.9901, abs=1e-3)
    # SELL blocked at 104 -> 103: the block cost a winning short (positive = the signal was right).
    assert digest.forward["blocked"]["+1"].mean_pct == pytest.approx(0.9615, abs=1e-3)
    assert digest.regime_switches == 1
    assert digest.bar_seq_gaps == 0
    md = digest_markdown(digest)
    assert "risk.max_daily_loss: 1" in md
    system, user = build_prompt(digest, "Чому так мало угод?")
    assert "гіпотез" in system
    assert user.rstrip().endswith("Чому так мало угод?")


def test_analyze_without_a_model_returns_the_digest_not_invented_text() -> None:
    body = analyze_records(
        _rows_for_digest(), question=resolve_question("", "blocking_filter"), completer=None
    )
    assert body["status"] == "no_llm"
    assert body["analysis"] is None
    assert "15%" not in body["markdown"]
    assert body["digest"]["outcomes"]["ENTRY_BLOCKED_RISK"] == 1
    assert "блокує" in body["question"]


def test_analyze_with_a_model_saves_a_reproducible_report(tmp_path: Path) -> None:
    class FakeModel:
        def __init__(self) -> None:
            self.user = ""

        def complete(self, *, system: str, user: str) -> str:
            self.user = user
            return "Гіпотеза: денний ліміт відсік прибуткові шорти."

    model = FakeModel()
    body = analyze_records(
        _rows_for_digest(),
        question="Що блокувало?",
        completer=model,
        model="fake",
        reports_dir=tmp_path / "reports",
        root=tmp_path,
        session_id="regime-eth-1",
    )
    assert body["status"] == "ok"
    assert body["analysis"].startswith("Гіпотеза")
    assert "risk.max_daily_loss" in model.user
    saved = tmp_path / body["report"]
    assert saved.is_file()
    assert "Що блокувало?" in saved.read_text(encoding="utf-8")
