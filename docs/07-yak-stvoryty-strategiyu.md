# 07. Як створити свою стратегію

Покроковий посібник: від ідеї до власного робота, який працює через `lab research`.
Усі фрагменти коду в цьому документі **перевірені** — вони компілюються, тести проходять,
а робот реально генерує сигнали на синтетичних барах.

---

## 1. Сім правил, які не можна порушувати

Порушення будь-якого з них робить результати безглуздими, навіть якщо код «працює».

| # | Правило | Чому |
|---|---------|------|
| 1 | **Домен не знає про Nautilus, мережу, `.env`** | Інакше логіку не можна протестувати швидко, а заміна біржі ламає стратегію |
| 2 | **Стратегія повертає лише напрямок, без розміру** | Розмір рахує ризик-шар. Інакше підбір параметрів «підтягне» ризик під історію |
| 3 | **Тільки закриті бари** | Використання поточного бару в максимумі/мінімумі = підгляд у майбутнє |
| 4 | **`Decimal`, не `float`** | Гроші та ціни; float дає похибку в розрахунках позиції |
| 5 | **Валідуй вхідні дані** | `validate_bar()` ловить перевернуті свічки, дублікати часу, бари з майбутнього |
| 6 | **Тести без мережі** | Unit-тест має виконуватися за мілісекунди на згенерованих барах |
| 7 | **Живий режим не чіпаємо** | Жодного коду, який надсилає реальні ордери |

Ще одне, менш очевидне: **не підбирайте параметри, дивлячись на out-of-sample**. Якщо ви
запустили walk-forward, побачили поганий OOS, змінили параметри й запустили знову —
OOS більше не out-of-sample. Він став частиною підбору.

## 2. Карта змін: куди саме додавати код

| Файл | Що зробити | Обов'язково? |
|------|------------|--------------|
| `domain/<ваш_робот>.py` | Новий клас стратегії | ✅ так |
| `domain/regime.py` | Додати назву в `RobotName` **і** в `BACKTEST_WIRED_ROBOTS` | ✅ так (перше відкриває робота для CLI, друге — для рушія: без нього `require_backtest_support()` відмовиться запускати) |
| `specs/strategies/<ваш_робот>.yaml` | Специфікація робота (пишеться **до** коду) | ✅ так — `tests/unit/test_specs.py` падає, доки її немає |
| `infrastructure/nautilus/signal_strategy.py` | Гілка в `_build_robot()` + поля в `SignalRobotConfig` | ✅ так |
| `tests/unit/test_<ваш_робот>.py` | Юніт-тести | ✅ так |
| `application/param_grid.py` | Гілка сітки параметрів | ⚙️ якщо хочете підбір (інакше спрацює сітка `regime` — марно) |
| `application/dtos.py` | Поля в `BacktestRequest` і `SelectedParams` | ⚙️ якщо додаєте **нові** параметри для оптимізації |
| `infrastructure/settings.py` + `.env.example` | Нові змінні | ⚙️ якщо хочете керувати з `.env` |
| `interfaces/composition.py` | Прокинути налаштування з `Settings` у `BacktestRequest` | ⚙️ якщо додали поля в `BacktestRequest` |
| `application/run_research_backtest.py` | Мінімум барів у `minimum_bars()` | ⚙️ якщо ваш робот потребує довгого прогріву |

CLI-прапорці `--robot` оновляться **автоматично**: у `cli.py` список береться з `RobotName`.

## 3. Крок за кроком: робот `vpin_momentum`

> **Приклад уже в репозиторії.** `vpin_momentum` — не гіпотетична вправа: файл
> `src/nautilus_lab/domain/vpin_momentum.py` існує, назва є в `RobotName` і в
> `BACKTEST_WIRED_ROBOTS`, сітка для нього — у `param_grid.py`, специфікація — у
> `specs/strategies/vpin_momentum.yaml`. Тож кроки нижче читайте як **шаблон для вашого
> нового робота** (і як розбір того, як цей робот зроблено): підставляйте свої імена, а
> фрагменти, які вже є в коді, — звіряйте з реальними файлами, а не переписуйте.

Ідея (прямо з MFT-документа, розділ 1.2): коли VPIN фіксує токсичний потік, на ринку працює
інформований гравець; старі рівні підтримки/опору будуть пробиті, тому треба йти **за** потоком.
Використаємо три готові блоки: `BarVpin`, `EMA`, `ATR`.

Правило трьома реченнями (це і є специфікація):
1. **Вхід:** VPIN-кошик токсичний (≥ порогу) і ціна вище EMA → лонг; ціна нижче EMA → шорт.
2. **Вихід:** ціна втратила EMA (втрата імпульсу) або спрацював трейлінг-стоп `ATR × 2`.
3. **Фільтр:** поки індикатори не прогрілися — нічого не робимо.

