"""The alpha screen on synthetic panels with a known answer."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from nautilus_lab.application.alpha.panel import FloatArray, Panel
from nautilus_lab.application.alpha.report import (
    dataset_key,
    record_trials,
    render_markdown,
    write_report,
)
from nautilus_lab.application.alpha.screen import (
    CONTROL_LEAK,
    CONTROL_RANDOM,
    ScreenConfig,
    ScreenReport,
    SignalResult,
    benjamini_hochberg,
    block_t,
    book_stats,
    decision_rows,
    forward_returns,
    rank_ic,
    run_screen,
    zone_segments,
)
from nautilus_lab.application.alpha.signals import TEMPLATES, Context, SignalSpec
from nautilus_lab.domain.data_zone import DataZone, TimeWindow, ZonePolicy

START = datetime(2020, 1, 1, tzinfo=UTC)
NAMES = 8
BARS = 24 * 400


def _policy() -> ZonePolicy:
    return ZonePolicy(
        exploration=(TimeWindow(START, datetime(2020, 12, 1, tzinfo=UTC)),),
        validation=(
            TimeWindow(datetime(2020, 12, 1, tzinfo=UTC), datetime(2021, 6, 1, tzinfo=UTC)),
        ),
        holdout=(),
        holdout_symbol_fraction=Decimal(0),
    )


def _synthetic(seed: int = 11) -> tuple[Panel, FloatArray, FloatArray]:
    """Returns = beta x market + idio + a persistent alpha that the signal knows."""
    rng = np.random.default_rng(seed)
    market = rng.normal(0.0001, 0.006, BARS)
    beta = rng.uniform(0.6, 1.6, NAMES)
    alpha = np.empty((BARS, NAMES))
    alpha[0] = rng.normal(size=NAMES)
    for t in range(1, BARS):
        alpha[t] = 0.98 * alpha[t - 1] + 0.2 * rng.normal(size=NAMES)
    returns = beta * market[:, None] + rng.normal(0, 0.008, (BARS, NAMES))
    returns[1:] += 0.0004 * alpha[:-1]
    close = 100.0 * np.cumprod(1.0 + returns, axis=0)
    ts = int(START.timestamp() // 60) + 60 * np.arange(BARS, dtype=np.int64)
    fields = {
        "close": close,
        "high": close * 1.001,
        "low": close * 0.999,
        "volume": np.full((BARS, NAMES), 1000.0),
    }
    panel = Panel(ts, tuple(f"C{i}USDT" for i in range(NAMES)), fields, bar_minutes=60)
    return panel, alpha, np.broadcast_to(beta, (BARS, NAMES)).copy()


def _spec(name: str, values: FloatArray) -> SignalSpec:
    def compute(_: Context) -> FloatArray:
        return values

    return SignalSpec(name, "test", "synthetic", ("close",), compute)


@pytest.fixture(scope="module")
def report() -> ScreenReport:
    panel, alpha, beta = _synthetic()
    specs = (_spec("true_alpha", alpha), _spec("beta_trap", beta))
    config = ScreenConfig(horizons=(1, 24), permutations=60)
    return run_screen(panel, policy=_policy(), config=config, templates=specs)


def _result(report: ScreenReport, name: str, horizon: int) -> SignalResult:
    return next(r for r in report.results if r.name == name and r.horizon == horizon)


def test_controls_pass(report: ScreenReport) -> None:
    assert report.controls_ok
    leak = _result(report, CONTROL_LEAK, 24)
    assert leak.ic_mean == pytest.approx(1.0)
    noise = _result(report, CONTROL_RANDOM, 24)
    assert abs(noise.ic_mean or 0.0) < 0.02


def test_a_real_signal_becomes_a_candidate(report: ScreenReport) -> None:
    result = _result(report, "true_alpha", 24)
    assert result.verdict == "candidate", result.reasons
    assert result.direction == 1
    assert (result.t_block or 0) > 5
    assert (result.perm_z or 0) > 5
    book = result.book_beta_neutral
    assert (book.sharpe_net or 0) > 1
    assert abs(book.market_corr or 1) < 0.1


def test_beta_is_not_alpha(report: ScreenReport) -> None:
    """Sorting on beta looks great on raw returns in a rising market; residuals say no."""
    result = _result(report, "beta_trap", 24)
    assert result.verdict == "reject"
    assert abs(result.ic_mean or 1) < 0.05


def test_turnover_kills_a_fast_horizon(report: ScreenReport) -> None:
    result = _result(report, "true_alpha", 1)
    assert any("breakeven" in reason for reason in result.reasons)


def test_only_exploration_can_be_screened() -> None:
    panel, _, _ = _synthetic()
    for zone in (DataZone.VALIDATION, DataZone.HOLDOUT):
        with pytest.raises(PermissionError, match="exploration only"):
            run_screen(panel, policy=_policy(), zone=zone)


def test_held_out_symbols_never_enter_the_screen() -> None:
    panel, alpha, _ = _synthetic()
    policy = ZonePolicy(
        exploration=_policy().exploration,
        validation=(),
        holdout=(),
        holdout_symbol_fraction=Decimal("0.3"),
    )
    held = policy.holdout_symbols(panel.symbols)
    assert held

    def by_symbol(ctx: Context) -> FloatArray:
        return alpha[:, [panel.symbols.index(s) for s in ctx.panel.symbols]]

    spec = SignalSpec("true_alpha", "test", "synthetic", ("close",), by_symbol)
    out = run_screen(
        panel,
        policy=policy,
        config=ScreenConfig(horizons=(24,), permutations=20),
        templates=(spec,),
    )
    assert set(out.held_out) == set(held)
    assert not set(out.symbols) & set(held)


def test_target_window_must_stay_inside_the_zone() -> None:
    panel, _, _ = _synthetic()
    segment = zone_segments(panel, _policy(), DataZone.EXPLORATION)
    rows = decision_rows(segment, 24)
    last_inside = int(np.flatnonzero(segment == 0).max())
    assert rows[last_inside - 24]
    assert not rows[last_inside - 23 :].any()


def test_forward_return_charges_funding_to_the_long() -> None:
    ts = np.arange(4, dtype=np.int64) * 60
    close = np.array([[100.0], [100.0], [100.0], [100.0]])
    paid = np.array([[np.nan], [0.001], [0.0], [0.002]])
    fields = {"close": close, "high": close, "low": close, "volume": close, "funding_paid": paid}
    panel = Panel(ts, ("A",), fields, bar_minutes=60)
    forward = forward_returns(panel, 2)
    assert forward[0, 0] == pytest.approx(-0.001)  # pays the settlements on bars 1 and 2
    assert forward[1, 0] == pytest.approx(-0.002)
    assert np.isnan(forward[2, 0])


def test_rank_ic_is_one_for_identical_ranks_and_needs_names() -> None:
    ranks = np.array([[-0.5, 0.0, 0.5], [-0.5, 0.5, np.nan]])
    ic = rank_ic(ranks, ranks, min_names=3)
    assert ic[0] == pytest.approx(1.0)
    assert np.isnan(ic[1])


def test_block_t_ignores_serial_correlation_inside_blocks() -> None:
    values = np.repeat(np.array([1.0, -1.0] * 10), 50)
    t, blocks = block_t(values, np.arange(values.size) // 50)
    assert blocks == 20
    assert t == pytest.approx(0.0)


def test_benjamini_hochberg_matches_the_textbook() -> None:
    q = benjamini_hochberg([0.01, 0.04, 0.03, None, 0.20])
    assert q[0] == pytest.approx(0.04)
    assert q[2] == pytest.approx(4 / 75)
    assert q[1] == pytest.approx(4 / 75)  # step-up
    assert q[3] is None
    assert q[4] == pytest.approx(0.20)


def test_book_with_constant_weights_has_no_turnover_after_warmup() -> None:
    rows = 400
    weights = np.tile([1.0, -1.0], (rows, 1))
    returns = np.tile([0.001, -0.001], (rows, 1))
    stats = book_stats(
        weights,
        5,
        returns,
        np.zeros(rows),
        np.arange(rows) >= 10,
        cost_bps=7.0,
        bars_per_year=8760.0,
    )
    assert stats.turnover == pytest.approx(0.0)
    assert stats.mean_bps == pytest.approx(10.0)  # 0.5 x 10 bps + 0.5 x 10 bps


def test_report_files_and_ledger(report: ScreenReport, tmp_path: Path) -> None:
    class Ledger:
        def __init__(self) -> None:
            self.calls: list[tuple[str, list[str]]] = []

        def record(self, dataset: str, trial_ids: Iterable[str]) -> int:
            self.calls.append((dataset, list(trial_ids)))
            return len(self.calls[-1][1])

    ledger = Ledger()
    total = record_trials(ledger, report, "synthetic_1h")
    dataset, trials = ledger.calls[0]
    assert dataset == dataset_key(report, "synthetic_1h")
    assert total == 4  # 2 signals x 2 horizons; controls are not trials
    assert all(not t.startswith("alpha|control") for t in trials)
    json_path, md_path = write_report(report, tmp_path, "synthetic_1h")
    assert json_path.exists()
    assert md_path.exists()
    text = render_markdown(report, "synthetic_1h")
    assert "true_alpha" in text
    assert "Кандидати" in text


def test_every_template_runs_on_a_full_panel() -> None:
    panel, _, _ = _synthetic()
    rng = np.random.default_rng(2)
    extra = {
        "taker_buy": panel.get("volume") * rng.uniform(0.3, 0.7, panel.shape),
        "funding_last": rng.normal(0.0001, 0.0001, panel.shape),
        "funding_paid": np.zeros(panel.shape),
        "premium": rng.normal(0.0, 0.0005, panel.shape),
    }
    full = Panel(panel.ts_min, panel.symbols, {**panel.fields, **extra}, panel.bar_minutes)
    out = run_screen(full, policy=_policy(), config=ScreenConfig(horizons=(24,), permutations=20))
    assert not out.skipped
    names = {r.name for r in out.results if not r.control}
    assert names == {spec.name for spec in TEMPLATES}
    # random data: the gate should let (almost) nothing through
    assert len(out.candidates) <= 1
