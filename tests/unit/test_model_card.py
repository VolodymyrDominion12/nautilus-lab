"""Model cards stop leaking ML models from reaching an OOS number (audit A1/A2/A3/B7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    WalkForwardRequest,
)
from nautilus_lab.application.model_guard import require_clean_model
from nautilus_lab.application.run_walk_forward import RunWalkForward
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import ModelArtifactMissingError
from nautilus_lab.domain.model_card import ModelCard, ModelLeakError, card_problems
from nautilus_lab.domain.order_book import OrderBookSnapshot
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.ticks import AggTrade
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.model_card_store import (
    JsonModelCardSource,
    card_path,
    file_sha256,
    write_model_card,
)
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_ohlcv

BAR_TYPE = "ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL"
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _card(*, last: datetime, bar_type: str | None = BAR_TYPE, sha: str = "abc") -> ModelCard:
    return ModelCard(
        robot="formulaic_lgbm",
        instrument_id="ETH/USDT.SIM",
        bar_type=bar_type,
        train_first_ts=T0,
        train_last_ts=last,
        horizon=5,
        rows=100,
        model_sha256=sha,
    )


def _problems(card: ModelCard | None, *, oos: datetime, **kw: object) -> tuple[str, ...]:
    return card_problems(
        card,
        robot=str(kw.get("robot", "formulaic_lgbm")),
        bar_type=str(kw.get("bar_type", BAR_TYPE)),
        first_clean_ts=oos,
        model_sha256=kw.get("sha", "abc"),  # type: ignore[arg-type]
    )


def test_card_round_trips_through_its_dict() -> None:
    card = _card(last=T0 + timedelta(days=30))
    assert ModelCard.from_dict(card.as_dict()) == card


def test_model_trained_before_oos_is_admissible() -> None:
    assert _problems(_card(last=T0 + timedelta(days=30)), oos=T0 + timedelta(days=31)) == ()


def test_model_that_saw_the_oos_bars_is_refused() -> None:
    """The matrix case: train window [2024-01-01, 2026-09-17) covered every OOS fold."""
    problems = _problems(_card(last=T0 + timedelta(days=60)), oos=T0 + timedelta(days=31))
    assert any("leak" in problem for problem in problems)


def test_last_training_bar_equal_to_first_oos_bar_is_a_leak() -> None:
    oos = T0 + timedelta(days=31)
    assert _problems(_card(last=oos), oos=oos)


def test_model_for_another_instrument_is_refused() -> None:
    """The matrix case: the ETH booster ran on BTC bars without a word."""
    problems = _problems(
        _card(last=T0),
        oos=T0 + timedelta(days=1),
        bar_type="BTC/USDT.SIM-1-HOUR-LAST-EXTERNAL",
    )
    assert any("bar_type" in problem for problem in problems)


def test_book_model_checks_the_instrument_prefix() -> None:
    card = _card(last=T0, bar_type=None)
    assert _problems(card, oos=T0 + timedelta(days=1)) == ()
    assert _problems(card, oos=T0 + timedelta(days=1), bar_type="BTC/USDT.SIM-1-HOUR-LAST")


def test_missing_card_and_swapped_file_are_refused() -> None:
    assert _problems(None, oos=T0)
    assert _problems(_card(last=T0), oos=T0 + timedelta(days=1), sha="other")
    assert _problems(_card(last=T0), oos=T0 + timedelta(days=1), sha=None)


def test_card_for_another_robot_is_refused() -> None:
    assert _problems(_card(last=T0), oos=T0 + timedelta(days=1), robot="meta_label")


def test_json_store_round_trip_and_corrupt_card(tmp_path: Path) -> None:
    model = tmp_path / "formulaic.txt"
    model.write_text("booster", "utf-8")
    sha = file_sha256(model)
    assert sha is not None
    card = _card(last=T0, sha=sha)
    written = write_model_card(model, card)
    assert written == card_path(model) == tmp_path / "formulaic.txt.card.json"
    source = JsonModelCardSource()
    assert source.card_for(str(model)) == card
    assert source.sha256_of(str(model)) == sha
    written.write_text("{not json", "utf-8")
    assert source.card_for(str(model)) is None


def _limits() -> RiskLimits:
    return RiskLimits(
        risk_per_trade=Decimal("0.005"),
        stop_pct=Decimal("0.01"),
        max_daily_loss=Decimal("0.02"),
        max_drawdown=Decimal("0.06"),
    )


def _request(robot: RobotName, model_path: str | None) -> BacktestRequest:
    return BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=600,
        starting_equity=Decimal("100000"),
        risk=_limits(),
        robot=robot,
        bar_type=BAR_TYPE,
        formulaic_model_path=model_path,
    )


class _Source:
    def __init__(self, card: ModelCard | None) -> None:
        self.card = card

    def card_for(self, model_path: str) -> ModelCard | None:
        return self.card

    def sha256_of(self, model_path: str) -> str | None:
        return "abc"


def test_guard_ignores_robots_without_a_model() -> None:
    require_clean_model(_request(RobotName.EMA, None), first_clean_ts=T0, source=_Source(None))


def test_guard_fails_closed_without_a_model_path() -> None:
    with pytest.raises(ModelArtifactMissingError):
        require_clean_model(
            _request(RobotName.FORMULAIC_LGBM, None), first_clean_ts=T0, source=_Source(None)
        )


def test_walk_forward_refuses_a_model_trained_through_the_oos_folds() -> None:
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=600, seed=5)
    calls: list[int] = []

    class Engine:
        def run(
            self,
            request: BacktestRequest,
            folded: list[OhlcvBar],
            ticks: list[AggTrade] | None = None,
            books: list[OrderBookSnapshot] | None = None,
        ) -> BacktestReport:
            calls.append(len(folded))
            return BacktestReport(fills=1, positions=1, ending_balance=Decimal("1"), notes="")

        def run_spread(self, *args: object, **kwargs: object) -> BacktestReport:
            raise AssertionError("single-leg robot")

    class Feed:
        def load(self, request: BacktestRequest) -> list[OhlcvBar]:
            return bars

        def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
            return {request.instrument_id: bars}

    leaking = _card(last=bars[-1].ts_utc)
    use_case = RunWalkForward(Engine(), Feed(), model_cards=_Source(leaking))
    request = WalkForwardRequest(
        backtest=_request(RobotName.FORMULAIC_LGBM, "models/f.txt"), folds=2
    )
    with pytest.raises(ModelLeakError, match="leak"):
        use_case.execute_multi(request)
    assert calls == [], "nothing may be scored with a leaking model"

    clean = _card(last=bars[0].ts_utc)
    RunWalkForward(Engine(), Feed(), model_cards=_Source(clean)).execute_multi(request)
    assert calls


def test_obi_book_symbol_drops_the_slash() -> None:
    from nautilus_lab.application.train_obi import obi_book_symbol

    assert obi_book_symbol("ETH/USDT.SIM") == "ETHUSDT"
    assert obi_book_symbol("BTC/USDT.SIM") == "BTCUSDT"
    assert obi_book_symbol("ETHUSDT-PERP.SIM") == "ETHUSDTPERP"