### Крок 1: чистий клас домену

Створіть `src/nautilus_lab/domain/vpin_momentum.py`:

```python
from __future__ import annotations

from decimal import Decimal

from nautilus_lab.domain.atr import AverageTrueRange
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.ema import ExponentialMovingAverage
from nautilus_lab.domain.signals import Signal, SignalSide
from nautilus_lab.domain.vpin import BarVpin


class VpinMomentum:
    """Momentum in the direction of informed (toxic) order flow, ATR trailing stop."""

    def __init__(
        self,
        *,
        instrument_id: str,
        bucket_volume: Decimal = Decimal("1000"),
        toxic_threshold: Decimal = Decimal("0.7"),
        ema_period: int = 50,
        atr_period: int = 14,
        atr_multiple: Decimal = Decimal("2"),
        min_hold_bars: int = 3,
    ) -> None:
        if ema_period < 2:
            raise ValueError("ema_period must be >= 2")
        if atr_period < 1:
            raise ValueError("atr_period must be >= 1")
        if atr_multiple <= 0:
            raise ValueError("atr_multiple must be > 0")
        if min_hold_bars < 0:
            raise ValueError("min_hold_bars must be >= 0")
        self._instrument_id = instrument_id
        self._vpin = BarVpin(bucket_volume=bucket_volume, toxic_threshold=toxic_threshold)
        self._ema = ExponentialMovingAverage(ema_period)
        self._atr = AverageTrueRange(atr_period)
        self._atr_multiple = atr_multiple
        self._min_hold_bars = min_hold_bars
        self._direction = 0
        self._bars_in_position = 0
        self._extreme = Decimal("0")

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        state = self._vpin.update(bar)
        self._ema.update(bar.close)
        self._atr.update(bar)
        ema = self._ema.value
        atr = self._atr.value
        if ema is None or atr is None:
            return None

        if self._direction != 0:
            self._bars_in_position += 1
            self._extreme = (
                max(self._extreme, bar.high) if self._direction > 0 else min(self._extreme, bar.low)
            )
            stop = (
                self._extreme - self._atr_multiple * atr
                if self._direction > 0
                else self._extreme + self._atr_multiple * atr
            )
            hit_stop = bar.close <= stop if self._direction > 0 else bar.close >= stop
            lost_momentum = bar.close < ema if self._direction > 0 else bar.close > ema
            can_exit = self._bars_in_position >= self._min_hold_bars
            if can_exit and (hit_stop or lost_momentum):
                self._reset()
                return self._signal(
                    bar, SignalSide.FLAT, "vpin momentum exit" if lost_momentum else "vpin atr stop"
                )
            return None

        if state is None or not state.toxic:
            return None
        if bar.close > ema:
            self._enter(direction=1, bar=bar)
            return self._signal(bar, SignalSide.BUY, f"toxic flow up vpin={state.value}")
        if bar.close < ema:
            self._enter(direction=-1, bar=bar)
            return self._signal(bar, SignalSide.SELL, f"toxic flow down vpin={state.value}")
        return None

    @property
    def regimes_ready(self) -> bool:
        return self._ema.initialized and self._atr.initialized

    def _enter(self, *, direction: int, bar: OhlcvBar) -> None:
        self._direction = direction
        self._bars_in_position = 0
        self._extreme = bar.high if direction > 0 else bar.low

    def _reset(self) -> None:
        self._direction = 0
        self._bars_in_position = 0
        self._extreme = Decimal("0")

    def _signal(self, bar: OhlcvBar, side: SignalSide, reason: str) -> Signal:
        return Signal(
            instrument_id=self._instrument_id,
            side=side,
            bar_ts_utc=bar.ts_utc,
            reason=reason,
        )
```

Зверніть увагу: жодного `import nautilus_trader`, жодного читання `.env`, жодного ордера.
Клас лише зберігає стан і повертає `Signal`.

> **Одна відмінність від файлу в репозиторії.** У `domain/vpin_momentum.py` модель потоку не
> створюється всередині, а **впорскується**: `def __init__(self, *, instrument_id: str,
> vpin: VpinModel, ema_period: int = 50, ...)`. Це дозволяє тому самому класу працювати і на
> барах (`BarVpin`), і на окремих угодах (`TickVpin`) — саме так працює прапорець
> `--tick-vpin`. Разом із цим у класі є метод `on_trade_tick(*, is_buy, volume, dt_seconds)`,
> який прокидає тік у `vpin.update_from_trade(...)`.

