from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class StressSliceName(StrEnum):
    COVID_2020 = "covid2020"
    LUNA_FTX_2022 = "ftx2022"
    ETF_2024 = "etf2024"


@dataclass(frozen=True, slots=True)
class StressSlice:
    name: StressSliceName
    start: datetime
    end: datetime
    description: str


STRESS_SLICES: dict[StressSliceName, StressSlice] = {
    StressSliceName.COVID_2020: StressSlice(
        name=StressSliceName.COVID_2020,
        start=datetime(2020, 2, 1, tzinfo=UTC),
        end=datetime(2020, 5, 1, tzinfo=UTC),
        description="COVID crash and recovery window",
    ),
    StressSliceName.LUNA_FTX_2022: StressSlice(
        name=StressSliceName.LUNA_FTX_2022,
        start=datetime(2022, 5, 1, tzinfo=UTC),
        end=datetime(2022, 12, 1, tzinfo=UTC),
        description="LUNA/FTX contagion period",
    ),
    StressSliceName.ETF_2024: StressSlice(
        name=StressSliceName.ETF_2024,
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 6, 1, tzinfo=UTC),
        description="Bitcoin ETF approval rally window",
    ),
}


def resolve_stress_slice(name: str) -> StressSlice:
    try:
        key = StressSliceName(name.lower())
    except ValueError:
        allowed = ", ".join(item.value for item in StressSliceName)
        raise ValueError(f"unknown stress slice {name!r}; use one of: {allowed}") from None
    return STRESS_SLICES[key]
