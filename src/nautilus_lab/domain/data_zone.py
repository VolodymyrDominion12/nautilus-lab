"""Data zones: which slice of history a research step is allowed to look at.

Every look at data is a selection. The research pipeline therefore splits the history
into three zones (strategy-research-pipeline-plan, 2026-10-05):

* **exploration**: screening, grids, LLM ideas. It can be looked at as often as needed.
* **validation**: preregistered walk-forward tests only, never a screen.
* **holdout**: one disclosure, by a person, at the end.

The split runs along two axes:

* **Time.** Calendar windows, half-open `[start, end)` in UTC.
* **Symbols.** A fixed share of coins is held out for good. Such a coin is in the
  holdout zone on every date, so a signal found on the research coins can be checked
  on coins it never saw.

The symbol split is a hash of the base symbol and a salt. That makes it stable: adding
a coin to the universe never moves another coin between zones, and a rank-based split
would. BTC and ETH are market anchors (the market return, beta, the benchmark). They
are kept on the research side, and that cost was paid long ago: every robot in this
lab has already been run on them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from nautilus_lab.domain.errors import InvalidWindowError

DEFAULT_SALT = "nautilus-lab/data-zone/v1"
#: Never held out: the market return and every benchmark are built from them.
MARKET_ANCHORS = frozenset({"BTCUSDT", "ETHUSDT"})


class DataZone(StrEnum):
    EXPLORATION = "exploration"
    VALIDATION = "validation"
    HOLDOUT = "holdout"


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """Half-open UTC interval `[start, end)`."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise InvalidWindowError("zone windows must be timezone-aware UTC")
        if self.start >= self.end:
            raise InvalidWindowError("zone window start must be before end")

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end

    def overlaps(self, other: TimeWindow) -> bool:
        return self.start < other.end and other.start < self.end


def base_symbol(symbol: str) -> str:
    """`BTCUSDT-PERP.SIM` and `btcusdt` both become `BTCUSDT`."""
    return symbol.upper().split(".", 1)[0].removesuffix("-PERP")


@dataclass(frozen=True, slots=True)
class ZonePolicy:
    exploration: tuple[TimeWindow, ...]
    validation: tuple[TimeWindow, ...]
    holdout: tuple[TimeWindow, ...]
    holdout_symbol_fraction: Decimal = Decimal(1) / Decimal(3)
    salt: str = DEFAULT_SALT
    anchors: frozenset[str] = field(default=MARKET_ANCHORS)

    def __post_init__(self) -> None:
        if not Decimal(0) <= self.holdout_symbol_fraction < Decimal(1):
            raise ValueError("holdout_symbol_fraction must be in [0, 1)")
        windows = [
            *((DataZone.EXPLORATION, w) for w in self.exploration),
            *((DataZone.VALIDATION, w) for w in self.validation),
            *((DataZone.HOLDOUT, w) for w in self.holdout),
        ]
        for index, (zone_a, left) in enumerate(windows):
            for zone_b, right in windows[index + 1 :]:
                if left.overlaps(right):
                    raise InvalidWindowError(
                        f"zone windows overlap: {zone_a} {left.start:%Y-%m-%d}.."
                        f"{left.end:%Y-%m-%d} and {zone_b} {right.start:%Y-%m-%d}.."
                        f"{right.end:%Y-%m-%d}"
                    )

    def symbol_is_holdout(self, symbol: str) -> bool:
        base = base_symbol(symbol)
        if base in self.anchors:
            return False
        digest = hashlib.sha256(f"{self.salt}:{base}".encode()).digest()
        bucket = Decimal(int.from_bytes(digest[:8], "big")) / Decimal(2**64)
        return bucket < self.holdout_symbol_fraction

    def research_symbols(self, symbols: Iterable[str]) -> tuple[str, ...]:
        """Symbols that exploration and validation may use, input order kept."""
        return tuple(s for s in symbols if not self.symbol_is_holdout(s))

    def holdout_symbols(self, symbols: Iterable[str]) -> tuple[str, ...]:
        return tuple(s for s in symbols if self.symbol_is_holdout(s))

    def windows(self, zone: DataZone) -> tuple[TimeWindow, ...]:
        if zone is DataZone.EXPLORATION:
            return self.exploration
        if zone is DataZone.VALIDATION:
            return self.validation
        return self.holdout

    def time_zone(self, moment: datetime) -> DataZone | None:
        """Zone of a timestamp by calendar alone; None outside every window."""
        for zone in DataZone:
            if any(window.contains(moment) for window in self.windows(zone)):
                return zone
        return None

    def zone(self, moment: datetime, symbol: str) -> DataZone | None:
        """Zone of one observation. A held-out coin is holdout on every date."""
        if self.symbol_is_holdout(symbol):
            return DataZone.HOLDOUT
        return self.time_zone(moment)


def _utc(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


#: The split agreed on 2026-10-05. After 2026-10-01 nothing is assigned yet:
#: new data is not anyone's zone until a person decides which one it is.
DEFAULT_ZONE_POLICY = ZonePolicy(
    exploration=(
        TimeWindow(_utc(2019), _utc(2022)),
        TimeWindow(_utc(2023), _utc(2024)),
    ),
    validation=(TimeWindow(_utc(2024), _utc(2026, 7)),),
    holdout=(
        TimeWindow(_utc(2022), _utc(2023)),
        TimeWindow(_utc(2026, 7), _utc(2026, 10)),
    ),
)
