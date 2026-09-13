# 09. MFT-модулі: робочі приклади коду

Тут зібрані **перевірені** приклади використання модулів, які не підключені до CLI
(див. статуси в [08-mft-2026-vidpovidnist.md](08-mft-2026-vidpovidnist.md)).
Кожен фрагмент виконувався на цій машині — вивід у блоках «Вивід» справжній.

Як запускати:

```bash
uv run python - <<'PY'
...код...
PY
```

або (якщо `uv` не має доступу до кеша) `.venv/bin/python - <<'PY'`.

---

## 1. VPIN: токсичність потоку на барах

```python
from decimal import Decimal

from nautilus_lab.domain.vpin import BarVpin
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_regime_ohlcv

bars = synthetic_regime_ohlcv(instrument_id="ETH/USDT.SIM", count=500, seed=3)
vpin = BarVpin(bucket_volume=Decimal("1500"), toxic_threshold=Decimal("0.7"))

buckets = [state for bar in bars if (state := vpin.update(bar)) is not None]
print("кошиків:", len(buckets), "токсичних:", sum(s.toxic for s in buckets))
print("остання VPIN:", buckets[-1].value, "токсично:", buckets[-1].toxic)
```

**Вивід:**

```
кошиків: 351 токсичних: 201
остання VPIN: 0.7866666666666666666666666667 токсично: True
```

Як користуватися: `BarVpin.update(bar)` повертає `None`, доки кошик не наповниться;
інакше — `VpinState(value, bucket_filled, toxic)`, і `value` — це `|buy − sell| / total`
для **останнього завершеного** кошика. Підбирайте `bucket_volume` так, щоб кошик наповнювався
за 10–50 барів (інакше VPIN «застигає»).

## 2. Процес Хоукса: кластеризація потоку угод

```python
from decimal import Decimal

from nautilus_lab.domain.hawkes import ExponentialHawkes

hawkes = ExponentialHawkes(
    baseline=Decimal("0.1"), alpha=Decimal("0.5"), beta=Decimal("1"), toxic_threshold=Decimal("2")
)
events = [("buy", Decimal("1.0")), ("buy", Decimal("0.4")), ("buy", Decimal("0.3")), ("sell", Decimal("5.0"))]
for side, dt in events:
    intensity = hawkes.on_trade(side=side, dt_seconds=dt)
    print(side, "buy:", intensity.buy_intensity, "sell:", intensity.sell_intensity, "toxic:", intensity.toxic_flow)
```

**Вивід:**

```
buy  buy: 0.60000000000000000 sell: 0.10000000000000000 toxic: False
buy  buy: 0.9351600230178196500 sell: 0.100000000000000000 toxic: False
buy  buy: 1.218701762236563718449682674 sell: 0.1000000000000000000 toxic: False
sell buy: 0.1075377531817334781183133927 sell: 0.600000000000000000 toxic: False
```

Добре видно самозбудження: серія покупок підняла `buy_intensity` з 0.6 до 1.22,
а після паузи 5 секунд і однієї продажі інтенсивність покупок обвалилася до 0.107.
`dt_seconds` — час **між** подіями (саме він керує затуханням `exp(−β·dt)`).

## 3. Мікроструктура книги ордерів

```python
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_lab.domain.microstructure import (
    liquidity_fade_velocity,
    order_book_imbalance,
    weighted_order_flow_imbalance,
)
from nautilus_lab.domain.order_book import BookLevel, OrderBookSnapshot

ts = datetime(2025, 1, 1, tzinfo=UTC)


def snap(bids, asks, ts=ts):
    book = OrderBookSnapshot(
        instrument_id="ETH/USDT.SIM",
        ts_utc=ts,
        bids=tuple(BookLevel(Decimal(p), Decimal(q)) for p, q in bids),
        asks=tuple(BookLevel(Decimal(p), Decimal(q)) for p, q in asks),
    )
    book.validate()          # перевіряє перевернуту/перехрещену книгу
    return book


prev = snap([("3500", "10"), ("3499", "8")], [("3501", "6"), ("3502", "5")])
curr = snap([("3500", "4"), ("3499", "3")], [("3501", "9"), ("3502", "7")], ts + timedelta(minutes=1))

print("OBI:", order_book_imbalance(curr))
print("WOFI:", weighted_order_flow_imbalance(curr, prev))
print("Fade:", liquidity_fade_velocity(curr, prev))
```

