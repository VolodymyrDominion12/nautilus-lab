from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from nautilus_lab.application.alpha.panel import Panel
from nautilus_lab.application.alpha.validate import (
    Criteria,
    Hypothesis,
    Leg,
    Preregistration,
    already_run,
    composite_scores,
    read_preregistration,
    run_validation,
    write_preregistration,
)
from nautilus_lab.domain.data_zone import TimeWindow, ZonePolicy

SYMBOLS = tuple(f"C{i}USDT" for i in range(7))


def _prereg(**overrides: object) -> Preregistration:
    kwargs: dict[str, object] = {
        "hypotheses": (
            Hypothesis("H1", (Leg("mom_7d", 1),), 24, "momentum"),
            Hypothesis("H2", (Leg("mom_7d", 1), Leg("rev_1d", -1)), 24, "combo"),
        ),
        "symbols": SYMBOLS,
        "panel_label": "perp_1h",
        "cost_bps": 7.0,
        "criteria": Criteria(),
        "exploration_report": "reports/x.md",
        "created_at": "2026-10-20T09:00:00+00:00",
    }
    kwargs.update(overrides)
    return Preregistration(**kwargs)  # type: ignore[arg-type]


def _policy(fraction: str = "0") -> ZonePolicy:
    return ZonePolicy(
        exploration=(
            TimeWindow(datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 4, 1, tzinfo=UTC)),
        ),
        validation=(
            TimeWindow(datetime(2020, 4, 1, tzinfo=UTC), datetime(2021, 1, 1, tzinfo=UTC)),
        ),
        holdout=(),
        holdout_symbol_fraction=Decimal(fraction),
    )


def _panel() -> Panel:
    rng = np.random.default_rng(9)
    bars = 24 * 366
    close = 100.0 * np.cumprod(1.0 + rng.normal(0, 0.01, (bars, len(SYMBOLS))), axis=0)
    ts = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp() // 60) + 60 * np.arange(bars)
    fields = {"close": close, "high": close, "low": close, "volume": np.ones_like(close)}
    return Panel(ts.astype(np.int64), SYMBOLS, fields, 60)


def test_registration_round_trips_and_detects_edits(tmp_path: Path) -> None:
    prereg = _prereg()
    path = write_preregistration(prereg, tmp_path)
    assert prereg.digest in path.name
    assert read_preregistration(path).digest == prereg.digest
    data = json.loads(path.read_text(encoding="utf-8"))
    data["hypotheses"][0]["horizon"] = 72  # quietly "improve" it after the fact
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="edited after registration"):
        read_preregistration(path)


def test_unknown_signal_or_direction_fails_at_registration() -> None:
    with pytest.raises(KeyError):
        Leg("no_such_signal", 1)
    with pytest.raises(ValueError, match="direction"):
        Leg("mom_7d", 0)


def test_one_look_per_registration(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    prereg = _prereg()
    run = run_validation(_panel(), prereg, policy=_policy(), log=log)
    assert len(run.outcomes) == 2
    assert already_run(log, prereg.digest)
    # random walks: nothing should pass, and the threshold is split over 2 hypotheses
    assert not any(o.passed for o in run.outcomes)
    assert run.outcomes[0].p_threshold == pytest.approx(0.025)
    with pytest.raises(PermissionError, match="already run"):
        run_validation(_panel(), prereg, policy=_policy(), log=log)


def test_holdout_coins_cannot_be_validated(tmp_path: Path) -> None:
    policy = _policy("0.5")
    assert policy.holdout_symbols(SYMBOLS)
    with pytest.raises(PermissionError, match="holdout"):
        run_validation(_panel(), _prereg(), policy=policy, log=tmp_path / "log.jsonl")


def test_composite_needs_every_leg() -> None:
    a = np.array([[0.5, -0.5, np.nan]])
    b = np.array([[0.1, 0.3, 0.2]])
    out = composite_scores([a, b])
    np.testing.assert_allclose(out[0, :2], [0.3, -0.1])
    assert np.isnan(out[0, 2])


def test_the_drafted_spec_is_registrable() -> None:
    spec_path = Path(__file__).parents[2] / "research/alpha/validation-spec-2026-10-20.json"
    if not spec_path.exists():
        pytest.skip("draft spec not present")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    for h in spec["hypotheses"]:
        Hypothesis(
            h["id"],
            tuple(Leg(leg["signal"], leg["direction"]) for leg in h["legs"]),
            h["horizon"],
            h["rationale"],
        )
    Criteria(**spec["criteria"])
