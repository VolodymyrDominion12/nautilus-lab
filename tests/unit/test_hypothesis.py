from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import InvalidHypothesisError
from nautilus_lab.domain.formulaic_alphas import FEATURE_NAMES, MIN_HISTORY, FormulaicAlphaEngine
from nautilus_lab.domain.hypothesis import (
    ALLOWED_FORMULA_FUNCTIONS,
    MAX_HORIZON_BARS,
    parse_hypotheses,
    rejected_names,
    unknown_identifiers,
)

_VALID: dict[str, object] = {
    "name": "volume-climax reversal",
    "formula": "-reversal_3 * zscore(volume_ratio)",
    "mechanism": "a volume spike with no follow-through means the aggressor is spent",
    "horizon_bars": 5,
    "expected_sign": -1,
    "kill_condition": "out-of-sample IC < 0 in two adjacent folds",
}


def _bars(count: int = 40) -> list[OhlcvBar]:
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[OhlcvBar] = []
    price = Decimal("100")
    for index in range(count):
        price += Decimal("1")
        bars.append(
            OhlcvBar(
                instrument_id="ETH/USDT.SIM",
                ts_utc=origin + timedelta(hours=index),
                open=price - Decimal("1"),
                high=price + Decimal("1"),
                low=price - Decimal("2"),
                close=price,
                volume=Decimal("100") + Decimal(index),
            )
        )
    return bars


def test_feature_names_match_engine_order() -> None:
    """The public contract and the engine output must not drift apart."""
    bars = _bars(40)
    engine = FormulaicAlphaEngine(history=MIN_HISTORY)
    features: tuple[Decimal, ...] | None = None
    for bar in bars:
        features = engine.update(bar)
    assert features is not None
    assert len(FEATURE_NAMES) == len(features) == 12
    assert len(set(FEATURE_NAMES)) == 12

    closes = [item.close for item in bars]
    assert features[FEATURE_NAMES.index("ret")] == (closes[-1] - closes[-2]) / closes[-2]
    assert features[FEATURE_NAMES.index("momentum_10")] == (closes[-1] - closes[-11]) / closes[-11]
    assert features[FEATURE_NAMES.index("reversal_3")] == -((closes[-1] - closes[-4]) / closes[-4])


def test_parse_hypotheses_accepts_array() -> None:
    parsed = parse_hypotheses([dict(_VALID)])
    assert len(parsed) == 1
    assert parsed[0].name == "volume-climax reversal"
    assert parsed[0].expected_sign == -1
    assert parsed[0].horizon_bars == 5


def test_parse_hypotheses_accepts_wrapped_object() -> None:
    parsed = parse_hypotheses({"hypotheses": [dict(_VALID)]})
    assert len(parsed) == 1


def test_parse_hypotheses_rejects_empty_payload() -> None:
    with pytest.raises(InvalidHypothesisError, match="no hypotheses"):
        parse_hypotheses([])


def test_parse_hypotheses_rejects_wrong_shape() -> None:
    with pytest.raises(InvalidHypothesisError, match="array or object"):
        parse_hypotheses("not json")
    with pytest.raises(InvalidHypothesisError, match="hypotheses"):
        parse_hypotheses({"rows": []})


def test_parse_hypotheses_rejects_missing_field() -> None:
    broken = dict(_VALID)
    del broken["kill_condition"]
    with pytest.raises(InvalidHypothesisError, match="kill_condition"):
        parse_hypotheses([broken])


def test_parse_hypotheses_rejects_blank_text() -> None:
    broken = dict(_VALID, mechanism="   ")
    with pytest.raises(InvalidHypothesisError, match="mechanism"):
        parse_hypotheses([broken])


@pytest.mark.parametrize(
    ("given", "expected"),
    [(1, 1), (-1, -1), ("+1", 1), ("-1", -1), ("long", 1), ("SHORT", -1)],
)
def test_parse_hypotheses_normalises_sign(given: object, expected: int) -> None:
    assert parse_hypotheses([dict(_VALID, expected_sign=given)])[0].expected_sign == expected


@pytest.mark.parametrize("given", [0, 2, "sideways", None, True])
def test_parse_hypotheses_rejects_bad_sign(given: object) -> None:
    with pytest.raises(InvalidHypothesisError, match="expected_sign"):
        parse_hypotheses([dict(_VALID, expected_sign=given)])


@pytest.mark.parametrize("given", [0, -5, MAX_HORIZON_BARS + 1, "5", 5.0])
def test_parse_hypotheses_rejects_bad_horizon(given: object) -> None:
    with pytest.raises(InvalidHypothesisError, match="horizon_bars"):
        parse_hypotheses([dict(_VALID, horizon_bars=given)])


def test_unknown_identifiers_flags_hallucinated_feature() -> None:
    formula = "-reversal_3 * zscore(order_flow_toxicity)"
    assert unknown_identifiers(formula) == ("order_flow_toxicity",)
    assert unknown_identifiers("mean(vol_10) + abs(ret)") == ()


def test_allowed_functions_are_not_flagged() -> None:
    formula = " + ".join(f"{name}(ret)" for name in sorted(ALLOWED_FORMULA_FUNCTIONS))
    assert unknown_identifiers(formula) == ()


def test_hypothesis_reports_unknown_identifiers() -> None:
    parsed = parse_hypotheses([dict(_VALID, formula="mean(made_up_feature)")])
    assert parsed[0].unknown_identifiers() == ("made_up_feature",)
    assert parsed[0].as_dict()["unknown_identifiers"] == ["made_up_feature"]


def test_rejected_names_lists_flagged_hypotheses() -> None:
    good = parse_hypotheses([dict(_VALID)])[0]
    bad = parse_hypotheses([dict(_VALID, name="bad one", formula="mean(ghost_feature)")])[0]
    assert rejected_names([good, bad]) == ("bad one",)
    assert set(good.as_dict()) >= {
        "name",
        "formula",
        "mechanism",
        "horizon_bars",
        "expected_sign",
        "kill_condition",
    }
