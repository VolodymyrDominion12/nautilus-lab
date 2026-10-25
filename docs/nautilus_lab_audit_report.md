# Технічний аудит nautilus-lab: виявлені баги, патчі та план покращень

Проєкт має сильний інженерний фундамент: чіткий поділ на шари (`domain` → `application` → `infrastructure` → `interfaces`/`api`), дисципліну Spec-Driven Development (`specs/_validator.py`), захист від заглядання в майбутнє (`RollingWindow.prior()`, `Decimal`), контроль перенавчання (Walk-Forward, Purged K-Fold, PBO/CSCV, Deflated Sharpe Ratio, пререєстрація гіпотез) та fail-closed запобіжники для `lab live`.

Водночас на стиках між доменними стратегіями, адаптерами NautilusTrader, модулями оцінки воріт (`promotion_gate`), живим paper-стрімером та CLI/API виявлено низку критичних і середніх дефектів, які безпосередньо впливають на результати OOS-бектестів, коректність сайзингу та здатність стратегій пройти валідацію.

## Зведена матриця виявлених багів за пріоритетом

| ID | Пріоритет | Компонент / Файл | Суть дефекту | Вплив на систему |
| :--- | :--- | :--- | :--- | :--- |
| **BUG-01** | **P0 (Critical)** | `domain/regime_router.py`, `formulaic_lgbm_strategy.py`, `vpin_momentum.py`, `pairs_trading.py`, `adaptive_ema.py`, `meta_label_strategy.py` | Доменні роботи мутують власний стан позиції (`_current_side`, `_position`, `_direction`, `in_position`) під час OOS warm-up, при відмові фільтрів/ризику та після інтрабарних стопів | Фантомні позиції на старті OOS, пропуск легітимних входів, хибні `HOLD_NOOP` після стоп-аутів |
| **BUG-02** | **P0 (Critical)** | `domain/meta_label_strategy.py:32`, `infrastructure/nautilus/signal_strategy.py:211` | `MetaLabelStrategy` не реалізує `on_trade_tick()`, тому `hasattr(self._robot, "on_trade_tick")` повертає `False` | Прапорці `--tick-vpin` та `--hawkes` для `meta_label` мовчки ігноруються (0 тіків у фільтрах) |
| **BUG-03** | **P0 (Critical)** | `infrastructure/nautilus/signal_strategy.py:330-336` | У `on_order_filled()` при спрацюванні біржового захисного стопу (`_stop_order_id`) не викликається `self._stop_cooldown.trip()` і не скидаються `_ratchet`/`_chandelier` | `STOP_COOLDOWN_BARS` повністю обходиться при `use_protective_stop=True`; можливий миттєвий перезахід на тому ж барі |
| **BUG-04** | **P0 (Critical)** | `infrastructure/nautilus/backtest_runner.py:456, 604` | `_single_run()` та `_spread_run()` не передають `qty_step` з `instrument.size_increment` у конфіг стратегії (завжди дефолт `0.001`) | Некоректний сайзинг для BTC (`0.00001`), DOGE/ADA/XRP (`1`/`0.1`), ризик порушення 1x notional cap |
| **BUG-05** | **P1 (High)** | `api/paper_streamer.py:111, 459, 776, 785`, `application/trade_history.py:365` | Рішення в live paper штампуються часом відкриття бару (`kline["t"]`), а філи — `datetime.now(UTC)` (закриття бару); `entry_time` не містить дати | На ТФ $\ge 15	ext{m}$ різниця $> 5	ext{ хв}$ (`FILL_MATCH_TOLERANCE`), тому філи та комісії ніколи не прив'язуються до угод |
| **BUG-06** | **P1 (High)** | `api/paper_streamer.py:224-264, 732`, `api/live_sessions.py:244` | Розрив паритету Backtest ↔ Live Paper: фіксований `stop_pct` замість `2×ATR(14)`, наявність `take_profit`, зашиті параметри `vpin_momentum`/`formulaic_lgbm`, відсутність `EntryFilter`/`GlobalTrendGate` | Live paper тестує іншу торгову систему, ніж та, що досліджувалась у бектесті |
| **BUG-07** | **P1 (High)** | `application/promotion_gate.py:56, 269`, `application/run_xsmom.py:100`, `signal_strategy.py:807` | `evaluate_gate` вимагає `oos_daily_returns` для DSR (`xsmom` повертає `()`, CLI `--pbo` має `multi=None`); `xsmom` і `meta_label` класифіковані як `MEAN_REVERSION`; останній день фолду не входить у `daily_returns` | `xsmom` і CLI `--pbo` ніколи не можуть отримати оцінку DSR; завищений поріг фолдів (83%) для трендових/моментум стратегій |
| **BUG-08** | **P2 (Medium)** | `application/portfolio_replay.py:209-227` | `_vol_scale()` доповнює вікно нулями за дні до початку реплею (`flat = vol_lookback_days - len(window)`) і ділить минулий PnL на поточний `equity` | Штучне заниження оцінки волатильності на старті реплею та завищення розміру позицій до `max_scale` |
| **BUG-09** | **P2 (Medium)** | `application/alpha/validate.py:278`, `application/alpha/operators.py:146` | У `_net_sharpe_by_year()` пропущено ініціалізацію `held[:horizon-1]` через `cumsum`; у `rolling_beta`/`ts_std` кумулятивні суми вразливі до втрати точності float64 | Штучний стрибок обороту та комісії на барі `horizon - 1` у річному розрізі валідації альф |
| **BUG-10** | **P2 (Medium)** | `interfaces/cli.py:367, 614, 678, 863`, `api/research_runner.py:301, 488`, `Makefile:184`, `evaluate_recipe.py:91` | Ігнорування `--days` у `--pbo`, невірний `bar_count` у лідерборді, порт `8002` замість `8000` у `make api`, пропуск полів у `config_from_job`, $O(N^2)$ копіювання у `evaluate_recipe.py` | Помилки відтворення конфігурацій у дашборді, недоступність API при `make api`, повільна оцінка DSL-рецептів |

