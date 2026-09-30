from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.regime import RegimeParams
from nautilus_lab.domain.regime_router import RegimeRouter
from nautilus_lab.domain.signals import SignalSide


def _bar(close: Decimal, index: int) -> OhlcvBar:
    ts = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(minutes=index)
    return OhlcvBar(
        instrument_id="ETH/USDT.SIM",
        ts_utc=ts,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=Decimal("1"),
    )


def _params() -> RegimeParams:
    return RegimeParams(
        er_period=5,
        trend_ema_period=5,
        slope_lookback=3,
        enter_trend_er=Decimal("0.40"),
        exit_trend_er=Decimal("0.20"),
        donchian_period=3,
        bb_period=5,
        bb_k=Decimal("1.5"),
    )


def test_router_flattens_on_regime_change() -> None:
    router = RegimeRouter(instrument_id="ETH/USDT.SIM", params=_params())
    for index in range(1, 20):
        router.on_bar(_bar(Decimal(100 + index), index))
    crash_signals = []
    for offset, close in enumerate((Decimal("80"), Decimal("60"), Decimal("40"), Decimal("20"))):
        crash_signals.append(router.on_bar(_bar(close, 20 + offset)))

    flats = [
        signal for signal in crash_signals if signal is not None and signal.side is SignalSide.FLAT
    ]
    assert flats
    assert flats[0].reason.startswith("regime change")


def test_router_is_silent_until_classifier_is_warm() -> None:
    router = RegimeRouter(instrument_id="ETH/USDT.SIM", params=_params())
    first = router.on_bar(_bar(Decimal("100"), 0))
    assert first is None


def test_b2_inactive_legs_stay_warm_during_uptrend() -> None:
    """B2 regression: всі три ноги мають отримувати on_bar на кожному барі.

    До фіксу: неактивна нога не отримувала on_bar() і не заповнювала свій
    RollingWindow. При переключенні режиму вона «прокидалась» не ініціалізована
    і повертала warmup-step замість сигналу.
    """
    params = RegimeParams(
        er_period=4,
        trend_ema_period=4,
        slope_lookback=2,
        enter_trend_er=Decimal("0.40"),
        exit_trend_er=Decimal("0.20"),
        donchian_period=3,
        bb_period=4,
        bb_k=Decimal("1.5"),
    )
    router = RegimeRouter(instrument_id="ETH/USDT.SIM", params=params)

    # Тривалий uptrend — понад max(er+1, ema+slope, channel+1) барів, щоб усі
    # три ноги точно прогрілись (B2 fix).
    warmup = 30
    for i in range(warmup):
        router.on_bar(_bar(Decimal(100 + i), i))

    # Різкий downtrend — classifier перейде в DOWNTREND і router випустить FLAT.
    router.on_bar(_bar(Decimal("50"), warmup))
    router.on_bar(_bar(Decimal("30"), warmup + 1))
    router.on_bar(_bar(Decimal("20"), warmup + 2))

    # Trace НЕ повинен мати warmup_step для DowntrendBreakout.
    trace_components = [step.component for step in router.last_trace]
    assert "DowntrendBreakout" in trace_components, (
        f"B2 regression: DowntrendBreakout не в trace. Trace: {router.last_trace}"
    )
    warmup_steps = [
        s
        for s in router.last_trace
        if s.component == "DowntrendBreakout" and s.verdict.value == "skip"
    ]
    assert not warmup_steps, (
        f"B2 regression: DowntrendBreakout у warmup після {warmup} барів. "
        f"Trace: {router.last_trace}"
    )


def test_b3_range_leg_is_warm_after_uptrend() -> None:
    """B3 regression: range-нога заповнена після тривалого uptrend."""
    params = RegimeParams(
        er_period=4,
        trend_ema_period=4,
        slope_lookback=2,
        enter_trend_er=Decimal("0.60"),
        exit_trend_er=Decimal("0.20"),
        donchian_period=3,
        bb_period=4,
        bb_k=Decimal("1.5"),
    )
    router = RegimeRouter(instrument_id="ETH/USDT.SIM", params=params)

    # Прогрів у чіткому тренді
    for i in range(25):
        router.on_bar(_bar(Decimal(100 + i * 2), i))

    # Боковий рух → RANGE
    base = Decimal("150")
    for j in range(15):
        close = base + (Decimal(1) if j % 2 == 0 else Decimal(-1))
        router.on_bar(_bar(close, 25 + j))

    trace_components = [step.component for step in router.last_trace]
    assert "RangeMeanReversion" in trace_components, (
        f"B3 regression: RangeMeanReversion не в trace. Trace: {router.last_trace}"
    )
    warmup_steps = [
        s
        for s in router.last_trace
        if s.component == "RangeMeanReversion" and s.verdict.value == "skip"
    ]
    assert not warmup_steps, (
        f"B3 regression: RangeMeanReversion у warmup після 25+ барів. Trace: {router.last_trace}"
    )