**Вивід:**

```
OBI: -0.3913043478260869565217391304
WOFI: -0.6326836581709145427286356821
Fade: 16
```

Читаємо: біди «висохли» (10+8 → 4+3), аски виросли (11 → 16). `OBI` став від'ємним
(перевага продавців), `WOFI` показує, наскільки швидко це сталося, `Fade = 16` — чистий відтік
ліквідності з бідів. Саме такі ознаки MFT-документ називає провісниками руху ціни.

## 4. ML-стратегія за дисбалансом книги

```python
from decimal import Decimal

from nautilus_lab.domain.ml_obi_strategy import MlObiStrategy
from nautilus_lab.infrastructure.lightgbm_classifier import HeuristicDirectionClassifier

robot = MlObiStrategy(
    instrument_id="ETH/USDT.SIM",
    classifier=HeuristicDirectionClassifier(),   # замініть на LightGBMDirectionClassifier(model_path=...)
    threshold=Decimal("0.55"),
)
for book in (prev, curr):                        # змінні з прикладу 3
    signal = robot.on_book(book)
    print(None if signal is None else (signal.side.value, signal.reason))
```

**Вивід:**

```
None
('sell', 'ml_obi')
```

Перший знімок лише запам'ятовується (потрібні два, щоб порахувати WOFI і Fade).
Другий дає `sell`, бо евристика бачить від'ємний OBI.

`HeuristicDirectionClassifier` — це fallback-правила: `OBI > 0.2` → up, `OBI < −0.2` → down.
Для справжньої моделі: `uv sync --extra ml`, навчіть LightGBM-бустер і передайте шлях
у `LightGBMDirectionClassifier(model_path="model.txt")`.

## 5. GLFT-котировки маркет-мейкера

```python
from datetime import UTC, datetime
from decimal import Decimal

from nautilus_lab.domain.glft import GlftMarketMaker, GlftParams

mm = GlftMarketMaker(
    instrument_id="ETH/USDT.SIM",
    params=GlftParams(gamma=Decimal("0.1"), base_half_spread_bps=Decimal("5")),
)
for inventory in (Decimal("0"), Decimal("10"), Decimal("-10")):
    quote = mm.quote(
        mid=Decimal("3500"), inventory=inventory, volatility=Decimal("0.02"),
        ts_utc=datetime(2025, 1, 1, tzinfo=UTC),
    )
    print(f"inventory={inventory:>4}  bid={quote.bid_price}  ask={quote.ask_price}")
```

**Вивід:**

```
inventory=   0  bid=3498.24996  ask=3501.75004
inventory=  10  bid=3497.24996  ask=3500.75004
inventory= -10  bid=3499.24996  ask=3502.75004
```

Ключова поведінка GLFT: коли інвентар **довгий** (+10), обидві котировки зсуваються **вниз** —
щоб частіше продавати й рідше купувати. І навпаки. Саме це робить маркет-мейкінг стійким до тренду.

## 6. Funding cash-and-carry

```python
from datetime import UTC, datetime
from decimal import Decimal

from nautilus_lab.domain.funding import FundingCashAndCarry, FundingParams, FundingSnapshot

strategy = FundingCashAndCarry(
    spot_id="ETH/USDT.SIM",
    perp_id="ETHUSDT-PERP.SIM",
    params=FundingParams(min_net_apy=Decimal("0.10"), taker_fee=Decimal("0.0005")),
)
signal = strategy.on_funding(
    FundingSnapshot(
        instrument="ETHUSDT",
        funding_rate=Decimal("0.002"),     # 0.2% за 8 годин — дуже високий рівень
        mark_price=Decimal("3510"),
        index_price=Decimal("3500"),
        ts_utc=datetime(2025, 1, 1, tzinfo=UTC),
    )
)
print(signal.reason if signal else "немає входу", signal.leg_a.side.value, signal.leg_b.side.value)
```

**Вивід:**

```
funding cash-and-carry buy sell
```

