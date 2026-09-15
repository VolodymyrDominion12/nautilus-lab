# State: режими процесу, ринку й ризику

## Режим торгівлі процесу

Live ніколи не переходить у виконання: немає адаптера ордерів.

```mermaid
stateDiagram-v2
    [*] --> Research: типовий Settings / lab research
    Research --> Paper: lab paper
    Paper --> Research: повернутися до бектесту
    Research --> LiveBlocked: lab live
    Paper --> LiveBlocked: mode=LIVE
    LiveBlocked --> [*]: LiveTradingDisabledError
    note right of LiveBlocked
        require_simulated_mode
        викликається в CLI, composition і use case
    end note
```

| Стан | Гроші | I/O |
|------|-------|-----|
| RESEARCH | симуляція | історія / синтетика / каталог |
| PAPER | симуляція | лог гіпотетичних ордерів, без біржі |
| LIVE | заборонено | завжди виняток |

## Режим ринку в `RegimeClassifier`

Гістерезис: увійти в тренд важче (`enter_trend_er`), ніж лишитися в ньому (`exit_trend_er`).
Поки індикатори не прогріті, режиму немає.

```mermaid
stateDiagram-v2
    [*] --> Warmup: недостатньо закритих барів
    Warmup --> Range: initialized, ER низький
    Range --> Uptrend: ER >= enter і нахил EMA вгору
    Range --> Downtrend: ER >= enter і нахил EMA вниз
    Uptrend --> Range: ER < exit або нахил зник
    Downtrend --> Range: ER < exit або нахил зник
    Uptrend --> Downtrend: зміна знака нахилу при високому ER
    Downtrend --> Uptrend: зміна знака нахилу при високому ER
```

`RegimeRouter` на **будь-якій** зміні режиму спочатку емітує `SignalSide.FLAT`,
потім на наступних барах торгує стратегією нового режиму:

| Режим | Стратегія |
|-------|-----------|
| UPTREND | Donchian breakout long |
| DOWNTREND | Donchian breakout short |
| RANGE | Bollinger mean reversion |

Опційний `--bar-vpin`: токсичний VPIN може змістити ефективний режим (флет з нахилом → тренд).

## Рішення про вхід

Не повний автомат позиції Nautilus, а логіка **до** ордера в адаптері.

```mermaid
stateDiagram-v2
    [*] --> NoSignal: on_bar без Signal
    NoSignal --> Flatten: Signal FLAT
    NoSignal --> CheckRisk: Signal BUY або SELL
    Flatten --> Flat: close_all_positions
    CheckRisk --> Blocked: evaluate_entry.allowed = false
    CheckRisk --> Skip: вже в потрібному боці або qty = 0
    CheckRisk --> Enter: allowed і qty > 0
    Enter --> InPosition: market order
    InPosition --> Flatten: FLAT / зміна режиму / on_stop
    Blocked --> NoSignal: чекати наступний бар
    Skip --> NoSignal
    Flat --> NoSignal
```

Circuit breakers у `evaluate_entry`: денний збиток, максимальна просадка, ліміт позицій,
VaR 99%, опційно CVaR. Flattening — обов'язок адаптера, не стратегії.
