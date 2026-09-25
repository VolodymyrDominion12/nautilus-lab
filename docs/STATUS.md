# Стан роботів і гейтів

<!-- Згенеровано scripts/gen_status.py. Не редагувати вручну: змінити код або
     spec і виконати `uv run python scripts/gen_status.py`.
     tests/unit/test_status_doc.py падає, поки файл застарілий. -->

Єдина таблиця стану (docs/27 E-2.8). Кожна клітинка прочитана з коду або зі
специфікації, тож розійтися з ними вона не може; docs/21, docs/22 і docs/README
посилаються сюди замість того, щоб переписувати статуси.

## Роботи

| Робот | Статус spec | Бектест | Адаптер | Tick VPIN | Hawkes | Paper (батч) | Live paper | Вимір | Причина / суть |
|---|---|---|---|---|---|---|---|---|---|
| [`ema`](../specs/strategies/ema.yaml) | candidate | так | `signal_strategy` | — | — | так | так | виміряно: не обганяє buy&hold | EMA crossover: always-in-market baseline на двох експоненційних середніх |
| [`formulaic_lgbm`](../specs/strategies/formulaic_lgbm.yaml) | candidate | так | `signal_strategy` | — | — | так | так | виміряно: не обганяє buy&hold | Formulaic LGBM: напрямок бару з 12 формульних ознак OHLCV + пороговий класифікатор |
| [`meta_label`](../specs/strategies/meta_label.yaml) | candidate | так | `signal_strategy` | так | так | так | — | не виміряно | Meta-label: LightGBM вирішує, чи брати сигнал regime, а не напрямок ціни |
| [`ml_obi`](../specs/strategies/ml_obi.yaml) | candidate | так | `signal_strategy` | — | — | так | — | не виміряно | ML за дисбалансом книги: OBI + WOFI + fade → сигнал напрямку |
| [`pairs`](../specs/strategies/pairs.yaml) | candidate | так | `spread_strategy` | — | — | так | — | виміряно: не обганяє buy&hold | Pairs trading: коінтеграція ETH/BTC і повернення до середнього за z-score |
| [`regime`](../specs/strategies/regime.yaml) | candidate | так | `signal_strategy` | так | так | так | так | виміряно: не обганяє buy&hold | Regime router: Donchian у тренді, Bollinger mean reversion у флеті |
| [`vpin_momentum`](../specs/strategies/vpin_momentum.yaml) | candidate | так | `signal_strategy` | так | — | так | так | виміряно: не обганяє buy&hold | VPIN momentum: момент у бік токсичного потоку, трейлінг-стоп за ATR |
| [`funding`](../specs/strategies/funding.yaml) | blocked | — | `none` | — | — | — | — | не виміряно | Бракує двох складових із трьох — розрив «даних» закрито у v1.1. |
| [`glft`](../specs/strategies/glft.yaml) | blocked | — | `none` | — | — | — | — | не виміряно | (1) Немає споживача `QuoteIntent`. |
| [`tri_scan`](../specs/strategies/tri_scan.yaml) | blocked | — | `none` | — | — | — | — | не виміряно | (1) Класу-робота не існує. |
| [`adaptive_ema`](../specs/strategies/adaptive_ema.yaml) | rejected | так | `signal_strategy` | — | — | так | так | виміряно: не обганяє buy&hold | Контрольний A/B на каталозі 1h (23 697 барів на інструмент, 4 rolling-фолди, embargo 10, конфігурації зафіксовані всередині фолду і НЕ віді… |

Лише в live paper (еталони, не стратегії): `hold`.

**Бектест** — робот є в `BACKTEST_WIRED_ROBOTS` (інакше він fail-closed, а не
підмінюється іншим). **Paper (батч)** — `lab paper`; **Live paper** — термінал
дашборду. **Вимір** — `evidence` зі spec: «не обганяє» означає «не доведено», а
не «закрито»; закрита гіпотеза має статус `rejected`.

## Гейт просування (research → paper)

Джерело — `GateCriteria` в `src/nautilus_lab/application/promotion_gate.py`;
пороги зафіксовані до будь-якого прогону
([ADR 0003](adr/0003-porohy-heita-z-kodu.md)). Робот проходить, лише коли кожна
перевірка виміряна й пройдена: невиміряне ніколи не читається як «так».

| Поріг | Значення | Що означає |
|---|---|---|
| `min_folds` | 6 | ковзних walk-forward фолдів, не менше |
| `min_profitable_share` | 83% | частка OOS-фолдів у плюсі після комісій, не менше |
| `min_oos_fills` | 30 | OOS-угод у сумі по фолдах, не менше |
| `max_pbo` | 0.3 | ймовірність перенавчання (PBO, CSCV), не більше |
| `min_dsr` | 0.95 | дефльований Шарп (DSR як імовірність; 0.95 = p ≤ 0.05), не менше |

Додатково до гейта, поки без машинної перевірки (docs/21 §10): поріг
беззбитковості > сплачені витрати + 5 bps і жодного маржин-колу чи стоп-ауту
на кризових слайсах `covid2020` та `ftx2022`.

## Компоненти

| Компонент | Статус | Суть |
|---|---|---|
| [`agg-trades-catalog`](../specs/components/agg-trades-catalog.yaml) | active | Parquet-каталог aggTrades: публічний REST Binance, day-sharded, без API-ключів |
| [`backtest-engine`](../specs/components/backtest-engine.yaml) | active | NautilusTrader BacktestEngine: песимістична симуляція й fail-closed роботи |
| [`breakeven-cost`](../specs/components/breakeven-cost.yaml) | active | Breakeven-cost: максимальна комісія на одиницю обороту, за якої PnL = 0 |
| [`dashboard-api`](../specs/components/dashboard-api.yaml) | active | Веб-дашборд ↔ FastAPI: повага до fail-closed і до відсутніх даних |
| [`data-catalog`](../specs/components/data-catalog.yaml) | active | Parquet-каталог історії: публічний ingest Binance, один каталог — одна серія |
| [`deflated-sharpe`](../specs/components/deflated-sharpe.yaml) | partial | DSR: чи переможець сітки кращий за найкращого з N випадкових прогонів |
| [`execution-modes`](../specs/components/execution-modes.yaml) | active | Режими виконання: research, paper, live — і fail-closed запобіжники |
| [`overfitting-audit`](../specs/components/overfitting-audit.yaml) | active | PBO/CSCV: чи переживає вибір параметрів дані, яких вона не бачила |
| [`purged-k-fold`](../specs/components/purged-k-fold.yaml) | active | Purged K-fold: embargo в одиницях часу мітки, не в кількості рядків |
| [`risk-layer`](../specs/components/risk-layer.yaml) | partial | Розмір позиції від стопу, ліміти й circuit breakers — поза стратегією |
| [`walk-forward`](../specs/components/walk-forward.yaml) | active | In-sample лише обирає параметри, out-of-sample лише звітує |

## Розбіжності spec ↔ код

Немає: кожна специфікація каже те саме, що код.