> ### ⚠️ Пастка в параметрах
> Формула входу: `net = funding_rate − 2 × taker_fee`, потім `annualized = net × 3 × 365`.
> Тобто **подвійна комісія віднімається від одного платежу**, і лише потім річнизується.
> З типовими значеннями `taker_fee = 0.0005` (USDⓈ-M) і `min_net_apy = 0.10` поріг виходить
> дуже високим. Реальні перевірки:
>
> | `funding_rate` (за 8 год) | `taker_fee` | `min_net_apy` | Річна нетто | Сигнал |
> |---------------------------|-------------|----------------|-------------|--------|
> | 0.002 (0.20%) | 0.0005 | 0.10 | +109.5% | **вхід** |
> | 0.0005 (0.05%) | 0.0005 | 0.05 | −54.8% | немає |
> | 0.0005 (0.05%) | 0.0001 | 0.05 | +32.9% | **вхід** |
> | 0.0003 (0.03%) | 0.0005 | 0.10 | −76.7% | немає |
>
> Типова ставка фандингу на Binance — 0.01% за 8 годин, тобто `0.0001`. З `taker_fee = 0.0005`
> стратегія не ввійде **ніколи**. Для реалістичних тестів задавайте `taker_fee` як **комісію в
> розрахунку на платіж** (або виправте формулу на `rate × 3 × 365 − round_trip_fees`).
> Це чесний приклад того, як комісії вбивають арбітраж — рівно те, про що попереджає MFT-документ (розділ 7.1).

## 7. Трикутний арбітраж зі своїми курсами

```python
from decimal import Decimal

from nautilus_lab.application.scan_triangular import scan_triangular_opportunities

rates = {
    ("USDT", "BTC"): Decimal("0.00002"),
    ("BTC", "ETH"): Decimal("20"),
    ("ETH", "USDT"): Decimal("4000"),
}
for fee in (Decimal("0"), Decimal("0.001")):
    found = scan_triangular_opportunities(rates, fee=fee)
    print(f"fee={fee}: {len(found)} циклів")
    for item in found[:1]:
        print("   ", " -> ".join(item.cycle), "profit_log =", item.profit_log)
```

**Вивід:**

```
fee=0: 3 циклів
     BTC -> ETH -> USDT -> BTC profit_log = 0.470003629245736
fee=0.001: 3 циклів
     BTC -> ETH -> USDT -> BTC profit_log = 0.4670021282449845
```

`profit_log > 0` означає наявність від'ємного циклу, тобто арбітраж: повний оберт
дає множник `exp(profit_log)` (тут ≈ 1.60 без комісій — «занадто добре, щоб бути правдою»,
бо курси в прикладі вигадані).

Дві практичні деталі:
- Сканер повертає **той самий цикл кілька разів** — по одному на кожну вершину-старт.
  Дедуплікуйте за відсортованим набором валют, якщо потрібен один запис.
- Комісія враховується в кожному ребрі (`rate × (1 − fee)`), тобто тричі на цикл.
  **Глибина книги не перевіряється** — реальність арбітражу визначає саме вона.

## 8. Келлі, VaR, CVaR

```python
from decimal import Decimal

from nautilus_lab.domain.portfolio_risk import fractional_kelly_cap, historical_cvar, historical_var

kelly = fractional_kelly_cap(win_rate=Decimal("0.55"), reward_risk=Decimal("1.5"), fraction=Decimal("0.25"))
print("фракційний Келлі:", kelly)

returns = tuple(Decimal(x) for x in ("-0.031", "-0.012", "-0.004", "0.002", "0.007", "0.011", "-0.02", "0.004", "0.001", "-0.008"))
print("VaR 99%:", historical_var(returns), "CVaR 99%:", historical_cvar(returns))
```

**Вивід:**

```
фракційний Келлі: 0.0625
VaR 99%: 0.031 CVaR 99%: 0.031
```

Розшифровка: повний Келлі = `(0.55 × 1.5 − 0.45) / 1.5 = 0.25`, чверть від нього = **6.25%** ризику
на угоду. Це набагато агресивніше за `RISK_PER_TRADE=0.5%` — і саме тому в проєкті Келлі
використовується як **обмежувач зверху** (`min(risk_per_trade, kelly_cap)`), а не як ціль.

`VaR 99% = 3.1%` означає: у 1% найгірших випадків збиток був ≥3.1% капіталу.

## 9. HAR-RV і масштабування ризику за волатильністю

```python
from decimal import Decimal

from nautilus_lab.domain.volatility import HarRealizedVolatility, vol_scaled_risk_fraction
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_regime_ohlcv

bars = synthetic_regime_ohlcv(instrument_id="ETH/USDT.SIM", count=500, seed=3)
har = HarRealizedVolatility(daily_bars=24, weekly_bars=168, monthly_bars=720)
previous_close = None
forecast = None
for bar in bars:
    forecast = har.update(bar, previous_close)
    previous_close = bar.close

print("прогноз волатильності на бар:", forecast)
print("скоригований ризик:", vol_scaled_risk_fraction(Decimal("0.005"), forecast, Decimal("0.02")))
```

