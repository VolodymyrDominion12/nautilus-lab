from __future__ import annotations

from collections.abc import Mapping

NAUTILUS_BAR_SPEC: Mapping[str, str] = {
    "1m": "1-MINUTE",
    "5m": "5-MINUTE",
    "15m": "15-MINUTE",
    "1h": "1-HOUR",
    "4h": "4-HOUR",
    "1d": "1-DAY",
}


def nautilus_bar_type(instrument_id: str, interval: str) -> str:
    spec = NAUTILUS_BAR_SPEC.get(interval)
    if spec is None:
        allowed = ", ".join(NAUTILUS_BAR_SPEC)
        raise ValueError(f"unsupported bar interval {interval!r}; use one of: {allowed}")
    return f"{instrument_id}-{spec}-LAST-EXTERNAL"