### Крок 2: юніт-тести

Створіть `tests/unit/test_vpin_momentum.py`:

```python
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.signals import SignalSide
from nautilus_lab.domain.vpin_momentum import VpinMomentum


def _bars(closes: list[str]) -> list[OhlcvBar]:
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        OhlcvBar(
            instrument_id="ETH/USDT.SIM",
            ts_utc=origin + timedelta(hours=index),
            open=Decimal(close),
            high=Decimal(close) + Decimal("1"),
            low=Decimal(close) - Decimal("1"),
            close=Decimal(close),
            volume=Decimal("100"),
        )
        for index, close in enumerate(closes)
    ]


def test_no_signal_while_indicators_warm_up() -> None:
    robot = VpinMomentum(
        instrument_id="ETH/USDT.SIM",
        bucket_volume=Decimal("100"),
        toxic_threshold=Decimal("0.6"),
        ema_period=5,
        atr_period=3,
    )
    bars = _bars(["100", "101"])
    assert [robot.on_bar(bar) for bar in bars] == [None, None]


def test_enters_long_on_toxic_upward_flow() -> None:
    robot = VpinMomentum(
        instrument_id="ETH/USDT.SIM",
        bucket_volume=Decimal("100"),
        toxic_threshold=Decimal("0.6"),
        ema_period=2,
        atr_period=1,
        min_hold_bars=0,
    )
    signals = [robot.on_bar(bar) for bar in _bars(["100", "101", "102", "103", "104"])]
    sides = [signal.side for signal in signals if signal is not None]
    assert SignalSide.BUY in sides


def test_exits_when_price_loses_the_ema() -> None:
    robot = VpinMomentum(
        instrument_id="ETH/USDT.SIM",
        bucket_volume=Decimal("100"),
        toxic_threshold=Decimal("0.6"),
        ema_period=2,
        atr_period=1,
        min_hold_bars=0,
    )
    sides = []
    for bar in _bars(["100", "110", "120", "130", "100", "90"]):
        signal = robot.on_bar(bar)
        if signal is not None:
            sides.append(signal.side)
    assert SignalSide.FLAT in sides
```

Перевірка (ці три тести реально проходять):

```bash
.venv/bin/pytest tests/unit/test_vpin_momentum.py -q
...
3 passed
```

Принципи тестування тут прості: бари будуються **вручну** (жодної мережі), тестується
по одному правилу за раз, і перевіряється не «прибутковість», а **поведінка** —
прогрів, поява входу, поява виходу.

### Крок 3: реєстрація робота

`src/nautilus_lab/domain/regime.py` — додайте рядок у `RobotName` (тут показано повний перелік
на сьогодні, ваш робот стане дванадцятим):

```python
class RobotName(StrEnum):
    REGIME = "regime"
    EMA = "ema"
    PAIRS = "pairs"
    VPIN_MOMENTUM = "vpin_momentum"
    FORMULAIC_LGBM = "formulaic_lgbm"
    META_LABEL = "meta_label"
    ADAPTIVE_EMA = "adaptive_ema"
    FUNDING = "funding"
    ML_OBI = "ml_obi"
    GLFT = "glft"
    TRI_SCAN = "tri_scan"
    YOUR_ROBOT = "your_robot"  # <-- додано
```

І **обов'язково** — у `BACKTEST_WIRED_ROBOTS` у тому ж файлі:

```python
BACKTEST_WIRED_ROBOTS: frozenset[RobotName] = frozenset(
    {
        RobotName.REGIME,
        # ... решта підключених роботів ...
        RobotName.YOUR_ROBOT,  # <-- додано
    }
)
```

Без другого кроку `require_backtest_support(robot)` кидає `robot 'your_robot' has no backtest
adapter yet; use one of: ...`, і жоден прогін не відбудеться — це fail closed за задумом.

Після цього `uv run lab research --help` покаже нову опцію в `--robot` без жодних правок у CLI
(і в `lab paper --robot` теж, якщо робот є в `PAPER_SUPPORTED_ROBOTS`).

### Крок 4: підключення до рушія

`src/nautilus_lab/infrastructure/nautilus/signal_strategy.py`.

а) Додайте поля в `SignalRobotConfig` (усі поля мають значення за замовчуванням):

```python
class SignalRobotConfig(StrategyConfig, frozen=True):
    ...
    vpin_momentum_ema_period: int = 50
    vpin_momentum_atr_multiple: Decimal = Decimal("2")
```

б) Додайте гілку в `_build_robot()`. Тип повернення вже узагальнено до протоколу
`SingleLegRobot` (оголошений у тому самому файлі, `infrastructure/nautilus/signal_strategy.py`),
тож розширювати union не потрібно:

