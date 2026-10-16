"""One shared account replaying many cells' trades (plan 2026-10-16, P1.5/1.6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from nautilus_lab.application.portfolio_replay import (
    ReplayRules,
    ReplayTrade,
    render_markdown,
    replay,
    trade_from_row,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _t(cell: str, start_h: int, end_h: int, r: float, side: str = "LONG") -> ReplayTrade:
    return ReplayTrade(
        cell=cell,
        side=side,
        ts_in=T0 + timedelta(hours=start_h),
        ts_out=T0 + timedelta(hours=end_h),
        r_net=r,
        fold=0,
    )


def test_uncapped_replay_sizes_every_trade_on_portfolio_equity() -> None:
    rules = ReplayRules(risk_per_trade=0.01, max_heat=None, max_per_side=None)
    result = replay([_t("a", 0, 10, 2.0), _t("b", 20, 30, -1.0)], rules)
    # +2R on 100k at 1% = +2000; then -1R on 102k = -1020
    assert result.ending_equity == pytest.approx(100_000 + 2_000 - 1_020)
    assert result.taken == 2
    assert result.pnl_by_cell == {"a": pytest.approx(2_000), "b": pytest.approx(-1_020)}


def test_heat_cap_skips_entries_while_the_book_is_full() -> None:
    rules = ReplayRules(risk_per_trade=0.01, max_heat=0.02, max_per_side=None)
    trades = [_t("a", 0, 10, -1.0), _t("b", 1, 10, -1.0), _t("c", 2, 10, -1.0)]
    result = replay(trades, rules)
    assert result.taken == 2
    assert result.skipped_heat == 1
    assert result.peak_heat == pytest.approx(0.02)


def test_an_exit_frees_its_slot_for_an_entry_at_the_same_instant() -> None:
    rules = ReplayRules(risk_per_trade=0.01, max_heat=0.01, max_per_side=None)
    result = replay([_t("a", 0, 5, 1.0), _t("b", 5, 9, 1.0)], rules)
    assert result.taken == 2
    assert result.skipped_heat == 0


def test_side_cap_counts_longs_and_shorts_separately() -> None:
    rules = ReplayRules(risk_per_trade=0.005, max_heat=None, max_per_side=1)
    trades = [
        _t("a", 0, 10, 1.0, "LONG"),
        _t("b", 1, 10, 1.0, "LONG"),
        _t("c", 2, 10, 1.0, "SHORT"),
    ]
    result = replay(trades, rules)
    assert result.taken == 2
    assert result.skipped_side == 1


def test_drawdown_is_measured_on_realised_equity() -> None:
    rules = ReplayRules(risk_per_trade=0.01, max_heat=None, max_per_side=None)
    result = replay([_t("a", 0, 1, 1.0), _t("b", 2, 3, -2.0), _t("c", 4, 5, -2.0)], rules)
    peak = 101_000.0
    trough = peak - 0.02 * peak
    trough -= 0.02 * trough
    assert result.max_drawdown == pytest.approx(1 - trough / peak)


def test_vol_target_scales_risk_down_after_a_volatile_stretch() -> None:
    # 10 days of big alternating results, then one more trade: the realised vol of the
    # account is far above 5%/year, so the next trade must risk less than the base 1%.
    trades = [_t(f"c{i}", 24 * i, 24 * i + 12, 3.0 if i % 2 else -3.0) for i in range(10)]
    probe = _t("probe", 24 * 10 + 1, 24 * 10 + 2, 1.0)
    fixed = replay([*trades, probe], ReplayRules(risk_per_trade=0.01, max_heat=None))
    targeted = replay(
        [*trades, probe], ReplayRules(risk_per_trade=0.01, max_heat=None, target_vol=0.05)
    )
    # clipped at min_scale=0.25 (the two accounts' equities differ a little by then)
    ratio = targeted.pnl_by_cell["probe"] / fixed.pnl_by_cell["probe"]
    assert 0.2 < ratio < 0.35


def test_trade_from_row_takes_funding_out_and_needs_a_stop() -> None:
    row = {
        "fold": 2,
        "side": "LONG",
        "ts_in": T0.isoformat(),
        "ts_out": (T0 + timedelta(hours=8)).isoformat(),
        "px_in": 100.0,
        "qty": 2.0,
        "stop": 98.0,
        "net": 8.0,
        "funding": 0.4,
    }
    trade = trade_from_row("regime_BTC", row)
    assert trade is not None
    assert trade.r_net == pytest.approx((8.0 - 0.4) / 4.0)
    assert trade.fold == 2
    assert trade_from_row("regime_BTC", {**row, "stop": None}) is None


def test_rules_refuse_a_heat_cap_below_one_trade() -> None:
    with pytest.raises(ValueError, match="max_heat"):
        ReplayRules(risk_per_trade=0.01, max_heat=0.005)


def test_markdown_names_every_replay() -> None:
    rules = ReplayRules(max_heat=None, max_per_side=None)
    text = render_markdown({"uncapped": replay([_t("a", 0, 30, 1.0)], rules)})
    assert "| uncapped | 1 |" in text
