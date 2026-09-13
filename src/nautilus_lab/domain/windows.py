from __future__ import annotations

from collections import deque
from decimal import Decimal


class RollingWindow:
    """Fixed-length queue of closed-bar values. No look-ahead."""

    def __init__(self, maxlen: int) -> None:
        if maxlen < 1:
            raise ValueError("maxlen must be >= 1")
        self._values: deque[Decimal] = deque(maxlen=maxlen)

    def push(self, value: Decimal) -> None:
        self._values.append(value)

    def __len__(self) -> int:
        return len(self._values)

    @property
    def full(self) -> bool:
        limit = self._values.maxlen
        return limit is not None and len(self._values) == limit

    def values(self) -> tuple[Decimal, ...]:
        return tuple(self._values)

    def prior(self) -> tuple[Decimal, ...]:
        """All values except the most recent (the just-closed bar)."""
        if len(self._values) < 2:
            return ()
        return tuple(list(self._values)[:-1])
