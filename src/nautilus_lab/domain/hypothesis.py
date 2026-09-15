"""Hypothesis contract for the offline alpha-generation loop.

An LRM/LLM may *propose* an alpha, but a proposal only enters the research pipeline
after it satisfies the invariants in this module. Nothing here touches the network,
Nautilus or `.env`: this is pure validation, so it can be unit-tested in milliseconds.

See docs/14-llm-model-u-torhivli.md and research/README.md for the workflow this
contract belongs to.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass

from nautilus_lab.domain.errors import InvalidHypothesisError
from nautilus_lab.domain.formulaic_alphas import FEATURE_NAMES

#: Longest horizon a proposal may claim, in bars. A "prediction" five days out on 1h
#: bars is not a research hypothesis, it is a macro bet; reject it at the door.
MAX_HORIZON_BARS = 240

#: Formula primitives allowed on top of FEATURE_NAMES. Kept deliberately small and
#: documented: anything outside this set is reported by `unknown_identifiers()` so a
#: hallucinated feature cannot slip into the pipeline unnoticed.
ALLOWED_FORMULA_FUNCTIONS: frozenset[str] = frozenset(
    {
        "abs",
        "clip",
        "corr",
        "delta",
        "delay",
        "log",
        "max",
        "mean",
        "min",
        "pow",
        "rank",
        "sign",
        "sqrt",
        "std",
        "sum",
        "ts_max",
        "ts_mean",
        "ts_min",
        "ts_std",
        "zscore",
    }
)

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_REQUIRED_FIELDS: tuple[str, ...] = (
    "name",
    "formula",
    "mechanism",
    "horizon_bars",
    "expected_sign",
    "kill_condition",
)

_SIGN_ALIASES: dict[str, int] = {
    "+1": 1,
    "-1": -1,
    "1": 1,
    "long": 1,
    "short": -1,
    "up": 1,
    "down": -1,
    "positive": 1,
    "negative": -1,
}


@dataclass(frozen=True, slots=True)
class Hypothesis:
    """A reviewable alpha proposal. Never a trade instruction, never sized."""

    name: str
    formula: str
    mechanism: str
    horizon_bars: int
    expected_sign: int
    kill_condition: str

    def unknown_identifiers(self) -> tuple[str, ...]:
        """Identifier-like tokens in `formula` that are neither features nor functions."""
        return unknown_identifiers(self.formula)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "formula": self.formula,
            "mechanism": self.mechanism,
            "horizon_bars": self.horizon_bars,
            "expected_sign": self.expected_sign,
            "kill_condition": self.kill_condition,
            "unknown_identifiers": list(self.unknown_identifiers()),
        }


def unknown_identifiers(
    formula: str,
    *,
    known: Collection[str] = FEATURE_NAMES,
    functions: Collection[str] = ALLOWED_FORMULA_FUNCTIONS,
) -> tuple[str, ...]:
    """Tokens in `formula` outside the allowed feature/function vocabulary.

    This is a lint, not a gate: the caller reports these to the human reviewer, who
    decides whether the proposal invented a feature that does not exist.
    """
    tokens = set(_IDENTIFIER_RE.findall(formula))
    return tuple(sorted(item for item in tokens if item not in known and item not in functions))


def parse_hypotheses(payload: object) -> tuple[Hypothesis, ...]:
    """Validate a decoded JSON payload into hypotheses. Fail closed on anything else.

    Accepts either a JSON array or an object with a `hypotheses` array, because both
    shapes are common LLM outputs; every other deviation raises.
    """
    rows = _as_rows(payload)
    if not rows:
        raise InvalidHypothesisError("payload contains no hypotheses")
    return tuple(_parse_one(row, index=index) for index, row in enumerate(rows, start=1))


def _as_rows(payload: object) -> Sequence[object]:
    if isinstance(payload, list):
        return list(payload)
    if isinstance(payload, Mapping):
        candidate = payload.get("hypotheses")
        if isinstance(candidate, list):
            return list(candidate)
        raise InvalidHypothesisError("object payload must carry a 'hypotheses' array")
    raise InvalidHypothesisError(f"payload must be a JSON array or object, got {type(payload)}")


def _parse_one(row: object, *, index: int) -> Hypothesis:
    if not isinstance(row, Mapping):
        raise InvalidHypothesisError(f"hypothesis #{index} must be an object")
    missing = [field for field in _REQUIRED_FIELDS if field not in row]
    if missing:
        raise InvalidHypothesisError(f"hypothesis #{index} is missing fields: {', '.join(missing)}")

    name = _require_text(row["name"], field="name", index=index)
    formula = _require_text(row["formula"], field="formula", index=index)
    mechanism = _require_text(row["mechanism"], field="mechanism", index=index)
    kill_condition = _require_text(row["kill_condition"], field="kill_condition", index=index)
    horizon = _require_horizon(row["horizon_bars"], index=index)
    sign = _require_sign(row["expected_sign"], index=index)

    return Hypothesis(
        name=name,
        formula=formula,
        mechanism=mechanism,
        horizon_bars=horizon,
        expected_sign=sign,
        kill_condition=kill_condition,
    )


def _require_text(value: object, *, field: str, index: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidHypothesisError(f"hypothesis #{index}: {field} must be a non-empty string")
    return value.strip()


def _require_horizon(value: object, *, index: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidHypothesisError(f"hypothesis #{index}: horizon_bars must be an integer")
    if not 1 <= value <= MAX_HORIZON_BARS:
        raise InvalidHypothesisError(
            f"hypothesis #{index}: horizon_bars must be within 1..{MAX_HORIZON_BARS}, got {value}"
        )
    return value


def _require_sign(value: object, *, index: int) -> int:
    if isinstance(value, bool):
        raise InvalidHypothesisError(f"hypothesis #{index}: expected_sign must be +1 or -1")
    if isinstance(value, int) and value in (1, -1):
        return value
    if isinstance(value, str):
        alias = _SIGN_ALIASES.get(value.strip().lower())
        if alias is not None:
            return alias
    raise InvalidHypothesisError(
        f"hypothesis #{index}: expected_sign must be +1/-1 (or long/short), got {value!r}"
    )


def rejected_names(
    hypotheses: Iterable[Hypothesis], *, known: Collection[str] = FEATURE_NAMES
) -> tuple[str, ...]:
    """Names of hypotheses referring to unknown identifiers — review before any run."""
    return tuple(item.name for item in hypotheses if unknown_identifiers(item.formula, known=known))