## Детальний розбір багів та готові патчі для виправлення

### 1. Десинхронізація стану позиції між `domain/` та рушієм виконання (BUG-01)

**Корінь проблеми:**
У `SignalRobot.on_bar()` (`src/nautilus_lab/infrastructure/nautilus/signal_strategy.py:250`) та `SpreadRobot.on_bar()` (`src/nautilus_lab/infrastructure/nautilus/spread_strategy.py:154`) виклик `self._robot.on_bar(domain_bar)` відбувається на кожному барі, включно з барами розігріву (`bar.ts_event < trade_start_ns`), до перевірки фільтрів входу (`_gate_entry`) і лімітів ризику (`_entry_allowed`). Водночас стратегії `RegimeRouter`, `AdaptiveEmaRouter`, `FormulaicLgbmStrategy`, `VpinMomentum`, `MetaLabelStrategy` та `PairsTrading` зберігають внутрішнє поле поточної позиції (`_current_side`, `_position`, `_direction`, `_state.in_position`) і оновлюють його одразу при поверненні `Signal`.

Наслідки:
1. На OOS-розігріві робот «відкриває» віртуальну позицію до `trade_start_ns`. Коли починається реальна торгівля OOS, рахунок є `FLAT`, але робот вважає, що вже в позиції (`BUY` або `SELL`), тому не генерує вхідний сигнал або в `RANGE` блокує `RangeMeanReversion`.
2. Коли вхід блокується через `EntryFilter`, `GlobalTrendGate`, `StopCooldown` або circuit breaker, доменний робот вважає, що позиція відкрита.
3. Коли позиція закривається інтрабарним захисним стопом (`protective_stop`, `ratchet`, `chandelier`), доменний робот не знає про закриття. Зокрема, `FormulaicLgbmStrategy` при протилежному сигналі генерує `FLAT` замість розвороту, що на вже закритій позиції перетворюється на `HOLD_NOOP`.

**Рекомендоване виправлення:**
Додати метод `sync_holding(self, holding: SignalSide) -> None` (або передавати поточний `holding` / викликати `abort_entry()`, як це реалізовано у `FundingCashAndCarry`), і синхронізувати стан робота перед обчисленням сигналу в `SignalRobot.on_bar()` та `LivePaperSessionManager`:

