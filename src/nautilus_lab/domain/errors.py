"""Domain errors. Fail closed: callers must not swallow these around orders."""

from __future__ import annotations


class DomainError(ValueError):
    """Base class for domain invariant violations."""


class InvalidBarError(DomainError):
    """OHLCV bar failed point-in-time validation."""


class InvalidWindowError(DomainError):
    """Walk-forward window overlaps, is empty, or is not UTC."""


class CatalogEmptyError(DomainError):
    """Parquet catalog has no bars for the requested series."""


class InvalidRiskError(DomainError):
    """Risk parameter is outside the allowed range."""


class RobotNotWiredError(DomainError):
    """Robot has no execution adapter yet. Fail closed instead of running another robot."""


class ModelArtifactMissingError(DomainError):
    """A robot that needs an offline-trained booster was started without a model file."""


class InvalidHypothesisError(DomainError):
    """An alpha proposal is malformed or breaks the hypothesis contract.

    Raised only in the offline research loop: a bad proposal must never reach a
    strategy, and never a hot path.
    """


class JournalFormatError(DomainError):
    """The research journal lost its marker pair, so a new row has no defined place."""


class RateLimitedError(DomainError):
    """Exchange rate limit was hit and the retry budget is exhausted.

    Fail closed rather than returning a short or empty series: a silently truncated
    ingest produces a catalog that looks complete and is not.
    """


class MarketDataError(DomainError):
    """A public market-data endpoint answered with a non-retryable status.

    Raised for HTTP 4xx other than 429/418 (e.g. an unknown symbol, or a history
    window the exchange does not serve) so the caller sees the real cause instead
    of an empty list.
    """


class LiveTradingDisabledError(RuntimeError):
    """Live orders are blocked until the user explicitly enables a live adapter."""


class PaperTradingNotReadyError(RuntimeError):
    """Paper node is not wired; research backtests are the supported path."""
