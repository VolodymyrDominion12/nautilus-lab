from __future__ import annotations

from typing import Protocol


class KillSwitch(Protocol):
    """Flatten and cancel working orders when risk or connectivity breaks."""

    def trigger(self, reason: str) -> None: ...

    def is_active(self) -> bool: ...


class NoOpKillSwitch:
    """Research stub: records trigger but does not send orders."""

    def __init__(self) -> None:
        self._active = False
        self.last_reason: str | None = None

    def trigger(self, reason: str) -> None:
        self._active = True
        self.last_reason = reason

    def is_active(self) -> bool:
        return self._active