```python
# У SignalRobot.on_bar (src/nautilus_lab/infrastructure/nautilus/signal_strategy.py):
held_side = (
    SignalSide.FLAT
    if self._warming_up(int(bar.ts_event)) or self._is_flat()
    else (SignalSide.BUY if self._holding() is Holding.LONG else SignalSide.SELL)
)
if hasattr(self._robot, "sync_holding"):
    self._robot.sync_holding(held_side)
signal = self._robot.on_bar(domain_bar)
if self._warming_up(int(bar.ts_event)):
    if hasattr(self._robot, "sync_holding"):
        self._robot.sync_holding(SignalSide.FLAT)
    self._record_decision_log(domain_bar, signal, Outcome.WARMUP, steps)
    return
```

А в `_process_signal()`, якщо вхід відхилено (`refusal is not None` або вето фільтра), викликати `self._robot.sync_holding(SignalSide.FLAT if self._is_flat() else held_side)`.

### 2. Втрата тікових даних (`--tick-vpin`, `--hawkes`) у `MetaLabelStrategy` (BUG-02)

**Корінь проблеми:**
`SignalRobot.on_trade_tick()` (`src/nautilus_lab/infrastructure/nautilus/signal_strategy.py:211`) перевіряє `if not hasattr(self._robot, "on_trade_tick"): return`. Клас `MetaLabelStrategy` (`src/nautilus_lab/domain/meta_label_strategy.py`) обгортає `self._primary` (`RegimeRouter`), але не делегує йому `on_trade_tick`.

**Патч (`src/nautilus_lab/domain/meta_label_strategy.py`):**

```diff
--- a/src/nautilus_lab/domain/meta_label_strategy.py
+++ b/src/nautilus_lab/domain/meta_label_strategy.py
@@ -57,6 +57,12 @@ class MetaLabelStrategy:
     def last_trace(self) -> tuple[TraceStep, ...]:
         return self._trace
 
+    def on_trade_tick(self, *, is_buy: bool, volume: Decimal, dt_seconds: Decimal) -> None:
+        handler = getattr(self._primary, "on_trade_tick", None)
+        if callable(handler):
+            handler(is_buy=is_buy, volume=volume, dt_seconds=dt_seconds)
+
     def on_bar(self, bar: OhlcvBar) -> Signal | None:
```

### 3. Неспрацювання `StopCooldown` після біржового захисного стопу (BUG-03)

**Корінь проблеми:**
У `SignalRobot.on_order_filled()` (`src/nautilus_lab/infrastructure/nautilus/signal_strategy.py:330-336`) при виконанні ордера `self._stop_order_id` позиція закривається всередині бару до виклику `on_bar()`. Через відсутність `self._stop_cooldown.trip()` у `on_order_filled()` кулдаун ніколи не вмикається для стандартного захисного стопу та підтягнутого Chandelier-стопу.

**Патч (`src/nautilus_lab/infrastructure/nautilus/signal_strategy.py`):**

```diff
--- a/src/nautilus_lab/infrastructure/nautilus/signal_strategy.py
+++ b/src/nautilus_lab/infrastructure/nautilus/signal_strategy.py
@@ -330,6 +330,9 @@ class SignalRobot(Strategy):  # type: ignore[misc]
         if self._stop_order_id is not None and client_order_id == self._stop_order_id:
             self._stop_order_id = None
+            self._ratchet = None
+            self._chandelier = None
+            self._stop_cooldown.trip()
             self.log.info("Protective stop filled; position closed at the stop")
             self._record_stop_fill(client_order_id, event)
             return
```

### 4. Пропущений `qty_step` інструмента в `_single_run` та `_spread_run` (BUG-04)

**Корінь проблеми:**
У `src/nautilus_lab/infrastructure/nautilus/backtest_runner.py` функції `_single_run` та `_spread_run` залишають дефолтний `qty_step = Decimal("0.001")`, хоча `instrument.size_increment` для `BTC/USDT.SIM` становить `0.00001`, для `DOGE/USDT.SIM` — `1`, для `ADA/USDT.SIM` та `XRP/USDT.SIM` — `0.1`.

**Патч (`src/nautilus_lab/infrastructure/nautilus/backtest_runner.py`):**

