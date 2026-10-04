# 31. Перемикачі режиму та фільтри входу

Довідник змінних, на які посилається код: `REGIME_LEGS`, range-лег, мінімальний час
утримання та фільтри входу. Усе нижче прочитано з коду, посилання — `шлях:рядок`.

Продовження: [docs/32](32-model-vykonannia-ta-filtry-vkhodu.md) (звідки взялись фільтри —
потрейдовий розбір батчу `20261001_182028_batch`, гіпотези H1–H4) і
[docs/33](33-plan-pislia-batchu-20261002.md) (як перевіряти перемикачі після батчу).

## 1. `REGIME_LEGS` — які ноги режиму працюють

| факти | код |
|---|---|
| `regime_legs: str = ""`; порожньо = усі ноги | `infrastructure/settings.py:169` |
| Невідома нога — `ValueError` на старті, не посеред батчу | `infrastructure/settings.py:230-234` → `domain/regime_router.py:31` |
| `ALL_LEGS` — усі ноги; поведінка до появи перемикача | `domain/regime_router.py:27-28` |
| Канонічна назва `legs_label`: відсортовані ноги, `""` коли всі | `domain/regime_router.py:43-54` |
| Читають `adaptive_ema` і `regime` (той самий router обслуговує `meta_label` primary) | `infrastructure/nautilus/signal_strategy.py:1298`, `:1361` |
| Вимкнена нога втрачає **входи**, її виходи (`FLAT`) проходять; крок `Stage.FILTER` `regime_legs` `BLOCK`/`INFO` з `values={"leg","enabled"}` | `domain/regime_router.py:57-81` |
| Проводка `Settings` → `BacktestRequest` | `interfaces/composition.py:392`, `application/dtos.py:57` |

Приклад для батчу — `REGIME_LEGS=uptrend,range` (`.env.example:129-130`): гіпотеза
«короткий пробій програє на кожному фолді» перевіряється конфігурацією прогону, а не
правкою робота (`domain/regime_router.py:66-68`).

**Чому це в пререєстрації й у `trial_id`.** Вимкнена нога — інший набір входів на тих
самих даних, тож це новий слот пошуку: `trial_id` отримує хвіст `legs=<канонічна назва>`
(`application/trial_ledger.py:75-77`, пояснення — `:46-53`), терміни пререєстрації —
пару `("regime_legs", legs)` (`application/preregistration.py:72-74`). Обидва пишуть
значення **лише коли воно не дефолтне**: реєстрація «всі ноги» не засвідчить прогін із
вимкненою ногою, а записи до 2026-10-02 зберігають свої id і хеші. Закріплено тестами
`tests/unit/test_regime_legs.py`, `tests/unit/test_trial_ledger.py:163-165`,
`tests/unit/test_preregistration.py:118-127`.

## 2. `REGIME_RANGE_ALLOW_SHORT` і `REGIME_MIN_HOLD_BARS`

- `REGIME_RANGE_ALLOW_SHORT`, дефолт `true` = шорт дозволено; `false` = верхня смуга
  Боллінджера лише забирає прибуток (`infrastructure/settings.py:126-127`) → проводка в
  `RegimeParams.range_allow_short` (`:276`, `domain/regime.py:113`) → `RangeMeanReversion`
  (`domain/regime_router.py:112-117`). Слід у журналі спроб — `range_long_only`
  (`application/trial_ledger.py:71-72`), у реєстрації — `("range_allow_short", …)`
  (`application/preregistration.py:67`). У `adaptive_ema` це **окремий** перемикач
  `ADAPTIVE_RANGE_ALLOW_SHORT` із дефолтом `false` (`infrastructure/settings.py:151`).
- `REGIME_MIN_HOLD_BARS`, дефолт `0` = вимкнено (`infrastructure/settings.py:128-129`);
  `min_hold_bars >= 0` перевіряє `RegimeParams` (`domain/regime.py:117-121`). У
  `RegimeRouter.on_bar` вихід/фліп раніше ніж через N барів не проходить
  (`domain/regime_router.py:178-195`) → крок `Stage.FILTER` `min_hold_bars` `BLOCK` із
  фактичним числом барів (`:188-193`). У `trial_id` — `min_hold=N`
  (`application/trial_ledger.py:73-74`), у пререєстрації — `("regime_min_hold_bars", …)`
  (`application/preregistration.py:77-78`).

## 3. Фільтри входу: `ENTRY_FILTER_HTF_TREND` і `ENTRY_FILTER_VOL_EXPANSION`

| env | дефолт | що робить | код |
|---|---|---|---|
| `ENTRY_FILTER_HTF_TREND` | `false` | вхід лише в бік нахилу повільної EMA | `domain/entry_filters.py:136-168` |
| `ENTRY_FILTER_HTF_EMA_PERIOD` | `200` | вікно тієї EMA | `domain/entry_filters.py:42`, `:92` |
| `ENTRY_FILTER_HTF_SLOPE_LOOKBACK` | `24` | нахил = EMA зараз мінус EMA N барів тому | `domain/entry_filters.py:43`, `:110-115` |
| `ENTRY_FILTER_VOL_EXPANSION` | `false` | вхід лише коли діапазон бару не стиснутий | `domain/entry_filters.py:169-202` |
| `ENTRY_FILTER_VOL_FAST_PERIOD` | `24` | швидке вікно діапазону | `domain/entry_filters.py:46`, `:122` |
| `ENTRY_FILTER_VOL_SLOW_PERIOD` | `300` | повільне вікно; мусить бути більшим за швидке | `domain/entry_filters.py:47`, `:59-60` |
| `ENTRY_FILTER_MIN_VOL_RATIO` | `1` | поріг відношення швидке/повільне | `domain/entry_filters.py:48`, `:190` |

