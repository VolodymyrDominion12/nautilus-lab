from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from nautilus_lab.domain.regime import RegimeParams, RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode


@dataclass(frozen=True, slots=True)
class BacktestRequest:
    mode: TradingMode
    instrument_id: str
    bar_count: int
    starting_equity: Decimal
    risk: RiskLimits
    robot: RobotName = RobotName.REGIME
    fast_ema: int = 10
    slow_ema: int = 20
    regime: RegimeParams = field(default_factory=RegimeParams)
    seed: int = 42


@dataclass(frozen=True, slots=True)
class BacktestReport:
    fills: int
    positions: int
    ending_balance: Decimal | None
    notes: str


class ResearchBacktestPort(Protocol):
    def run(self, request: BacktestRequest) -> BacktestReport: ...