```diff
--- a/src/nautilus_lab/infrastructure/nautilus/backtest_runner.py
+++ b/src/nautilus_lab/infrastructure/nautilus/backtest_runner.py
@@ -478,6 +478,7 @@ def _single_run(
             max_open_positions=request.risk.max_open_positions,
             kelly_fraction=request.risk.kelly_fraction,
             max_var_99=request.risk.max_var_99,
             atr_stop_multiplier=request.risk.atr_stop_multiplier,
+            qty_step=instrument.size_increment.as_decimal(),
             use_bar_vpin=request.use_bar_vpin,
@@ -615,6 +616,8 @@ def _spread_run(
             kelly_fraction=request.risk.kelly_fraction,
             max_var_99=request.risk.max_var_99,
             atr_stop_multiplier=request.risk.atr_stop_multiplier,
+            qty_step_a=instrument_a.size_increment.as_decimal(),
+            qty_step_b=instrument_b.size_increment.as_decimal(),
             use_vol_scaling=request.risk_overlay.use_vol_scaling,
```

Також у `SpreadRobot` (`src/nautilus_lab/infrastructure/nautilus/spread_strategy.py`) варто додати `self._breaches = RiskBreachTally()` та властивість `risk_breaches`, а у `FundingRobot` (`funding_strategy.py`) — підрахунок `_exposure_bars` та властивість `exposure_pct`.

### 5. Розбіжність таймстемпів у `paper_streamer.py` та втрата філів на ТФ $\ge 15	ext{m}$ (BUG-05, BUG-06)

**Корінь проблеми:**
1. У `paper_streamer.py` метод `_open_position_internal` записує `LiveFill.ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")` (час закриття свічки) та `entry_time = datetime.now(UTC).strftime("%H:%M:%S")`, тоді як `DecisionRecord.bar_end_utc` отримує `bar_obj.ts_utc` (час відкриття свічки з `kline["t"]`). Через це `trade_history.py::_enrich_trades_with_fills()` з вікном `FILL_MATCH_TOLERANCE = timedelta(minutes=5)` не знаходить філи для жодної угоди на `15m`, `1h`, `4h`, `1d`.
2. У `paper_streamer.py` стоп-дистанція рахується як `price * stop_pct` замість `stop_distance(price, limits, atr=self._atr.value)`, а для `vpin_momentum` та `formulaic_lgbm` зашиті константи замість параметрів зі `Settings`.

**Патч (`src/nautilus_lab/api/paper_streamer.py`):**
- Передавати `ts=bar_obj.ts_utc` у `_decide(signal, close_price, trace, ts=bar_obj.ts_utc)` → `_execute_signal(..., ts=ts)` → `_open_position_internal(..., ts=ts)` та `_close_position_internal(..., ts=ts)`.
- Оновлювати `self._atr = AverageTrueRange(14)` на кожному закритому барі (включно з `warm_up`) і обчислювати `stop_dist = stop_distance(price, self._limits(), atr=self._atr.value)`.
- Зробити `take_profit_multiple` опціональним (`Decimal("0")` за замовчуванням для паритету з бектестом).

### 6. Виправлення `promotion_gate.py`, `run_xsmom.py` та `_update_equity_path` (BUG-07)