Дефолти — `infrastructure/settings.py:130-138`, збірка — `:280-290` і
`domain/entry_filters.py:36-50`; решта перевірок (`htf_ema_period >= 2`,
`htf_slope_lookback >= 1`, `vol_fast_period >= 1`, `min_vol_ratio > 0`) —
`domain/entry_filters.py:52-62`. Готовність вікон до першого вердикту —
`EntryFilterParams.warmup_bars()` (`:69-76`).

Застосовує **лише дослідницький бектест**: `EntryFilter` будується з конфіга
(`infrastructure/nautilus/signal_strategy.py:222-233`), годується кожним закритим баром,
разом із warm-up (`:329-331`), і питається в `_gate_entry` (`:846-853`). Фільтри ніколи
не блокують вихід — вони вирішують лише долю входу (`domain/entry_filters.py:17-18`).

## 4. `NO_INSTANT_REVERSE` — без миттєвого розвороту

Дефолт `false` (`infrastructure/settings.py:139-140`): протилежний сигнал лише закриває
позицію. Застосовує `_gate_entry` через `without_reversal(plan)`
(`infrastructure/nautilus/signal_strategy.py:830-843`, `domain/position_plan.py:69-77`) →
крок `Stage.PLAN`, компонент `no_instant_reverse`, `MODIFY`, `result="exit only"`.
У `trial_id` — токен `no_instant_reverse` (`application/trial_ledger.py:69-70`).

## 5. Як заблокований вхід видно в журналі рішень

- Відмова фільтра повертається як `filter.<код>`, де код — `EntryVerdict.code`
  (`domain/entry_filters.py:83-84`; значення `htf_trend`/`vol_expansion` — `:154`, `:168`,
  `:188`, `:202`; збірка рядка — `signal_strategy.py:846-853`, повернення —
  `_process_signal`, `:699-701`).
- `_process_signal` віддає `Outcome.SIGNAL_VETOED` разом із цим `blocked_by`
  (`signal_strategy.py:354-359`; константа — `domain/decision_trace.py:69`). Отже в
  журналі: `outcome="SIGNAL_VETOED"`, `blocked_by="filter.htf_trend"` або
  `"filter.vol_expansion"`, а кроки мають `stage="filter"` (`Stage.FILTER`,
  `domain/decision_trace.py:39`) з `values`/`thresholds` фільтра
  (`domain/entry_filters.py:136-166`, `:169-200`).
- Два випадки, де `blocked_by` **порожній**, а причина лежить у кроці `FILTER`: вимкнена
  нога режиму гасить сигнал усередині робота (`domain/regime_router.py:70-81`) і
  `min_hold_bars` відкидає вихід/фліп (`domain/regime_router.py:186-195`). Обидва дають
  `signal=None` зі кроком `FILTER`+`BLOCK`, і загальне правило `_vetoed`
  (`signal_strategy.py:355-356`, `:1221-1226`) ставить `SIGNAL_VETOED`.
- Дайджест рахує такі бари окремою групою `vetoed` (`application/decision_digest.py:51`,
  `:215`), людський підпис — `application/decision_narrative.py:29`.

## 6. Таблиця «перемикач → дефолт → що робить → хто читає»

| перемикач | дефолт | що робить | хто читає |
|---|---|---|---|
| `REGIME_LEGS` | `""` (усі ноги) | вимикає входи вибраних ніг | `RegimeRouter`/`AdaptiveEmaRouter` (`signal_strategy.py:1298`, `:1361`) |
| `REGIME_RANGE_ALLOW_SHORT` | `true` | `false` = range-лег не шортить | `RegimeParams` → `RangeMeanReversion` (`domain/regime_router.py:116`) |
| `REGIME_MIN_HOLD_BARS` | `0` | не дає вийти/фліпнути раніше N барів | `RegimeRouter.on_bar` (`domain/regime_router.py:178-195`) |
| `ENTRY_FILTER_HTF_TREND` (+`_HTF_EMA_PERIOD`, `_HTF_SLOPE_LOOKBACK`) | `false` (`200`, `24`) | вхід лише за нахилом повільної EMA | `EntryFilter.evaluate` (`domain/entry_filters.py:136-168`) |
| `ENTRY_FILTER_VOL_EXPANSION` (+`_VOL_FAST_PERIOD`, `_VOL_SLOW_PERIOD`, `_MIN_VOL_RATIO`) | `false` (`24`, `300`, `1`) | вхід лише при нестиснутій волатильності | `EntryFilter.evaluate` (`domain/entry_filters.py:169-202`) |
| `NO_INSTANT_REVERSE` | `false` | розворот без зворотного входу | `_gate_entry` (`signal_strategy.py:830-843`) |

## 7. Чого ці перемикачі **не** роблять у live-paper

Живий paper-термінал будує роботів сам за `LivePaperConfig` (`api/paper_streamer.py:108-133`),
і ця конфігурація не має ні поля ніг режиму, ні полів фільтрів входу; `RegimeRouter` там
створюється без `legs` (`api/paper_streamer.py:381-385`) — тобто всі ноги ввімкнені, а
гейти в `_decide` — лише `session_active` (`:676-681`) і `auto_trade` (`:682-687`).

Отже в live-paper **не діють**: `REGIME_LEGS`, `ENTRY_FILTER_*`, `NO_INSTANT_REVERSE`.
**Діють** `REGIME_RANGE_ALLOW_SHORT` і `REGIME_MIN_HOLD_BARS`: вони приходять як
`RegimeParams` через `regime=cfg.regime_params()` (`api/live_paper_boot.py:63`), а не
через робота. Те саме обмеження зафіксовано в [docs/32 §2](32-model-vykonannia-ta-filtry-vkhodu.md).