```python
from nautilus_lab.domain.vpin_momentum import VpinMomentum


def _build_robot(config: SignalRobotConfig) -> SingleLegRobot:
    robot = RobotName(config.robot)
    require_backtest_support(robot)
    instrument_id = str(config.instrument_id)
    if robot is RobotName.EMA:
        return EmaCrossover(...)  # як було
    if robot is RobotName.VPIN_MOMENTUM:
        vpin: VpinModel = (
            TickVpin(
                bucket_volume=config.vpin_bucket_volume,
                toxic_threshold=config.vpin_toxic_threshold,
            )
            if config.use_tick_vpin
            else BarVpin(
                bucket_volume=config.vpin_bucket_volume,
                toxic_threshold=config.vpin_toxic_threshold,
            )
        )
        return VpinMomentum(
            instrument_id=instrument_id,
            vpin=vpin,
            ema_period=config.vpin_momentum_ema_period,
            atr_multiple=config.vpin_momentum_atr_multiple,
        )
    ...  # гілка RegimeRouter як була
```

> **Протокол `SingleLegRobot` уже є.** Він оголошений у
> `infrastructure/nautilus/signal_strategy.py` (не в `domain/ports.py`): саме тому
> `_build_robot` повертає `SingleLegRobot`, і будь-яка нова стратегія з одним інструментом
> підходить автоматично — розширювати union-тип не потрібно.

в) `src/nautilus_lab/infrastructure/nautilus/backtest_runner.py` — прокидаємо налаштування у конфіг
(у виклику `SignalRobotConfig(...)` у методі `run`):

```python
SignalRobotConfig(
    ...,
    vpin_bucket_volume=request.vpin_bucket_volume,
    vpin_toxic_threshold=request.vpin_toxic_threshold,
    vpin_momentum_ema_period=request.vpin_momentum_ema_period,  # <-- додано
    vpin_momentum_atr_multiple=request.vpin_momentum_atr_multiple,  # <-- додано
)
```

### Крок 5: запуск (мінімальний шлях)

Якщо ви не додавали нових полів у `BacktestRequest`, робот уже готовий до запуску —
керуйте ним через **уже наявні** змінні `VPIN_BUCKET_VOLUME` і `VPIN_TOXIC_THRESHOLD`:

```bash
uv run lab research --robot vpin_momentum --synthetic --bars 3000
uv run lab research --robot vpin_momentum
```

Але є дві прогалини, які варто закрити:

> **Якщо ви користуєтесь лише `--optuna`,** проблема нижче менш критична: `OptunaParamOptimizer`
> має **власний** простір пошуку (і для невідомих роботів використовує гілку `regime`:
> `donchian`, `bb_period`, `bb_k`, `enter_trend_er`, `exit_trend_er`). Але якщо ваш робот цих параметрів
> не читає, Optuna марно витратить trials на однакові прогони. Тому або додайте гілку в оптимізатор,
> або запускайте з `--trials 1` після ручного вибору параметрів.

**Прогалина 1 — сітка параметрів.** `iter_param_grid()` для невідомого робота віддає сітку `regime`
(6 комбінацій `donchian × bb_k`), які ваш робот просто ігнорує: 6 прогонів на in-sample дадуть
однаковий результат, тобто витрачений час. Додайте власну гілку в `application/param_grid.py`.
Для `vpin_momentum` вона вже така (і поле `vpin_ema_period` у `SelectedParams` теж уже існує):

```python
if request.robot is RobotName.VPIN_MOMENTUM:
    for ema_period in (30, 50, 80):
        yield SelectedParams(
            fast_ema=base.fast_ema,
            slow_ema=base.slow_ema,
            donchian_period=base.donchian_period,
            bb_period=base.bb_period,
            bb_k=base.bb_k,
            enter_trend_er=base.enter_trend_er,
            exit_trend_er=base.exit_trend_er,
            z_entry=base.z_entry,
            z_exit=base.z_exit,
            vpin_ema_period=ema_period,
            vpin_atr_multiple=base.vpin_atr_multiple,
        )
    return
```

**Прогалина 2 — мінімум барів.** `application/run_research_backtest.py::minimum_bars()` (його ж
викликає `application/run_walk_forward.py::_require_warmup()`) дає для невідомих роботів **50**
барів. Вашому роботу з `ema_period=50` потрібно ~50 барів лише на прогрів. Якщо фолд має рівно
50 барів, сигналів не буде взагалі. Варіанти: зменшити `ema_period`, або додати робота в гілку з
150 барами — саме так зроблено для `vpin_momentum`:

