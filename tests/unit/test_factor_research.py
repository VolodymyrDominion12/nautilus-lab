from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.application.dtos import BacktestReport
from nautilus_lab.application.evaluate_recipe import pearson, score_recipe
from nautilus_lab.application.score import DEFAULT_TURNOVER_HAIRCUT, in_sample_score
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.counterfactual import perturb_bars
from nautilus_lab.domain.errors import InvalidHypothesisError, InvalidRiskError
from nautilus_lab.domain.factor_dsl import (
    crowding_hits,
    evaluate_recipe,
    parse_recipe,
    recipe_complexity,
)
from nautilus_lab.domain.metrics import BacktestMetrics
from nautilus_lab.domain.ratchet_stop import (
    RatchetParams,
    initial_ratchet,
    ratchet_hit,
    update_ratchet,
)
from nautilus_lab.domain.signals import SignalSide


def _report(
    balance: Decimal | None,
    *,
    fees: Decimal = Decimal("0"),
    turnover: Decimal = Decimal("0"),
    with_metrics: bool = True,
) -> BacktestReport:
    metrics = None
    if with_metrics:
        metrics = BacktestMetrics(
            fees_paid=fees,
            max_drawdown=Decimal("0.01"),
            turnover=turnover,
            sharpe_like=Decimal("1"),
        )
    return BacktestReport(
        fills=1,
        positions=1,
        ending_balance=balance,
        notes="test",
        metrics=metrics,
    )


def test_in_sample_score_ranks_missing_balance_last() -> None:
    missing = _report(None, with_metrics=False)
    present = _report(Decimal("1"), with_metrics=False)
    assert in_sample_score(missing) < in_sample_score(present)


def test_in_sample_score_does_not_double_count_fees() -> None:
    """Fees already reduced the balance; subtracting them again would punish twice."""
    report = _report(Decimal("100000"), fees=Decimal("500"), turnover=Decimal("0"))
    assert in_sample_score(report) == Decimal("100000")


def test_in_sample_score_penalises_turnover() -> None:
    quiet = _report(Decimal("110000"), turnover=Decimal("10000"))
    busy = _report(Decimal("110000"), turnover=Decimal("1000000"))
    assert in_sample_score(quiet) > in_sample_score(busy)
    haircut = DEFAULT_TURNOVER_HAIRCUT * Decimal("1000000")
    assert in_sample_score(busy) == Decimal("110000") - haircut


def test_in_sample_score_without_metrics_is_the_balance() -> None:
    report = _report(Decimal("105000"), with_metrics=False)
    assert in_sample_score(report) == Decimal("105000")


def test_in_sample_score_rejects_negative_haircut() -> None:
    with pytest.raises(ValueError, match="turnover_haircut"):
        in_sample_score(_report(Decimal("1")), turnover_haircut=Decimal("-0.1"))


def _feature_rows(length: int = 8) -> list[dict[str, Decimal]]:
    rows: list[dict[str, Decimal]] = []
    for index in range(length):
        ret = Decimal(index - 3) / Decimal("10")
        rows.append(
            {
                "ret": ret,
                "volume_ratio": Decimal("1") + Decimal(index) / Decimal("10"),
                "reversal_3": -ret,
                "momentum_10": Decimal(index) / Decimal("10"),
                "trend_er": Decimal("0.5"),
            }
        )
    return rows


def test_parse_recipe_combines_existing_features() -> None:
    node = parse_recipe("-reversal_3 * zscore(volume_ratio)")
    assert recipe_complexity(node) > 0
    rows = _feature_rows()
    value = evaluate_recipe(node, rows, index=len(rows) - 1)
    assert value is not None


def test_parse_recipe_rejects_unknown_feature() -> None:
    with pytest.raises(InvalidHypothesisError, match="unknown feature"):
        parse_recipe("abs(order_flow_toxicity)")


def test_parse_recipe_rejects_cross_sectional_ops() -> None:
    with pytest.raises(InvalidHypothesisError, match="cross-sectional"):
        parse_recipe("rank(ret)")
    with pytest.raises(InvalidHypothesisError, match="cross-sectional"):
        parse_recipe("corr(ret, volume_ratio)")


def test_parse_recipe_rejects_a_bare_feature() -> None:
    with pytest.raises(InvalidHypothesisError, match="single raw column"):
        parse_recipe("momentum_10")


def test_delay_is_point_in_time() -> None:
    rows = _feature_rows()
    node = parse_recipe("delay(ret, 2)")
    current = rows[5]["ret"]
    lagged = evaluate_recipe(node, rows, index=5)
    assert lagged == rows[3]["ret"]
    assert lagged != current


def test_ts_mean_needs_a_full_window() -> None:
    rows = _feature_rows()
    node = parse_recipe("ts_mean(ret, 3)")
    assert evaluate_recipe(node, rows, index=1) is None
    value = evaluate_recipe(node, rows, index=4)
    expected = (rows[2]["ret"] + rows[3]["ret"] + rows[4]["ret"]) / Decimal("3")
    assert value == expected


def test_crowding_flags_window_clones() -> None:
    first = parse_recipe("ts_mean(ret, 10)")
    clone = parse_recipe("ts_mean(ret, 20)")
    different = parse_recipe("abs(volume_ratio)")
    assert crowding_hits(clone, [first]) == (0,)
    assert crowding_hits(different, [first]) == ()


def test_clip_and_log_guard_domain() -> None:
    rows = [{"ret": Decimal("-0.5"), "volume_ratio": Decimal("2")}]
    assert evaluate_recipe(parse_recipe("log(ret)"), rows, index=0) is None
    clipped = evaluate_recipe(parse_recipe("clip(ret, -0.1, 0.1)"), rows, index=0)
    assert clipped == Decimal("-0.1")


