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


def interval_from_bar_type(bar_type: str) -> str:
    """Inverse of `nautilus_bar_type` for any interval in `NAUTILUS_BAR_SPEC`.

    The spec is matched as a whole `-SPEC-` segment, never as a bare substring:
    `"15-MINUTE"` contains `"5-MINUTE"`, so a prefix test would silently read a
    quarter-hour series as five-minute. Longest spec first keeps that ordering
    explicit instead of relying on the delimiter alone.
    """
    for interval, spec in sorted(NAUTILUS_BAR_SPEC.items(), key=lambda item: -len(item[1])):
        if f"-{spec}-" in bar_type:
            return interval
    allowed = ", ".join(NAUTILUS_BAR_SPEC)
    raise ValueError(
        f"cannot read a bar interval out of {bar_type!r}; expected a spec from: {allowed}"
    )