```python
def minimum_bars(robot: RobotName) -> int:
    if robot in (
        RobotName.REGIME,
        RobotName.VPIN_MOMENTUM,
        RobotName.META_LABEL,
        RobotName.ADAPTIVE_EMA,
    ):
        return 150
    if robot is RobotName.PAIRS:
        return 200
    if robot is RobotName.FORMULAIC_LGBM:
        return 80
    return 50
```

### Крок 6: повний шлях — нові параметри, якими керує `.env`

Якщо хочете оптимізувати `ema_period` і `atr_multiple` через walk-forward і задавати їх у `.env`,
потрібні зміни в **п'яти** місцях (це типовий ланцюг для будь-якого нового параметра):

1. **`infrastructure/settings.py`** — поля `Settings`:

```python
    vpin_momentum_ema_period: int = 50
    vpin_momentum_atr_multiple: Decimal = Decimal("2")
```

2. **`.env.example`** (і ваш `.env`) — однойменні змінні у верхньому регістрі:

```dotenv
# VPIN momentum robot
VPIN_MOMENTUM_EMA_PERIOD=50
VPIN_MOMENTUM_ATR_MULTIPLE=2
```

3. **`application/dtos.py`** — поля в `BacktestRequest`, у `SelectedParams`,
   а також у `selected_from_request()` і `apply_selected()`:

```python
@dataclass(frozen=True, slots=True)
class BacktestRequest:
    ...
    vpin_momentum_ema_period: int = 50
    vpin_momentum_atr_multiple: Decimal = Decimal("2")


@dataclass(frozen=True, slots=True)
class SelectedParams:
    ...
    vpin_ema_period: int = 50
    vpin_atr_multiple: Decimal = Decimal("2")


def selected_from_request(request: BacktestRequest) -> SelectedParams:
    return SelectedParams(
        ...,
        vpin_ema_period=request.vpin_momentum_ema_period,
        vpin_atr_multiple=request.vpin_momentum_atr_multiple,
    )


def apply_selected(request: BacktestRequest, params: SelectedParams) -> BacktestRequest:
    return replace(
        request,
        ...,
        vpin_momentum_ema_period=params.vpin_ema_period,
        vpin_momentum_atr_multiple=params.vpin_atr_multiple,
    )
```

4. **`interfaces/composition.py`** — `research_request()` передає значення з `Settings`:

```python
BacktestRequest(
    ...,
    vpin_momentum_ema_period=cfg.vpin_momentum_ema_period,
    vpin_momentum_atr_multiple=cfg.vpin_momentum_atr_multiple,
)
```

5. **`infrastructure/nautilus/backtest_runner.py`** — як у кроці 4в.

Після цього працює все: `.env` → сітка → walk-forward → рушій → ваш робот.

### Крок 7: прогон повного циклу

```bash
uv run pytest tests/unit/test_vpin_momentum.py -q      # 1. тести
uv run ruff check --fix && uv run ruff format          # 2. стиль
uv run mypy src tests                                  # 3. типи
uv run lab research --robot vpin_momentum --synthetic --bars 3000   # 4. smoke
uv run lab research --robot vpin_momentum              # 5. walk-forward
uv run lab research --robot vpin_momentum --is-fraction 0.5 --embargo-bars 0   # 6. чутливість
uv run lab research --robot vpin_momentum --slice ftx2022 --catalog catalog_long  # 7. стрес
```

Крок 5 — це і є результат. Кроки 1–4 лише перевіряють, що код не зламаний.

---

## 4. Як вибрати ідею з MFT-документа

