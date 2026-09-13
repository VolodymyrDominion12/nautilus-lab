from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.fees import FeeSchedule
from nautilus_lab.domain.metrics import BacktestMetrics
from nautilus_lab.domain.pairs.params import PairsParams
from nautilus_lab.domain.regime import RegimeParams, RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.domain.walk_forward import WalkForwardWindow


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
    pairs: PairsParams = field(default_factory=PairsParams)
    seed: int = 42
    source: BarOrigin = BarOrigin.SYNTHETIC
    bar_type: str = "ETH/USDT.SIM-1-MINUTE-LAST-EXTERNAL"
    bar_types: tuple[str, ...] = ()
    instrument_ids: tuple[str, ...] = ()
    start: datetime | None = None
    end: datetime | None = None
    fee_schedule: FeeSchedule = field(default_factory=FeeSchedule.binance_spot_vip0)
    embargo_bars: int = 0
    stress_slice: str | None = None
    use_bar_vpin: bool = False
    vpin_bucket_volume: Decimal = Decimal("1000")
    vpin_toxic_threshold: Decimal = Decimal("0.7")


@dataclass(frozen=True, slots=True)
class BacktestReport:
    fills: int
    positions: int
    ending_balance: Decimal | None
    notes: str
    metrics: BacktestMetrics | None = None


@dataclass(frozen=True, slots=True)
class IngestRequest:
    mode: TradingMode
    symbol: str
    interval: str
    instrument_id: str
    bar_type: str
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class IngestReport:
    bars_written: int
    first_ts: datetime
    last_ts: datetime
    catalog_path: str
    source: str
    symbol: str = ""


@dataclass(frozen=True, slots=True)
class WalkForwardRequest:
    backtest: BacktestRequest
    window: WalkForwardWindow | None = None
    in_sample_fraction: Decimal = Decimal("0.7")
    embargo_bars: int = 0


@dataclass(frozen=True, slots=True)
class SelectedParams:
    fast_ema: int
    slow_ema: int
    donchian_period: int
    bb_period: int
    bb_k: Decimal
    enter_trend_er: Decimal
    exit_trend_er: Decimal
    z_entry: Decimal = Decimal("2")
    z_exit: Decimal = Decimal("0.5")

    def label(self) -> str:
        return (
            f"fast_ema={self.fast_ema} slow_ema={self.slow_ema} "
            f"donchian={self.donchian_period} bb_k={self.bb_k} "
            f"z_entry={self.z_entry}"
        )


@dataclass(frozen=True, slots=True)
class WalkForwardReport:
    selected: SelectedParams
    candidates_tried: int
    in_sample: BacktestReport
    out_of_sample: BacktestReport
    window: WalkForwardWindow
    notes: str


class ResearchBacktestPort(Protocol):
    def run(self, request: BacktestRequest, bars: list[OhlcvBar]) -> BacktestReport: ...

    def run_spread(
        self,
        request: BacktestRequest,
        bars_by_instrument: dict[str, list[OhlcvBar]],
    ) -> BacktestReport: ...


class BarFeed(Protocol):
    def load(self, request: BacktestRequest) -> list[OhlcvBar]: ...

    def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]: ...


def selected_from_request(request: BacktestRequest) -> SelectedParams:
    return SelectedParams(
        fast_ema=request.fast_ema,
        slow_ema=request.slow_ema,
        donchian_period=request.regime.donchian_period,
        bb_period=request.regime.bb_period,
        bb_k=request.regime.bb_k,
        enter_trend_er=request.regime.enter_trend_er,
        exit_trend_er=request.regime.exit_trend_er,
        z_entry=request.pairs.z_entry,
        z_exit=request.pairs.z_exit,
    )


def apply_selected(request: BacktestRequest, params: SelectedParams) -> BacktestRequest:
    return replace(
        request,
        fast_ema=params.fast_ema,
        slow_ema=params.slow_ema,
        regime=replace(
            request.regime,
            donchian_period=params.donchian_period,
            bb_period=params.bb_period,
            bb_k=params.bb_k,
            enter_trend_er=params.enter_trend_er,
            exit_trend_er=params.exit_trend_er,
        ),
        pairs=replace(
            request.pairs,
            z_entry=params.z_entry,
            z_exit=params.z_exit,
        ),
    )