**Корінь проблеми:**
1. У `promotion_gate.py::_audit_checks()` при `multi is None` (виклик `lab research --pbo`) або коли `multi.oos_daily_returns` порожній (`XsMomWalkForwardReport`), `dsr` примусово стає `None` (`not measured`), ігноруючи `audit.deflated_sharpe.probability`.
2. У `class_for_robot()` (`promotion_gate.py:56`) роботи `xsmom`, `vpin_momentum` та `meta_label` віднесені до `MEAN_REVERSION` (поріг прибуткових фолдів 83% замість 50% і обов'язковий сирий `beats_buy_hold`), а `formulaic_lgbm` повертає `None`.
3. У `_update_equity_path()` (`signal_strategy.py:807`, `spread_strategy.py:349`, `funding_strategy.py:354`) приріст за останній календарний день фолду ніколи не додається до `_daily_returns`.

**Патч (`src/nautilus_lab/application/promotion_gate.py`):**

```diff
--- a/src/nautilus_lab/application/promotion_gate.py
+++ b/src/nautilus_lab/application/promotion_gate.py
@@ -54,8 +54,8 @@ class StrategyClass(StrEnum):
 
 def class_for_robot(robot: str) -> StrategyClass | None:
-    if robot in ("ema", "regime", "adaptive_ema"):
+    if robot in ("ema", "regime", "adaptive_ema", "xsmom", "vpin_momentum", "meta_label"):
         return StrategyClass.TREND_FOLLOWING
-    if robot in ("vpin_momentum", "pairs", "meta_label", "ml_obi", "glft", "tri_scan", "xsmom"):
+    if robot in ("pairs", "ml_obi", "glft", "tri_scan", "formulaic_lgbm"):
         return StrategyClass.MEAN_REVERSION
     if robot == "funding":
         return StrategyClass.CARRY
@@ -282,9 +282,9 @@ def _audit_checks(
         dsr = dsr_result.probability
         trials = dsr_result.n_trials_total
         dsr_str = f"DSR={dsr} (OOS daily returns)"
     else:
-        dsr = None
+        dsr = audit.deflated_sharpe.probability
         trials = audit.deflated_sharpe.n_trials_total
-        missing = "run `lab research --folds N` for OOS daily returns"
-        dsr_str = missing
+        dsr_str = f"DSR={dsr} (block returns)" if dsr is not None else audit.deflated_sharpe.note
```

### 7. Виправлення `_vol_scale` у `portfolio_replay.py` та `_net_sharpe_by_year` у `alpha/validate.py` (BUG-08, BUG-09)

**Патч для `src/nautilus_lab/application/portfolio_replay.py`:**

```diff
--- a/src/nautilus_lab/application/portfolio_replay.py
+++ b/src/nautilus_lab/application/portfolio_replay.py
@@ -211,12 +211,15 @@ def _vol_scale(
     if rules.target_vol is None:
         return 1.0
+    if not daily:
+        return 1.0
+    first_day = min(daily)
+    elapsed_days = min(rules.vol_lookback_days, max(0, (today - first_day).days))
+    if elapsed_days < 5:
+        return 1.0
     window = [
         pnl / equity
         for day, pnl in daily.items()
         if 0 < (today - day).days <= elapsed_days
     ]
-    # Days without an exit are flat days: count them, or the vol is overstated.
-    flat = rules.vol_lookback_days - len(window)
+    flat = elapsed_days - len(window)
     returns = window + [0.0] * max(flat, 0)
     if len(window) < 5:
         return 1.0  # not enough history yet to scale on
```

**Патч для `src/nautilus_lab/application/alpha/validate.py`:**

```diff
--- a/src/nautilus_lab/application/alpha/validate.py
+++ b/src/nautilus_lab/application/alpha/validate.py
@@ -275,7 +275,9 @@ def _net_sharpe_by_year(
 ) -> dict[int, float]:
     target = np.nan_to_num(unit_gross(weights), nan=0.0)
-    held = np.nan_to_num(ts_sum(target, horizon) / horizon)
+    held = ts_sum(target, horizon) / horizon
+    held[: horizon - 1] = np.cumsum(target, axis=0)[: horizon - 1] / horizon
+    held = np.nan_to_num(held, nan=0.0)
     previous = np.zeros_like(held)
```

### 8. Виправлення CLI, API, `Makefile` та `evaluate_recipe.py` (BUG-10)

1. **`Makefile:184`**: змінити `--port 8002` на `--port 8000`, щоб `make api` відповідав `frontend/src/config.ts` та `DEFAULT_ALLOWED_ORIGINS`.
2. **`src/nautilus_lab/interfaces/cli.py`**:
   - У `_run_pbo()` (`cli.py:678`) та `api/research_runner.py:301` передавати `days=getattr(args, "days", None)` / `days=job.days` у `overfit_audit_request()`.
   - У `_print_backtest()` (`cli.py:863`) замінити `_breach_line("cost", report)` на `_breach_line("backtest", report)`.
   - У `composition.py:367` (`live_paper_use_case`) визначати символ стріму через `binance_symbol_for_instrument(resolved.instrument_id) or resolved.binance_symbol`.
3. **`src/nautilus_lab/api/research_runner.py:488` та `frontend/src/lib/researchForm.ts:96`**: додати `days`, `cost_profile`, `promote` та `preregister` у `config_from_job()` та `applyArchivedRun()`.
4. **`src/nautilus_lab/application/evaluate_recipe.py:87`**: винести `filled_rows = _filled(rows)` за межі циклу `for index in range(len(bars) - horizon_bars):` (прибирає $O(N^2)$ алокації).
5. **Гігієна репозиторію**: видалити тимчасові файли в корені та документації (`Claude outputs/ci.yml`, `e29-dependency-groups.patch`, перейменувати `docs/Untitled.md` у номерний документ).

## Архітектурні та дослідницькі покращення (Roadmap)

### 1. Узгодження навчання `meta_label` з реальними правилами виходу стратегії
Зараз `build_meta_label_dataset()` (`src/nautilus_lab/application/train_meta_label.py:66-98`) навчає класифікатор на мітках `label_triple_barrier(profit_multiple=2, stop_multiple=1, horizon=5)`, тоді як у бектесті `MetaLabelStrategy` не має ні тейк-профіту $2\sigma$, ні 5-барового вертикального бар'єру — вихід відбувається за сигналом `RegimeRouter` (перетин EMA / смуги Боллінджера) або за стопом $2 	imes 	ext{ATR}(14)$. Крім того, цикл у `build_meta_label_dataset()` пропускає прямі розвороти (`BUY` → `SELL` без проміжного `FLAT`), бо `awaiting_entry` скидається лише на `SignalSide.FLAT`.
- **Покращення**: Формувати навчальні мітки для `meta_label` за фактичним результатом угоди первинного робота (`RegimeRouter` + захисний стоп $2 	imes 	ext{ATR}(14)$ після комісій), а також впровадити дробовий сайзинг позиції (Fractional Bet Sizing за ймовірністю класифікатора $P$) замість бінарного відсікання.

### 2. Перехід від одноінструментних прогонів до портфельного виконання на USDⓈ-M Perps
Як показали батчі `20261013_053010` та `20261016_094231`, `regime` на `4h` обганяє vol-matched Buy&Hold на 7–8 із 11 монет, але:
- ~40% прибутку дають шорти, які на споті не мають вартості запозичення й не можуть виконуватися без маржинального займу;
- при `RISK_PER_TRADE=0.005` і стопі $2 	imes 	ext{ATR}$ середнє завантаження капіталу становить лише 3–4% equity;
- у фазах синхронного боковику (фолд 3) всі монети одночасно отримують стоп-аути.
- **Покращення**:
  1. Додати перемикач `market` (`spot` / `perp`) та поле `hypothesis` (пререєстрація) безпосередньо у веб-форму `BatchLaunchForm.tsx` (бекенд `BatchRunRequest` вже їх підтримує).
  2. Нараховувати funding settlements безпосередньо всередині `SignalRobot` під час бектесту перпетуалів (`*-PERP.SIM`), а не лише постфактум у `batch_store._breakdown()`, щоб крива капіталу, просадка та circuit breakers враховували фандинг у реальному часі.
  3. Перенести логіку `portfolio_replay.py` (ліміт сумарного відкритого ризику `max_heat=3%` та ліміт однонаправлених позицій `max_per_side=4`) у повноцінний мультиінструментний адаптер `BacktestEngine`, де всі монети торгують від спільного балансу `USDT`.

### 3. Векторизація та чисельна стабільність у `application/alpha/`
У `src/nautilus_lab/application/alpha/operators.py` функції `ts_std()` та `rolling_beta()` використовують префіксні суми квадратів (`np.cumsum(x * x)`) вздовж усієї осі часу `T`. На довгих історичних серіях (десятки тисяч годинних барів) різниця `(mean_sq - mean * mean)` та `sxx - sx * sx / n` втрачає точність через catastrophic cancellation у `float64`.
- **Покращення**: Центрувати ряд відносно ковзного середнього у вікні (`sliding_window_view`) або використовувати алгоритм Велфорда / `scipy`/`numba`-сумісне віконне обчислення, а в `_crowding()` (`signals.py:154`) передавати маску `only_members(..., ctx.member)`, щоб ранжування не включало монети поза точковим універсумом.