| Розділ «Стратегії MFT 2026» | Готові блоки в коді | Що дописати для робота | Складність |
|------------------------------|---------------------|-------------------------|------------|
| 1.1 Хоукс (кластеризація потоку ордерів) | `domain/hawkes.py::ExponentialHawkes`, фільтр `--hawkes` у `RegimeRouter` | Саму стратегію «розширити спред / піти за потоком»; тіки вже заливаються (`lab ingest --trades`) | 🟠 середньо |
| 1.2 VPIN / токсичний потік | `domain/vpin.py::BarVpin` і `TickVpin`, робот `vpin_momentum`, фільтри `--bar-vpin` / `--tick-vpin` у `RegimeRouter` | Нічого — робот підключено до рушія (див. приклад вище і `specs/strategies/vpin_momentum.yaml`) | ✅ готово |
| 2.1 LightGBM + OBI | `ml_obi_strategy.py`, `ml_classifier.py`, `lightgbm_classifier.py`, `microstructure.py` | Нічого критичного: L2 збирається (`lab ingest --depth`), модель навчається (`lab ml train --model-type obi`), робот `ml_obi` підключено до рушія | 🟠 середньо: якість даних і моделі |
| 2.2 Purged K-fold, PBO | `application/train_classifier.py::purged_k_fold`, `label_direction`; `lab ml train`; `lab research --pbo` (PBO + deflated Sharpe) | Нічого — обвʼязка й аудит уже є | ✅ готово |
| 3.1–3.3 Pairs trading | `pairs/cointegration.py`, `pairs/ou.py`, `pairs/pairs_trading.py` | Спрощений ADF **уже замінено** на справжній (див. §5); лишилось — динамічний хедж-коефіцієнт | 🟠 середньо |
| 4.1 GLFT маркет-мейкінг | `domain/glft.py::GlftMarketMaker` | Модель черги лімітних ордерів + облік інвентарю в бектесті | 🔴 складно |
| 4.2 DRL | — | Усе: середовище, агент, симулятор книги | 🔴 дуже складно |
| 5.1 Funding arbitrage | `domain/funding.py`, `infrastructure/binance_funding.py`, `lab ingest --funding` | Завантаження фандингу **уже є** (тека `catalog/data/funding/`); лишається подієва стратегія (не бари) | 🟠 середньо |
| 5.2 Трикутний арбітраж | `domain/triangular_arb.py`, `application/scan_triangular.py` | Дані стакану/глибини (знімки L2 уже збирає `lab ingest --depth`), оцінка прослизання | 🟠 середньо |
| 6.1 Волатильність (HAR-RV, EGARCH) | `domain/volatility.py`, `infrastructure/egarch_forecast.py` | Нічого — `vol_scaled_risk_fraction` підключено в ризик-шар (`USE_VOL_SCALING`, `VOL_MODEL`) | ✅ готово |
| 6.2 Келлі / VaR | `domain/portfolio_risk.py`, `application/risk.py` | Нічого — статистику угод передає `SignalRobot` (`USE_FRACTIONAL_KELLY`, `KELLY_MIN_TRADES`) | ✅ готово |
| 7. Комісії / інфраструктура | `domain/fees.py`, `MAKER_FEE`/`TAKER_FEE` | Нічого — вже враховано | ✅ готово |
| 8. Податки | — | Поза кодом (облік операцій для звітності — окрема задача) | ⚪ не в скоупі |

**Порада для початківця:** почніть з 🟢-рядків. Вони дають закінченого робота за вечір
і не потребують даних, яких у проєкті немає.

---

## 5. Приклад 2: замінити спрощений ADF на справжній

У цьому репозиторії роботу **вже зроблено** — і саме тому розділ варто прочитати: він показує, як
зробити статистичні ворота правильними й **довести** це проти еталонної реалізації. Це розбір
реального баґу, а не рецепт «додайте ще одну бібліотеку».

### Що було зламано

`domain/pairs/cointegration.py` рахував ADF на залишках коінтеграції так: регресія `Δresidual`
на `residual[−1]`, після чого з жорстко зашитими межами порівнювався **сирий коефіцієнт** цієї
регресії:

| Умова на `gamma` | p-value, що повертався |
|------------------|------------------------|
| `gamma < −3.5` | 0.01 |
| `gamma < −2.9` | 0.05 |
| `gamma < −2.0` | 0.10 |
| інакше | 0.50 |

Ні t-статистики, ні таблиць МакКіннона тут немає — і це не дрібниця. Для AR(1)-ряду
`gamma = rho − 1`, а `rho ∈ (−1, 1)` для **будь-якого** стаціонарного ряду. Отже `gamma`
математично замкнений у `(−2, 0)`, і межа `gamma < −2.9` **недосяжна за жодних вхідних даних**.
Найгірший можливий результат — гілка `else`, тобто `p-value = 0.50`.