**Вивід:**

```
прогноз волатильності на бар: 0.0002332365675986544230048375916
скоригований ризик: 0.005
```

Функція `vol_scaled_risk_fraction` **ніколи не збільшує** ризик: вона повертає
`min(base, base × target/forecast)`. Тут прогноз (0.00023) менший за цільову волатильність (0.02),
тому ризик лишається базовим 0.5%. Якщо ринок «розігріється» і прогноз перевищить 2% на бар,
ризик пропорційно зменшиться — це і є динамічний ризик-менеджмент із MFT-документа (розділ 6.1).

## 10. EGARCH(1,1) — опційно

```python
from nautilus_lab.infrastructure.egarch_forecast import egarch_forecast_volatility
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_regime_ohlcv

bars = synthetic_regime_ohlcv(instrument_id="ETH/USDT.SIM", count=500, seed=3)
returns = tuple(float((bars[i].close - bars[i - 1].close) / bars[i - 1].close) for i in range(1, len(bars)))
print("EGARCH прогноз σ:", egarch_forecast_volatility(returns))
```

**Вивід:**

```
EGARCH прогноз σ: 0.0697386893007272
```

Потрібен extra `research` (`uv sync --extra research`). Якщо пакета `arch` немає або точок < 60 —
повертає `None` (ніколи не падає). На коротких/синтетичних рядах оптимізатор може видати
`ConvergenceWarning` — це очікувано, значення все одно повертається.

Інші специфікації (GJR-GARCH, GARCH) — це той самий пакет з іншим `vol=`:

```python
from arch import arch_model

model = arch_model(list(returns), vol="GARCH", p=1, o=1, q=1, rescale=False)   # GJR-GARCH
```

## 11. Purged K-fold і розмітка для ML

```python
from decimal import Decimal

from nautilus_lab.application.train_classifier import label_direction, purged_k_fold

folds = purged_k_fold(300, n_splits=5, embargo=10)
for index, fold in enumerate(folds):
    print(f"fold {index}: train={len(fold.train_indices)} test={len(fold.test_indices)}")

print("мітка руху +20 bps:", label_direction(Decimal("0.002")))
print("мітка руху +1 bps:", label_direction(Decimal("0.0001")))
```

**Вивід:**

```
fold 0: train=230 test=60
fold 1: train=240 test=60
fold 2: train=240 test=60
fold 3: train=240 test=60
fold 4: train=230 test=60
мітка руху +20 bps: up
мітка руху +1 bps: flat
```

`embargo=10` означає, що 10 спостережень **до і після** тестового блоку викидаються з тренування —
тому перший і останній фолди мають на 10 точок менше. Поріг розмітки — `threshold_bps=5`.

## 12. Коінтеграція, О-У і Z-оцінка «руками»

```python
from nautilus_lab.domain.pairs.cointegration import fit_cointegration
from nautilus_lab.domain.pairs.ou import fit_ou_half_life, z_score
from nautilus_lab.infrastructure.nautilus.synthetic_pairs import synthetic_cointegrated_pair

data = synthetic_cointegrated_pair(leg_a="ETH/USDT.SIM", leg_b="BTC/USDT.SIM", count=300, seed=7)
y = tuple(bar.close for bar in data["ETH/USDT.SIM"])
x = tuple(bar.close for bar in data["BTC/USDT.SIM"])

coint = fit_cointegration(y, x)
spread = tuple(a - coint.intercept - coint.hedge_ratio * b for a, b in zip(y, x, strict=True))
ou = fit_ou_half_life(spread)

print("hedge ratio:", coint.hedge_ratio)
print("ADF p-value:", coint.adf_pvalue)
print("half-life (барів):", ou.half_life_bars)
print("поточна Z:", z_score(spread[-1], ou.mean, ou.sigma))
```

**Вивід:**

```
hedge ratio: 14.99698674201453994566195137
ADF p-value: 0.50
half-life (барів): 8.478388925230504373881490661
поточна Z: 0.1266129084121439705246271665
```

