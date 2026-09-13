"""Domain errors. Fail closed: callers must not swallow these around orders."""

from __future__ import annotations


class DomainError(ValueError):
    """Base class for domain invariant violations."""


class InvalidBarError(DomainError):
    """OHLCV bar failed point-in-time validation."""


class InvalidRiskError(DomainError):
    """Risk parameter is outside the allowed range."""


class LiveTradingDisabledError(RuntimeError):
    """Live orders are blocked until the user explicitly enables a live adapter."""


class PaperTradingNotReadyError(RuntimeError):
    """Paper node is not wired; research backtests are the supported path."""
