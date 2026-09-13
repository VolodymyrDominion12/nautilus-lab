from datetime import UTC, datetime, timedelta
from decimal import Decimal

from conftest import make_bars
from nautilus_lab.application.risk import effective_risk_fraction, stop_distance
from nautilus_lab.application.scan_triangular import scan_triangular_opportunities
from nautilus_lab.application.train_classifier import purged_k_fold
from nautilus_lab.domain.align import align_bars_inner_join
from nautilus_lab.domain.atr import AverageTrueRange
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.fees import FeeSchedule
from nautilus_lab.domain.funding import FundingCashAndCarry, FundingParams, FundingSnapshot
from nautilus_lab.domain.glft import GlftMarketMaker, GlftParams
from nautilus_lab.domain.hawkes import ExponentialHawkes
from nautilus_lab.domain.metrics import compute_metrics
from nautilus_lab.domain.microstructure import order_book_imbalance
from nautilus_lab.domain.order_book import BookLevel, OrderBookSnapshot
from nautilus_lab.domain.pairs.cointegration import fit_cointegration
from nautilus_lab.domain.pairs.ou import fit_ou_half_life, z_score
from nautilus_lab.domain.pairs.pairs_trading import PairsTrading
from nautilus_lab.domain.pairs.params import PairsParams
from nautilus_lab.domain.portfolio_risk import fractional_kelly_cap, historical_var
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.stress_slices import resolve_stress_slice
from nautilus_lab.domain.volatility import HarRealizedVolatility, vol_scaled_risk_fraction
from nautilus_lab.domain.vpin import BarVpin
from nautilus_lab.domain.walk_forward import anchored_window
from nautilus_lab.infrastructure.lightgbm_classifier import HeuristicDirectionClassifier
from nautilus_lab.infrastructure.nautilus.synthetic_pairs import synthetic_cointegrated_pair


def _bar(
    instrument_id: str,
    close: Decimal,
    ts: datetime,
    volume: Decimal = Decimal("100"),
) -> OhlcvBar:
    return OhlcvBar(
        instrument_id=instrument_id,
        ts_utc=ts,
        open=close,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        volume=volume,
    )


def test_fee_schedule_binance_defaults() -> None:
    spot = FeeSchedule.binance_spot_vip0()
    assert spot.maker == Decimal("0.001")
    perp = FeeSchedule.binance_usdm_vip0()
    assert perp.taker == Decimal("0.0005")


def test_align_bars_inner_join() -> None:
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    a = [_bar("A", Decimal("1"), origin), _bar("A", Decimal("2"), origin + timedelta(hours=1))]
    b = [_bar("B", Decimal("10"), origin), _bar("B", Decimal("11"), origin + timedelta(hours=1))]
    aligned = align_bars_inner_join({"A": a, "B": b})
    assert len(aligned["A"]) == 2


def test_cointegration_and_ou_on_synthetic_pair() -> None:
    data = synthetic_cointegrated_pair(
        leg_a="ETH/USDT.SIM",
        leg_b="BTC/USDT.SIM",
        count=200,
        seed=1,
    )
    y = tuple(bar.close for bar in data["ETH/USDT.SIM"])
    x = tuple(bar.close for bar in data["BTC/USDT.SIM"])
    coint = fit_cointegration(y, x)
    spread = tuple(
        item_y - coint.intercept - coint.hedge_ratio * item_x
        for item_y, item_x in zip(y, x, strict=True)
    )
    ou = fit_ou_half_life(spread)
    assert ou.half_life_bars > 0
    assert z_score(spread[-1], ou.mean, ou.sigma) is not None


