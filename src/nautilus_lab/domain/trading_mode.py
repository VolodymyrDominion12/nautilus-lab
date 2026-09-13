from __future__ import annotations

from enum import StrEnum


class TradingMode(StrEnum):
    """Execution modes. Never mix simulated and real money in one process."""

    RESEARCH = "research"
    PAPER = "paper"
    LIVE = "live"