def _bars(count: int = 80) -> list[OhlcvBar]:
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[OhlcvBar] = []
    price = Decimal("100")
    for index in range(count):
        price += Decimal("0.8") if index % 4 else Decimal("-0.3")
        bars.append(
            OhlcvBar(
                instrument_id="ETH/USDT.SIM",
                ts_utc=origin + timedelta(hours=index),
                open=price - Decimal("0.2"),
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price,
                volume=Decimal("100") + Decimal(index),
            )
        )
    return bars


def test_score_recipe_rejects_bad_horizon_and_sign() -> None:
    bars = _bars(40)
    with pytest.raises(ValueError, match="horizon_bars"):
        score_recipe(bars, "abs(ret)", horizon_bars=0)
    with pytest.raises(ValueError, match="expected_sign"):
        score_recipe(bars, "abs(ret)", horizon_bars=3, expected_sign=0)


def test_score_recipe_returns_ic_and_counterfactual() -> None:
    score = score_recipe(_bars(), "trend_er * momentum_10", horizon_bars=3, expected_sign=1)
    assert score.observations > 10
    assert score.information_coefficient is not None
    assert score.counterfactual_ic is not None
    assert score.crowding_index == ()
    assert 0 <= (score.hit_rate or Decimal("0")) <= 1


def test_score_recipe_reports_crowding_against_a_pool() -> None:
    pool = [parse_recipe("ts_mean(ret, 8)")]
    score = score_recipe(
        _bars(),
        "ts_mean(ret, 12)",
        horizon_bars=3,
        pool=pool,
    )
    assert score.crowding_index == (0,)


def test_parse_recipe_rejects_empty_and_junk() -> None:
    with pytest.raises(InvalidHypothesisError, match="empty"):
        parse_recipe("   ")
    with pytest.raises(InvalidHypothesisError, match="unexpected character"):
        parse_recipe("ret $ momentum_10")


def test_crowding_hits_rejects_bad_threshold() -> None:
    node = parse_recipe("abs(ret)")
    with pytest.raises(ValueError, match="max_similarity"):
        crowding_hits(node, [], max_similarity=Decimal("1.5"))


def test_perturb_bars_rejects_negative_magnitude_and_empty_input() -> None:
    assert perturb_bars([], magnitude=Decimal("0.01")) == []
    with pytest.raises(ValueError, match="magnitude"):
        perturb_bars(_bars(3), magnitude=Decimal("-0.01"))
    score = score_recipe(_bars(), "trend_er * momentum_10", horizon_bars=3, expected_sign=1)
    assert score.observations > 10
    assert score.information_coefficient is not None
    assert score.counterfactual_ic is not None
    assert score.crowding_index == ()
    assert 0 <= (score.hit_rate or Decimal("0")) <= 1


def test_perturb_bars_changes_closes_but_keeps_invariants() -> None:
    original = _bars(12)
    shocked = perturb_bars(original, magnitude=Decimal("0.05"), seed=7)
    assert len(shocked) == len(original)
    assert shocked[0].close == original[0].close
    assert any(
        left.close != right.close for left, right in zip(original[1:], shocked[1:], strict=True)
    )
    for bar in shocked:
        assert bar.high >= max(bar.open, bar.close)
        assert bar.low <= min(bar.open, bar.close)
    again = perturb_bars(original, magnitude=Decimal("0.05"), seed=7)
    assert [item.close for item in again] == [item.close for item in shocked]


def test_pearson_is_none_on_constant_series() -> None:
    constants = [Decimal("1"), Decimal("1"), Decimal("1")]
    varying = [Decimal("1"), Decimal("2"), Decimal("3")]
    assert pearson(constants, varying) is None
    perfect = pearson(varying, varying)
    assert perfect is not None
    assert abs(perfect - Decimal("1")) < Decimal("0.0000001")


def test_ratchet_starts_at_the_tighter_protective_stop() -> None:
    params = RatchetParams(max_loss_pct=Decimal("0.02"))
    state = initial_ratchet(
        entry_price=Decimal("100"),
        side=SignalSide.BUY,
        params=params,
        atr_distance=Decimal("1"),
    )
    assert state.stop_price == Decimal("99")
    assert not state.armed


def test_ratchet_never_loosens_after_locking() -> None:
    params = RatchetParams(max_loss_pct=Decimal("0.01"), arm_pct=Decimal("0.0125"))
    state = initial_ratchet(entry_price=Decimal("100"), side=SignalSide.BUY, params=params)
    armed = update_ratchet(state, Decimal("101.30"), params)
    assert armed.armed
    assert armed.stop_price == Decimal("100")
    locked = update_ratchet(armed, Decimal("108"), params)
    assert locked.stop_price == Decimal("104")
    pullback = update_ratchet(locked, Decimal("102"), params)
    assert pullback.stop_price == Decimal("104")
    assert ratchet_hit(pullback, Decimal("103.9"))
    assert not ratchet_hit(pullback, Decimal("104.1"))


def test_short_ratchet_hits_when_price_rallies_through_the_ceiling() -> None:
    params = RatchetParams(max_loss_pct=Decimal("0.01"), arm_pct=Decimal("0.0125"))
    state = initial_ratchet(entry_price=Decimal("100"), side=SignalSide.SELL, params=params)
    assert state.stop_price == Decimal("101")
    armed = update_ratchet(state, Decimal("98.70"), params)
    assert armed.stop_price == Decimal("100")
    assert ratchet_hit(armed, Decimal("100.1"))


def test_ratchet_params_reject_inverted_lock_levels() -> None:
    with pytest.raises(InvalidRiskError, match="below its trigger"):
        RatchetParams(lock_levels=((Decimal("0.08"), Decimal("0.09")),))
