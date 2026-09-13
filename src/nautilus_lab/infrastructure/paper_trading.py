from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from nautilus_lab.domain.signals import Signal, SpreadSignal


@dataclass(frozen=True, slots=True)
class PaperOrderLog:
    ts_utc: datetime
    description: str
    side: str
    instrument_id: str
    qty: Decimal


class PaperTradingLogger:
    """Paper mode: log hypothetical orders, never submit to an exchange."""

    def __init__(self) -> None:
        self.orders: list[PaperOrderLog] = []

    def log_signal(self, signal: Signal, qty: Decimal) -> None:
        self.orders.append(
            PaperOrderLog(
                ts_utc=signal.bar_ts_utc,
                description=signal.reason,
                side=signal.side.value,
                instrument_id=signal.instrument_id,
                qty=qty,
            )
        )

    def log_spread(self, signal: SpreadSignal) -> None:
        self.orders.append(
            PaperOrderLog(
                ts_utc=signal.bar_ts_utc,
                description=signal.reason,
                side="spread",
                instrument_id=f"{signal.leg_a.instrument_id}|{signal.leg_b.instrument_id}",
                qty=Decimal("0"),
            )
        )
