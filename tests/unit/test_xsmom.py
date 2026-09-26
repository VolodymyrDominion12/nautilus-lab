from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from random import Random

import pytest

from nautilus_lab.application.promotion_gate import evaluate_gate
from nautilus_lab.application.run_xsmom import (
    XsMomGrid,
    XsMomRequest,
    run_xsmom_audit,
    run_xsmom_walk_forward,
)
from nautilus_lab.application.xsmom_backtest import run_xsmom
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.fees import FeeSchedule
from nautilus_lab.domain.xsmom import (
    Weighting,
    XsMomParams,
    momentum_score,
    target_weights,
)

T0 = datetime(2024, 1, 1, tzinfo=UTC)
FEES = FeeSchedule.binance_spot_vip0()


def _series(symbol: str, drifts: list[float], seed: int) -> list[OhlcvBar]:
    rng = Random(seed)
    price = Decimal("100")
    bars: list[OhlcvBar] = []
    for index, drift in enumerate(drifts):
        change = Decimal(str(drift + rng.uniform(-0.01, 0.01)))
        close = (price * (1 + change)).quantize(Decimal("0.0001"))
        bars.append(
            OhlcvBar(
                instrument_id=symbol,
                ts_utc=T0 + timedelta(days=index + 1),
                open=price,
                high=max(price, close) * Decimal("1.001"),
                low=min(price, close) * Decimal("0.999"),
                close=close,
                volume=Decimal("1000"),
            )
        )
        price = close
    return bars