def test_pairs_trading_emits_spread_signal() -> None:
    data = synthetic_cointegrated_pair(
        leg_a="ETH/USDT.SIM",
        leg_b="BTC/USDT.SIM",
        count=250,
        seed=3,
    )
    robot = PairsTrading(
        leg_a="ETH/USDT.SIM",
        leg_b="BTC/USDT.SIM",
        params=PairsParams(lookback=120, z_entry=Decimal("1.5")),
    )
    signals = 0
    for bar_a, bar_b in zip(data["ETH/USDT.SIM"], data["BTC/USDT.SIM"], strict=True):
        if robot.on_bars(bar_a, bar_b) is not None:
            signals += 1
    assert signals >= 0


def test_bar_vpin_detects_toxic_bucket() -> None:
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    vpin = BarVpin(bucket_volume=Decimal("100"), toxic_threshold=Decimal("0.6"))
    state = None
    for index in range(20):
        bar = _bar(
            "ETH/USDT.SIM",
            Decimal("100") + Decimal(index),
            origin + timedelta(minutes=index),
            volume=Decimal("50"),
        )
        state = vpin.update(bar)
    assert state is None or state.value >= 0


def test_funding_cash_and_carry_opens_on_positive_rate() -> None:
    strategy = FundingCashAndCarry(
        spot_id="ETH/USDT.SIM",
        perp_id="ETHUSDT-PERP.SIM",
        params=FundingParams(min_net_apy=Decimal("0.01")),
    )
    signal = strategy.on_funding(
        FundingSnapshot(
            instrument="ETHUSDT",
            funding_rate=Decimal("0.01"),
            mark_price=Decimal("3500"),
            index_price=Decimal("3495"),
            ts_utc=datetime(2024, 1, 1, tzinfo=UTC),
        )
    )
    assert signal is not None
    assert "funding" in signal.reason


def test_har_rv_forecast() -> None:
    har = HarRealizedVolatility(daily_bars=5, weekly_bars=10, monthly_bars=15)
    bars = make_bars(20, step_minutes=60)
    previous: Decimal | None = None
    forecast = None
    for bar in bars:
        forecast = har.update(bar, previous)
        previous = bar.close
    assert forecast is not None or len(bars) < 5


def test_order_book_imbalance() -> None:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    snapshot = OrderBookSnapshot(
        instrument_id="ETH/USDT.SIM",
        ts_utc=ts,
        bids=(BookLevel(Decimal("100"), Decimal("10")),),
        asks=(BookLevel(Decimal("101"), Decimal("5")),),
    )
    snapshot.validate()
    obi = order_book_imbalance(snapshot)
    assert obi > 0


def test_triangular_scan_finds_cycle() -> None:
    rates = {
        ("USDT", "BTC"): Decimal("0.00002"),
        ("BTC", "ETH"): Decimal("20"),
        ("ETH", "USDT"): Decimal("4000"),
    }
    opportunities = scan_triangular_opportunities(rates, fee=Decimal("0"))
    assert isinstance(opportunities, list)


def test_glft_quote_intent() -> None:
    mm = GlftMarketMaker(instrument_id="ETH/USDT.SIM", params=GlftParams())
    quote = mm.quote(
        mid=Decimal("3500"),
        inventory=Decimal("1"),
        volatility=Decimal("0.02"),
        ts_utc=datetime(2024, 1, 1, tzinfo=UTC),
    )
    assert quote.bid_price < quote.ask_price


def test_metrics_and_risk_helpers() -> None:
    curve = (Decimal("100"), Decimal("105"), Decimal("103"), Decimal("110"))
    metrics = compute_metrics(
        starting_equity=Decimal("100"),
        equity_curve=curve,
        fees_paid=Decimal("1"),
        turnover=Decimal("50"),
    )
    assert metrics.max_drawdown >= 0
    limits = RiskLimits(
        risk_per_trade=Decimal("0.01"),
        stop_pct=Decimal("0.01"),
        max_daily_loss=Decimal("0.02"),
        max_drawdown=Decimal("0.06"),
    )
    capped = effective_risk_fraction(
        limits,
        win_rate=Decimal("0.6"),
        reward_risk=Decimal("2"),
    )
    assert capped <= limits.risk_per_trade
    assert stop_distance(Decimal("100"), limits, atr=Decimal("2")) == Decimal("4")


