"""How far each condition was from its threshold, bar by bar (docs/30, stage 6).

Every robot now logs a *margin* next to its threshold: `margin_pct` (VPIN, meta-label,
Bollinger z, LGBM probability), `z_margin_pct` (pairs), `apy_margin_pct` (funding),
`er_margin_pct` (regime ER hysteresis), or `dist_to_breakout_pct` (Donchian, in percent of
price). Collected per component, they answer "how many more signals would a threshold
X% softer have produced" without re-running a backtest — which is the question behind
"the devil is in the details". Softening is a hypothesis to test on fresh data, not a fix:
the answer is only as good as the next out-of-sample window.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

#: Margin fields in the order they are preferred when a step carries more than one.
MARGIN_KEYS: tuple[str, ...] = (
    "margin_pct",
    "z_margin_pct",
    "apy_margin_pct",
    "er_margin_pct",
    "dist_to_breakout_pct",
)
#: Values kept per component; a 4-fold 1h run has ~7k bars, well under it.
MAX_VALUES = 50_000


def margin_distribution(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per `<component>.<key>`: every margin value and how many of them passed (>= 0)."""
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("kind", "bar_decision") != "bar_decision":
            continue
        for item in row.get("steps") or []:
            if not isinstance(item, Mapping):
                continue
            if item.get("stage") not in ("regime", "filter", "strategy"):
                continue
            values = item.get("values")
            if not isinstance(values, Mapping):
                continue
            for key in MARGIN_KEYS:
                raw = values.get(key)
                if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
                    continue
                try:
                    number = float(raw)
                except ValueError:
                    continue
                name = f"{item.get('component')}.{key}"
                bucket = out.setdefault(
                    name,
                    {
                        "component": item.get("component"),
                        "key": key,
                        "unit": "% of price" if key == "dist_to_breakout_pct" else "% of threshold",
                        "values": [],
                        "passed": 0,
                    },
                )
                if len(bucket["values"]) < MAX_VALUES:
                    bucket["values"].append(round(number, 3))
                if number >= 0:
                    bucket["passed"] += 1
                break
    for bucket in out.values():
        bucket["total"] = len(bucket["values"])
    return out


def extra_passes(values: Iterable[float], softer_by_pct: float) -> int:
    """How many readings a threshold `softer_by_pct` looser would have let through."""
    return sum(1 for value in values if -softer_by_pct <= value < 0)