def _basket(count: int = 600) -> dict[str, list[OhlcvBar]]:
    """Leadership rotates every 100 days between A, B and C; D never trends."""
    leaders = ["A", "B", "C"]
    drifts: dict[str, list[float]] = {s: [] for s in ("A", "B", "C", "D")}
    for day in range(count):
        leader = leaders[(day // 100) % 3]
        for symbol in drifts:
            drifts[symbol].append(0.008 if symbol == leader else -0.001)
    return {s: _series(s, d, seed) for seed, (s, d) in enumerate(drifts.items())}


# --- domain -------------------------------------------------------------------------


def test_momentum_score_skips_the_most_recent_bar() -> None:
    closes = [Decimal(value) for value in ("100", "110", "121", "50")]
    assert momentum_score(closes, lookback=2, skip=1) == Decimal("0.21")
    assert momentum_score(closes, lookback=3, skip=1) is None


def test_target_weights_rank_filter_and_keep_empty_slots_in_cash() -> None:
    params = XsMomParams(lookback_bars=2, skip_bars=0, top_n=2, require_positive=True)
    closes = {
        "UP": [Decimal("100"), Decimal("105"), Decimal("120")],
        "DOWN": [Decimal("100"), Decimal("95"), Decimal("90")],
        "FLAT": [Decimal("100"), Decimal("100"), Decimal("100")],
    }
    weights = target_weights(closes, params)
    # Only one coin has positive momentum: it gets one slot, the other slot is cash.
    assert weights == {"UP": Decimal("0.5")}


def test_target_weights_without_the_filter_rank_everything() -> None:
    params = XsMomParams(lookback_bars=2, skip_bars=0, top_n=2, require_positive=False)
    closes = {
        "A": [Decimal("100"), Decimal("100"), Decimal("90")],
        "B": [Decimal("100"), Decimal("100"), Decimal("95")],
        "C": [Decimal("100"), Decimal("100"), Decimal("80")],
    }
    assert set(target_weights(closes, params)) == {"A", "B"}


def test_inverse_vol_weights_sum_to_the_filled_share() -> None:
    params = XsMomParams(
        lookback_bars=3, skip_bars=0, top_n=2, weighting=Weighting.INVERSE_VOL, vol_window=3
    )
    closes = {
        "CALM": [Decimal(v) for v in ("100", "101", "102", "103")],
        "WILD": [Decimal(v) for v in ("100", "110", "104", "115")],
    }
    weights = target_weights(closes, params)
    assert sum(weights.values()) == pytest.approx(Decimal("1"))
    assert weights["CALM"] > weights["WILD"]


# --- simulator ----------------------------------------------------------------------


def test_future_bars_never_change_the_past() -> None:
    """Decide on close t, fill on open t+1: truncating the future must not alter history."""
    basket = _basket(300)
    params = XsMomParams(lookback_bars=20, top_n=2, rebalance_every=5)
    full = run_xsmom(basket, params, starting_equity=Decimal("100000"), fees=FEES)
    cut = 200
    truncated = run_xsmom(
        {s: bars[:cut] for s, bars in basket.items()},
        params,
        starting_equity=Decimal("100000"),
        fees=FEES,
    )
    assert full.equity_curve[:cut] == truncated.equity_curve


def test_costs_are_charged_and_cash_never_goes_negative() -> None:
    basket = _basket(300)
    run = run_xsmom(
        basket,
        XsMomParams(lookback_bars=20, top_n=2, rebalance_every=5),
        starting_equity=Decimal("100000"),
        fees=FEES,
    )
    assert run.trades > 0
    assert run.fees_paid > 0
    # Taker fee on (roughly) every traded unit of notional.
    assert run.fees_paid == pytest.approx(run.traded_notional * FEES.taker, rel=Decimal("0.01"))
    assert min(run.equity_curve) > 0


def test_warm_up_bars_are_not_traded_or_recorded() -> None:
    basket = _basket(300)
    start = basket["A"][100].ts_utc
    run = run_xsmom(
        basket,
        XsMomParams(lookback_bars=20),
        starting_equity=Decimal("100000"),
        fees=FEES,
        trade_start=start,
    )
    assert len(run.equity_curve) == 200
    assert run.first_ts == start


def test_misaligned_series_are_refused() -> None:
    basket = _basket(50)
    basket["A"] = basket["A"][1:]
    with pytest.raises(ValueError, match="not aligned"):
        run_xsmom(basket, XsMomParams(), starting_equity=Decimal("1"), fees=FEES)


# --- walk-forward, audit, gate -------------------------------------------------------


def test_walk_forward_rotates_into_the_leader_and_is_gate_readable() -> None:
    basket = _basket(600)
    request = XsMomRequest(
        grid=XsMomGrid(lookback_bars=(10, 20), top_n=(1,), rebalance_every=(5,)),
        folds=3,
        in_sample_fraction=Decimal("0.5"),
    )
    report = run_xsmom_walk_forward(basket, request)

    assert len(report.folds) == 3
    assert report.total_oos_fills > 0
    # The planted rotation is strong: holding the leader beats holding the basket.
    assert report.beats_buy_and_hold() is True
    verdict = evaluate_gate(report, None)
    assert verdict.label in {"INCOMPLETE", "REJECT"}  # the audit half is missing


def test_audit_scores_every_configuration_on_every_block() -> None:
    basket = _basket(600)
    grid = XsMomGrid(lookback_bars=(10, 20), top_n=(1, 2), rebalance_every=(5,))
    audit = run_xsmom_audit(basket, XsMomRequest(grid=grid, pbo_blocks=4))
    assert audit.configuration_count == 4
    assert audit.blocks == 4
    assert len(audit.block_returns) == 4


def test_xsmom_audit_deflates_by_every_trial_in_the_ledger() -> None:
    """Audit B5: the basket DSR used to count only the current grid."""
    from nautilus_lab.application.trial_ledger import InMemoryTrialLedger

    basket = _basket()
    grid = XsMomGrid(lookback_bars=(10, 20), top_n=(1, 2), rebalance_every=(5,))
    ledger = InMemoryTrialLedger()
    ledger.record("basket", (f"earlier|{index}" for index in range(40)))
    audit = run_xsmom_audit(
        basket, XsMomRequest(grid=grid, pbo_blocks=4), trial_ledger=ledger, dataset="basket"
    )
    assert audit.deflated_sharpe.n_trials_total == 44