Тут видно **точно причину**, чому робот `pairs` не торгує: `ADF p-value = 0.50` проти порогу `0.05`.
Half-life при цьому чудовий (8.5 барів — ідеально для MFT), але ворота коінтеграції зачинені.
Це і є той блок, який треба замінити на `statsmodels.coint`
(див. [07 §5](07-yak-stvoryty-strategiyu.md#5-приклад-2-замінити-спрощений-adf-на-справжній)).

## 13. Завантажити свої бари з каталогу

Найкорисніший «клейовий» фрагмент: узяти реальну історію і прогнати її через будь-який модуль.

```python
from pathlib import Path

from nautilus_lab.domain.fees import FeeSchedule
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog

store = NautilusParquetCatalog(Path("catalog"), fees=FeeSchedule.binance_spot_vip0())
bars = store.load(bar_type="BTC/USDT.SIM-1-HOUR-LAST-EXTERNAL")

print("барів:", len(bars))
print("перший:", bars[0].ts_utc, bars[0].close)
print("останній:", bars[-1].ts_utc, bars[-1].close)
```

**Вивід (на цій машині):**

```
барів: 8759
перший: 2025-09-13 10:59:59.999000+00:00 115937.99
останній: 2026-09-13 08:59:59.999000+00:00 76813.71
```

`store.load()` уже валідує кожен бар (`validate_bar`) і кидає `CatalogEmptyError`,
якщо серії немає. Далі ці бари можна передавати в `BarVpin`, `HarRealizedVolatility`,
`fit_cointegration` тощо — саме так будуються власні дослідження без CLI.

Повний цикл «узяти каталог → порахувати метрику → надрукувати» без бектесту:

```python
from decimal import Decimal

from nautilus_lab.domain.vpin import BarVpin

vpin = BarVpin(bucket_volume=Decimal("1500"))
toxic_hours = 0
for bar in bars:
    state = vpin.update(bar)
    if state is not None and state.toxic:
        toxic_hours += 1
print("токсичних кошиків:", toxic_hours)
```

**Вивід** (та сама серія BTC/USDT з прикладу вище, 8759 барів):

```
токсичних кошиків: 3041
```

## 14. Швидка довідка «що де лежить»

| Потрібно | Імпорт |
|----------|--------|
| VPIN на барах | `from nautilus_lab.domain.vpin import BarVpin` |
| Хоукс | `from nautilus_lab.domain.hawkes import ExponentialHawkes` |
| OBI / WOFI / Fade | `from nautilus_lab.domain.microstructure import ...` |
| Знімок книги | `from nautilus_lab.domain.order_book import BookLevel, OrderBookSnapshot` |
| ML за книгою | `from nautilus_lab.domain.ml_obi_strategy import MlObiStrategy` |
| Класифікатори | `from nautilus_lab.infrastructure.lightgbm_classifier import ...` |
| GLFT | `from nautilus_lab.domain.glft import GlftMarketMaker, GlftParams` |
| Funding | `from nautilus_lab.domain.funding import FundingCashAndCarry, FundingParams, FundingSnapshot` |
| Трикутний арбітраж | `from nautilus_lab.domain.triangular_arb import FxEdge, find_negative_cycles` |
| Сканер циклів | `from nautilus_lab.application.scan_triangular import scan_triangular_opportunities` |
| Келлі / VaR | `from nautilus_lab.domain.portfolio_risk import fractional_kelly_cap, historical_var, historical_cvar` |
| HAR-RV | `from nautilus_lab.domain.volatility import HarRealizedVolatility, vol_scaled_risk_fraction` |
| EGARCH | `from nautilus_lab.infrastructure.egarch_forecast import egarch_forecast_volatility` |
| Purged K-fold | `from nautilus_lab.application.train_classifier import purged_k_fold, label_direction` |
| Коінтеграція / О-У | `from nautilus_lab.domain.pairs.cointegration import fit_cointegration` та `from nautilus_lab.domain.pairs.ou import fit_ou_half_life, z_score` |
| Каталог | `from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog` |
| Синтетика | `from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_ohlcv, synthetic_regime_ohlcv` |

## 15. Куди йти далі

- Підключити будь-який з цих модулів до бектесту → [07-yak-stvoryty-strategiyu.md](07-yak-stvoryty-strategiyu.md)
- Зрозуміти, чому модуль саме такий → [08-mft-2026-vidpovidnist.md](08-mft-2026-vidpovidnist.md)
