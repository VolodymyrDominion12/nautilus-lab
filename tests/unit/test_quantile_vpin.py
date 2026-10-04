"""Tests for QuantileVpin — adaptive rolling-quantile VPIN model.

IS-гіпотеза «перцентильний поріг» (spec vpin_momentum.yaml §hypothesis).
Усі тести — без мережі, синтетичні дані.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.signals import SignalSide
from nautilus_lab.domain.vpin import BarVpin, QuantileVpin
from nautilus_lab.domain.vpin_momentum import VpinMomentum

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bar(
    close: str,
    index: int = 0,
    volume: str = "1000",
    taker_buy: str | None = None,
) -> OhlcvBar:
    ts = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=index)
    c = Decimal(close)
    return OhlcvBar(
        instrument_id="ETH/USDT.SIM",
        ts_utc=ts,
        open=c,
        high=c + Decimal("1"),
        low=c - Decimal("1"),
        close=c,
        volume=Decimal(volume),
        taker_buy_base_volume=Decimal(taker_buy) if taker_buy is not None else None,
    )


def _fill_buckets(vpin: QuantileVpin, fractions: list[str]) -> None:
    """Заповнює по одному кошику (bucket_volume=100) з заданою часткою buy."""
    for i, frac in enumerate(fractions):
        vpin.update(
            _bar("100", index=i, volume="100", taker_buy=str(Decimal(frac) * Decimal("100")))
        )


# ---------------------------------------------------------------------------
# 1. Базова конструкція — валідація аргументів
# ---------------------------------------------------------------------------


def test_constructor_rejects_zero_quantile() -> None:
    with pytest.raises(ValueError, match="quantile"):
        QuantileVpin(bucket_volume=Decimal("100"), quantile=Decimal("0"))


def test_constructor_rejects_quantile_above_one() -> None:
    with pytest.raises(ValueError, match="quantile"):
        QuantileVpin(bucket_volume=Decimal("100"), quantile=Decimal("1.01"))


def test_constructor_rejects_zero_lookback() -> None:
    with pytest.raises(ValueError, match="lookback"):
        QuantileVpin(bucket_volume=Decimal("100"), lookback=0)


def test_constructor_rejects_zero_min_buckets() -> None:
    with pytest.raises(ValueError, match="min_buckets"):
        QuantileVpin(bucket_volume=Decimal("100"), min_buckets=0)


# ---------------------------------------------------------------------------
# 2. Прогрів: до min_buckets кошиків — toxic завжди False
# ---------------------------------------------------------------------------


def test_no_toxic_before_warmup() -> None:
    """До накопичення min_buckets завершених кошиків toxic=False (консервативно)."""
    vpin = QuantileVpin(bucket_volume=Decimal("100"), quantile=Decimal("0.90"), min_buckets=5)
    # 1 бар = 1 кошик, але < min_buckets=5
    state = vpin.update(_bar("100", volume="100", taker_buy="90"))
    assert state is not None
    assert not state.toxic


def test_toxic_threshold_is_one_before_warmup() -> None:
    """Властивість toxic_threshold до прогріву = 1 (= ніколи не токсично)."""
    vpin = QuantileVpin(bucket_volume=Decimal("100"), min_buckets=10)
    vpin.update(_bar("100", volume="100", taker_buy="80"))
    assert vpin.toxic_threshold == Decimal("1")


# ---------------------------------------------------------------------------
# 3. Після прогріву: поріг = rolling-квантиль
# ---------------------------------------------------------------------------


def test_after_warmup_threshold_equals_quantile_value() -> None:
    """Поріг після прогріву = floor(q * n)-й елемент відсортованого вікна."""
    vpin = QuantileVpin(bucket_volume=Decimal("100"), quantile=Decimal("0.80"), min_buckets=5)
    # 10 кошиків: частки 0.50..0.95 → VPIN = |2*buy-100|/100
    # 0.50→0.00, 0.55→0.10, ..., 0.95→0.90
    fractions = ["0.50", "0.55", "0.60", "0.65", "0.70", "0.75", "0.80", "0.85", "0.90", "0.95"]
    _fill_buckets(vpin, fractions)
    # idx = floor(0.80 * 10) = 8 → sorted[8] = 0.8
    assert abs(vpin.toxic_threshold - Decimal("0.8")) < Decimal("0.01")


def test_last_bucket_is_toxic_when_above_median() -> None:
    """Кошик з VPIN > поточного порогу (медіана) має toxic=True."""
    vpin = QuantileVpin(bucket_volume=Decimal("100"), quantile=Decimal("0.50"), min_buckets=5)
    # 5 збалансованих кошиків (VPIN=0)
    for i in range(5):
        vpin.update(_bar("100", index=i, volume="100", taker_buy="50"))
    # Сильно однобічний (VPIN≈0.9) > median=0
    state = vpin.update(_bar("100", index=5, volume="100", taker_buy="95"))
    assert state is not None
    assert state.toxic


def test_balanced_bucket_is_not_toxic_when_threshold_is_high() -> None:
    """Збалансований кошик (VPIN≈0) при високому порозі НЕ токсичний."""
    vpin = QuantileVpin(bucket_volume=Decimal("100"), quantile=Decimal("0.50"), min_buckets=5)
    # 10 сильно однобічних → поріг ≈ p50(0.9) = 0.9
    for i in range(10):
        vpin.update(_bar("100", index=i, volume="100", taker_buy="95"))
    state = vpin.update(_bar("100", index=10, volume="100", taker_buy="50"))  # VPIN=0
    assert state is not None
    assert not state.toxic


# ---------------------------------------------------------------------------
# 4. Rolling-вікно: lookback обмежує пам'ять
# ---------------------------------------------------------------------------


def test_old_buckets_pruned_beyond_lookback() -> None:
    """Після lookback кошиків стара інформація відкидається — поріг зсувається."""
    vpin = QuantileVpin(
        bucket_volume=Decimal("100"),
        quantile=Decimal("0.90"),
        min_buckets=5,
        lookback=5,
    )
    # 10 низьких VPIN кошиків (VPIN=0)
    for i in range(10):
        vpin.update(_bar("100", index=i, volume="100", taker_buy="50"))
    threshold_low = vpin.toxic_threshold

    # 10 високих VPIN кошиків (VPIN=0.9)
    for i in range(10, 20):
        vpin.update(_bar("100", index=i, volume="100", taker_buy="95"))
    threshold_high = vpin.toxic_threshold

    # lookback=5: старі нульові кошики вже за межею, поріг має піднятися
    assert threshold_high > threshold_low


# ---------------------------------------------------------------------------
# 5. Протокол VpinModel
# ---------------------------------------------------------------------------


def test_quantile_vpin_is_subclass_of_bar_vpin() -> None:
    """QuantileVpin є підкласом BarVpin і задовольняє VpinModel-протокол."""
    vpin = QuantileVpin(bucket_volume=Decimal("100"))
    assert isinstance(vpin, BarVpin)
    assert hasattr(vpin, "last")
    assert hasattr(vpin, "update")
    assert hasattr(vpin, "toxic_threshold")


# ---------------------------------------------------------------------------
# 6. Інтеграція з VpinMomentum
# ---------------------------------------------------------------------------


def test_vpin_momentum_with_quantile_vpin_generates_buy() -> None:
    """З QuantileVpin (quantile=0.50) VpinMomentum генерує BUY після прогріву."""
    vpin = QuantileVpin(
        bucket_volume=Decimal("100"),
        quantile=Decimal("0.50"),
        min_buckets=5,
        lookback=100,
    )
    robot = VpinMomentum(
        instrument_id="ETH/USDT.SIM",
        vpin=vpin,
        ema_period=3,
        atr_period=2,
        min_hold_bars=0,
    )

    # Фаза 1: 10 збалансованих барів (VPIN=0) → прогрів, поріг=0
    for i in range(10):
        robot.on_bar(_bar("100", index=i, volume="100", taker_buy="50"))

    # Фаза 2: сильно однобічні бари з зростаючою ціною → VPIN=0.9 > median=0
    signals = []
    for i in range(10, 20):
        sig = robot.on_bar(_bar(str(100 + i), index=i, volume="100", taker_buy="95"))
        if sig is not None:
            signals.append(sig)

    sides = {s.side for s in signals}
    assert SignalSide.BUY in sides, f"Очікували BUY з QuantileVpin, отримали: {sides or 'нічого'}"


def test_bar_vpin_threshold_07_never_fires_on_near_balanced_flow() -> None:
    """Регресія: BarVpin(threshold=0.7) не торгує при потоці max VPIN≈0.3.

    Відтворює картину з бектест-звітів (ETH/BTC, серпень–жовтень 2026).
    """
    vpin = BarVpin(bucket_volume=Decimal("100"), toxic_threshold=Decimal("0.7"))
    robot = VpinMomentum(
        instrument_id="ETH/USDT.SIM",
        vpin=vpin,
        ema_period=5,
        atr_period=3,
        min_hold_bars=0,
    )
    # taker_buy 35-65% → VPIN = 0.0-0.3, далеко від порогу 0.7
    signals = []
    for i in range(100):
        frac_val = "35" if i % 2 == 0 else "65"
        sig = robot.on_bar(_bar(str(100 + i % 10), index=i, volume="100", taker_buy=frac_val))
        if sig is not None:
            signals.append(sig)

    entries = [s for s in signals if s.side in (SignalSide.BUY, SignalSide.SELL)]
    assert len(entries) == 0, (
        f"BarVpin(threshold=0.7) не повинен давати входів при VPIN≤0.3, "
        f"але отримали: {[s.side for s in entries]}"
    )


def test_massive_volume_bar_performance() -> None:
    """Регресія: бари з гігантським обсягом (наприклад, DOGE 50M) обробляються за мілісекунди."""
    import time

    bar = _bar("0.1", volume="50000000", taker_buy="30000000")
    vpin = QuantileVpin(bucket_volume=Decimal("1000"), lookback=100)
    t0 = time.perf_counter()
    state = vpin.update(bar)
    elapsed = time.perf_counter() - t0

    assert state is not None
    # 50M обсягу / 1000 розмір кошика = 50 000 повних кошиків має виконатися < 0.05с (було > 0.8с на один бар)
    assert elapsed < 0.05, f"Обробка бару зайняла {elapsed:.4f}s замість < 0.05s"
    assert state.bucket_filled == Decimal("1000")