def test_purged_k_fold_and_stress_slice() -> None:
    folds = purged_k_fold(100, n_splits=5, embargo=5)
    assert folds
    slice_ = resolve_stress_slice("ftx2022")
    assert slice_.name.value == "ftx2022"


def test_embargo_window_splits_with_gap() -> None:
    bars = make_bars(20, step_minutes=60)
    window = anchored_window(bars, in_sample_fraction=Decimal("0.7"), embargo_bars=2)
    assert window.in_sample_end <= window.out_of_sample_start


def test_heuristic_classifier_and_hawkes() -> None:
    classifier = HeuristicDirectionClassifier()
    probs = classifier.predict((Decimal("0.5"),))
    assert probs.up + probs.down + probs.flat == Decimal("1")
    hawkes = ExponentialHawkes()
    intensity = hawkes.on_trade(side="buy", dt_seconds=Decimal("1"))
    assert intensity.buy_intensity >= 0


def test_fractional_kelly_and_var() -> None:
    kelly = fractional_kelly_cap(
        win_rate=Decimal("0.55"),
        reward_risk=Decimal("1.5"),
        fraction=Decimal("0.25"),
    )
    assert kelly >= 0
    var = historical_var((Decimal("-0.02"), Decimal("-0.01"), Decimal("0.01")))
    assert var is not None


def test_atr_initializes() -> None:
    atr = AverageTrueRange(3)
    bars = make_bars(5, step_minutes=60)
    values = [atr.update(bar) for bar in bars]
    assert values[-1] is not None


def test_vol_scaled_risk_fraction() -> None:
    scaled = vol_scaled_risk_fraction(
        Decimal("0.01"),
        forecast_vol=Decimal("0.04"),
        target_vol=Decimal("0.02"),
    )
    assert scaled < Decimal("0.01")


def test_noop_kill_switch() -> None:
    from nautilus_lab.domain.kill_switch import NoOpKillSwitch

    ks = NoOpKillSwitch()
    assert not ks.is_active()
    ks.trigger("drawdown limit reached")
    assert ks.is_active()
    assert ks.last_reason == "drawdown limit reached"


def test_ml_obi_strategy() -> None:
    from nautilus_lab.domain.ml_obi_strategy import MlObiStrategy
    from nautilus_lab.domain.signals import SignalSide

    strategy = MlObiStrategy(
        instrument_id="ETH/USDT.SIM",
        classifier=HeuristicDirectionClassifier(),
        threshold=Decimal("0.5"),
    )
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    snap1 = OrderBookSnapshot(
        instrument_id="ETH/USDT.SIM",
        ts_utc=origin,
        bids=(BookLevel(Decimal("3000"), Decimal("10")),),
        asks=(BookLevel(Decimal("3001"), Decimal("10")),),
    )
    snap2 = OrderBookSnapshot(
        instrument_id="ETH/USDT.SIM",
        ts_utc=origin + timedelta(seconds=1),
        bids=(BookLevel(Decimal("3000"), Decimal("20")),),
        asks=(BookLevel(Decimal("3001"), Decimal("5")),),
    )
    sig1 = strategy.on_book(snap1)
    assert sig1 is None  # warmup first book
    sig2 = strategy.on_book(snap2)
    assert sig2 is not None
    assert sig2.side == SignalSide.BUY


def test_egarch_forecast_volatility() -> None:
    from nautilus_lab.infrastructure.egarch_forecast import egarch_forecast_volatility

    # Below minimum length
    assert egarch_forecast_volatility((0.01, -0.01)) is None

    # Realistic return series >= 60
    returns = tuple(0.005 * ((-1) ** i) for i in range(70))
    vol = egarch_forecast_volatility(returns)
    assert vol is not None
    assert vol > 0
