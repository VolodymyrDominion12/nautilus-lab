from __future__ import annotations

from dataclasses import dataclass

from nautilus_lab.domain.errors import InvalidRiskError


@dataclass(slots=True)
class StopCooldown:
    """Blocks new entries for N closed bars after an overlay stop fired.

    Only entries are gated: an exit (or the exit half of a reversal) is never held back.
    `bars = 0` is disabled, so a run without the setting behaves as it did before it existed.
    """

    bars: int = 0
    _left: int = 0

    def __post_init__(self) -> None:
        if self.bars < 0:
            raise InvalidRiskError("stop_cooldown_bars must be >= 0")

    @property
    def active(self) -> bool:
        return self._left > 0

    @property
    def remaining(self) -> int:
        return self._left

    def trip(self) -> None:
        """A stop fired on this bar: the next `bars` bars may not open a position."""
        self._left = self.bars

    def tick(self) -> None:
        """One closed bar has been decided; call after the entry gate, not before."""
        if self._left > 0:
            self._left -= 1