Наслідок був не «суворі ворота», а мертві ворота: `PairsTrading._fit_state()` завжди повертав
`None`, тому робот `pairs` не торгував **ніколи** — кожен прогін друкував `fills=0`,
`ending=100000.00` і той самий `p-value = 0.50`. Важливо: `0.50` — це вивід самого баґу (остання
гілка зашитої логіки), а **не** доказ, що ETH/BTC не пройшли справжню статистичну перевірку
(див. [05 §3.4](05-roboty.md#34-ворота-якості-чому-робот-може-не-торгувати-взагалі)).

### Чому це не спливло одразу

У сусідньому тесті (`tests/unit/test_mft_modules.py`) стояв тавтологічний `assert`:

```python
    # було (тепер прибрано) — цей assert не міг не виконатися:
    signals = 0
    ...
    assert signals >= 0
```

Такий `assert` не перевіряє нічого: він істинний і для робота, який не торгує ніколи. Тест
виглядав як покриття, а насправді маскував недосяжні ворота. Справжня перевірка тут — `signals > 0`.

> **Правило, яке варто забрати з цієї історії.** Ворота, які неможливо **відкрити**, і ворота, які
> неможливо **закрити**, — однаково небезпечні. Перші дають нуль угод (легко помітити), другі —
> гарні результати (помітити важко). Тому ворота треба перевіряти з **обох** боків: тест на
> коінтегрованій парі (мусить пропустити) і тест на двох незалежних random walk (мусить відмовити).

### Як це працює тепер

- Статистика — **t-відношення** коефіцієнта при `e_{t−1}` в ADF-регресії, а не сам коефіцієнт.
- Порядок лагів обирається за **BIC** у межах `0..p_max` (правило Шверта) на **спільній вибірці**:
  усі кандидати рахуються на тих самих рядках, після чого переможний лаг перефітовується на своїй
  максимальній вибірці, і саме його статистика йде у звіт.
- p-value береться з квантилів **МакКіннона (2010)** для `N = 2` змінних і `regression="c"`
  (константа в коінтегруючій регресії, без тренду) з поправкою на скінченну вибірку — тому
  в 5%-точці p-value дорівнює рівно `0.05`, і поріг `adf_pvalue_max = 0.05` має точний зміст.
- `N = 2` — бо `statsmodels.coint()` рахує **змінні** (`k_vars = y1.shape[1] + 1`), а не регресори.
- Публічні символи модуля: `fit_cointegration()`, `critical_values(nobs)` (три межі — 1%, 5%, 10%)
  і `p_value_from_statistic(t_statistic, nobs)`; `CointegrationResult` отримав поле `adf_lags`.

### Чому нативно в домені, а не `statsmodels` у рантаймі

Спокуса розв'язати це одним рядком (`from statsmodels.tsa.stattools import coint`) зрозуміла, але
вибір у проєкті інший:

| Варіант | Що за це платимо |
|---------|------------------|
| `statsmodels.coint` у домені | `float` на межі домену (порушує правило 4 з §1) + ще одна важка рантайм-залежність |
| Нативна реалізація на `Decimal` | Квантили МакКіннона треба перенести самому — зате домен лишається чистим |

Обрано другий варіант: `statsmodels` **не** є рантайм-залежністю і використовується лише як
**еталон у тестах**. Це та сама схема «зроби сам, але доведи проти референсу».

### Як довести, що ворота правильні

Одна перевірка «на око» тут нічого не варта — потрібне порівняння з еталоном на багатьох рядах:

- t-статистики й вибір лагу збіглися з `adfuller(..., regression='n', autolag='bic')` на **48 з 48**
  засіяних рядів (максимальна розбіжність ~1e-15);
- `critical_values(nobs)` відтворює `mackinnoncrit(N=2, regression='c', nobs=T)` з розбіжністю
  0.0 / 4.44e-16 для `T = 40..2000`;
- `fit_cointegration` збігся з `coint(y, x, trend='c', autolag='bic')` до 2.8e-07.

Плюс тести, яких раніше бракувало (`tests/unit/test_cointegration.py`): коінтегрована пара мусить
пройти 5%-поріг, два незалежні random walk — **не** пройти, а p-value в 5%-точці мусить дорівнювати
рівно `0.05`.

### Що це дало роботу `pairs`

Робот **тепер торгує**. Свіжий walk-forward на поточному каталозі (IS 2024-01-01 … 2025-11-22,
OOS 2025-11-22 … 2026-09-14, стартовий капітал 100 000):

```
IS  fills=204 ending=99613.88    (−0.39%)
OOS fills=300 ending=98958.10    (−1.04%)
```

Скажімо прямо: це означає, що **ворота працюють**, і більше нічого. Результат трохи **від'ємний
на обох вибірках**, тобто переваги не видно: 204 і 300 угод із мінусом — це «стратегію нарешті
видно», а не «стратегія заробляє». Не читайте `fills > 0` як успіх.

Перевірити в себе:

```bash
uv run pytest tests/unit/test_cointegration.py -q      # ворота з обох боків
uv run lab research --robot pairs                      # fills мають бути > 0
```

Наступний крок за якістю — не послаблювати поріг, а **переоцінювати коінтеграцію** періодично:
зараз β фіксується один раз (`PAIRS_REFIT_EVERY=0`), але сам механізм переоцінки в коді вже є —
`N > 0` перераховує коінтеграцію раз на N барів і закриває позицію, коли пара перестала
проходити ворота (див. [05 §3.4](05-roboty.md#34-ворота-якості-чому-робот-може-не-торгувати-взагалі)).

## 6. Приклад 3: Келлі та vol-scaling — уже підключено

Обидва блоки не просто написані, а **вже вбудовані** в `SignalRobot`; типово вони вимкнені
прапорцями в `.env`. Тому цей розділ — не рецепт «як дописати», а розбір того, як воно працює
і як його ввімкнути.

Келлі: `SignalRobot` сам накопичує `TradeStats` (`application/risk.py`) —
`on_position_closed()` викликає `record(realized)`, — і передає статистику в розрахунок розміру:

```python
risk_fraction = resolve_risk_fraction(
    self._limits,
    self._overlay,
    stats=self._trade_stats,
    forecast_vol=self._last_vol_forecast,
)
```

Щоб це впливало на розмір, потрібні `USE_FRACTIONAL_KELLY=true` (і, за потреби,
`KELLY_MIN_TRADES`, типово 30) — гілка `resolve_risk_fraction` викликає
`effective_risk_fraction(limits, win_rate=..., reward_risk=...)`, яка повертає
`min(risk_per_trade, kelly_cap)`. Ефект: коли статистика показує відсутність переваги,
`fractional_kelly_cap` повертає 0, і розмір лишається на `RISK_PER_TRADE` — робот не збільшує
ставку на слабкому сигналі.

Vol-scaling: `USE_VOL_SCALING=true` + `VOL_MODEL` (`har` / `egarch` / `gjr_garch`) і
`VOL_SCALING_TARGET` (`0.02` — це і є ті 2% на бар). Прогноз приходить із
`vol_forecast.build_vol_forecaster(...)`, а `vol_scaled_risk_fraction(base, forecast_vol,
target_vol)` домножує ризик — і **ніколи не збільшує** його вище базового.

---

## 7. Антипатерни: так робити не можна

| Антипатерн | Що станеться | Як правильно |
|------------|--------------|--------------|
| Рахувати кількість лотів у стратегії | Підбір параметрів підтягне ризик; walk-forward збреше | Повертайте `Signal`, розмір — у `size_position` |
| Використовувати `float` для цін | Похибка в розрахунку позиції, тести «плавають» | `Decimal` всюди в домені |
| Брати максимум **включно** з поточним баром | Look-ahead: у бектесті «бачите» майбутнє | `RollingWindow.prior()` — усі значення, крім щойно закритого |
| Читати `.env` у домені | Логіку не можна тестувати; неявні залежності | Параметри передаються в конструктор |
| Додати 40 параметрів у сітку | PBO: ідеальний in-sample і збитковий OOS | Маленька сітка (3–6), або purged K-fold |
| Підбирати параметри, дивлячись на OOS | OOS перестає бути OOS | OOS дивляться один раз; для вибору — окрема validation-частина |
| Ринковий ордер на кожному барі | Комісії з'їдять усе | Додайте фільтр/порог, або лімітні ордери |
| Торгувати «в лоб» без ризик-шару | Один поганий день = кінець рахунку | `evaluate_entry` перед кожним входом |
| Вважати синтетичний результат результатом | Синтетика дає +3000% артефакту | Синтетика — лише smoke-тест |

## 8. Чекліст перед першим walk-forward вашої стратегії

- [ ] Клас у `domain/`, без імпортів Nautilus і без `.env`
- [ ] `Signal` не містить розміру позиції
- [ ] Використовуються лише закриті бари (`prior()`, а не «останній включно»)
- [ ] Є юніт-тести на прогрів, на вхід і на вихід
- [ ] Назва додана в `RobotName` **і** в `BACKTEST_WIRED_ROBOTS`
- [ ] Специфікація `specs/strategies/<робот>.yaml` збігається з кодом (`.venv/bin/python specs/_validator.py`)
- [ ] `_build_robot()` знає про новий робот
- [ ] `iter_param_grid()` має власну гілку (або свідомо прийнято, що сітка буде `regime`)
- [ ] `minimum_bars()` / `_require_warmup()` враховують довжину прогріву
- [ ] `uv run pytest && uv run ruff check && uv run mypy src tests` — чисто
- [ ] Прогін на синтетиці дає ненульові `fills`
- [ ] Walk-forward запущено **один раз** на незміненій конфігурації
- [ ] Результат записано в журнал досліджень

## 9. Куди йти далі

- Мапа MFT-документа на код → [08-mft-2026-vidpovidnist.md](08-mft-2026-vidpovidnist.md)
- Готові приклади використання MFT-модулів → [09-mft-moduli-pryklady.md](09-mft-moduli-pryklady.md)
- Повний опис циклу дослідження → [04-tsykl-doslidzhennya.md](04-tsykl-doslidzhennya.md)