def test_router_preserves_short_when_transitioning_to_downtrend() -> None:
    """SHORT, відкритий у RANGE (Bollinger upper band), не скидається при переході в DOWNTREND."""
    params = RegimeParams(
        er_period=5,
        trend_ema_period=5,
        slope_lookback=3,
        enter_trend_er=Decimal("0.40"),
        exit_trend_er=Decimal("0.20"),
        donchian_period=4,
        bb_period=5,
        bb_k=Decimal("1.2"),
    )
    router = RegimeRouter(instrument_id="ETH/USDT.SIM", params=params)

    # Прогрів у флеті навколо 100
    for i in range(15):
        val = Decimal("100") + (Decimal("1") if i % 2 == 0 else Decimal("-1"))
        router.on_bar(_bar(val, i))

    # Сплеск вгору для торкання верхньої смуги Боллінджера у RANGE -> сигнал SELL
    sell_sig = router.on_bar(_bar(Decimal("105"), 15))
    assert sell_sig is not None
    assert sell_sig.side is SignalSide.SELL
    assert router.current_side is SignalSide.SELL

    # Тепер різке падіння -> перехід у DOWNTREND (ER зростає, нахил від'ємний)
    signals = []
    for offset, close in enumerate((Decimal("95"), Decimal("85"), Decimal("75"), Decimal("65"))):
        signals.append(router.on_bar(_bar(close, 16 + offset)))

    # Жоден сигнал не повинен бути FLAT через зміну режиму
    flats = [s for s in signals if s is not None and s.side is SignalSide.FLAT]
    assert not flats, f"Очікувалось збереження SHORT, але отримано FLAT: {flats}"
    assert router.last_effective_regime is not None
    assert router.last_effective_regime.value == "downtrend"
    assert router.current_side == SignalSide.SELL


def test_router_holding_trend_long_in_range_until_ema_violated() -> None:
    """LONG з UPTREND не ліквідується у RANGE, доки ціна залишається вище EMA."""
    params = RegimeParams(
        er_period=5,
        trend_ema_period=5,
        slope_lookback=3,
        enter_trend_er=Decimal("0.50"),
        exit_trend_er=Decimal("0.30"),
        donchian_period=3,
        bb_period=5,
        bb_k=Decimal("2.0"),
    )
    router = RegimeRouter(instrument_id="ETH/USDT.SIM", params=params)

    # Прогрів і вхід у лонг на аптренді
    for i in range(20):
        router.on_bar(_bar(Decimal(100 + i * 5), i))
    side_at_trend: SignalSide = router.current_side
    assert side_at_trend is SignalSide.BUY

    # Тепер консолідація (ER падає нижче 0.30 -> перехід у RANGE), але ціна тримається вище EMA
    # Ціна останнього бару була ~195, EMA ~180. Консолідуємось навколо 195:
    range_signals = []
    for j in range(5):
        close = Decimal("195") + (Decimal("0.5") if j % 2 == 0 else Decimal("-0.5"))
        range_signals.append(router.on_bar(_bar(close, 20 + j)))

    # У RANGE позиція не скидається в FLAT
    flats = [s for s in range_signals if s is not None and s.side is SignalSide.FLAT]
    assert not flats, "Позиція була передчасно закрита у RANGE, хоча EMA не пробита"
    side_at_range: SignalSide = router.current_side
    assert side_at_range is SignalSide.BUY

    # Тепер ціна пробиває EMA вниз (падає до 120), що генерує FLAT
    drop_sig = router.on_bar(_bar(Decimal("120"), 25))
    assert drop_sig is not None
    assert drop_sig.side is SignalSide.FLAT
    assert "EMA exit" in drop_sig.reason or "regime change" in drop_sig.reason
    side_after_drop: SignalSide = router.current_side
    assert side_after_drop is SignalSide.FLAT


def test_router_confirmation_bars_filters_one_bar_spike() -> None:
    """confirmation_bars=2 запобігає перемиканню режиму на 1-барному шумі."""
    params = RegimeParams(
        er_period=5,
        trend_ema_period=5,
        slope_lookback=3,
        enter_trend_er=Decimal("0.50"),
        exit_trend_er=Decimal("0.30"),
        donchian_period=3,
        bb_period=5,
        bb_k=Decimal("2.0"),
        confirmation_bars=2,
    )
    router = RegimeRouter(instrument_id="ETH/USDT.SIM", params=params)

    # Прогрів у стійкому UPTREND
    for i in range(20):
        router.on_bar(_bar(Decimal(100 + i * 5), i))
    assert router.last_effective_regime is not None
    assert router.last_effective_regime.value == "uptrend"

    # Один бар із різким відкатом (ER впаде), але confirmation_bars=2 не дасть перемкнутись одразу
    router.on_bar(_bar(Decimal("170"), 20))
    # Режим залишається uptrend
    assert router.last_effective_regime is not None
    assert router.last_effective_regime.value == "uptrend"
