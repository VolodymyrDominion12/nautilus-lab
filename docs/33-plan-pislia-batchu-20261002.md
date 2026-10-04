# 33. План після батчу 20261002: потрейдовий розбір, умови тесту, тір C

Продовження docs/32. Батч `20261002_131115_batch` (8 роботів × BTC/ETH, 1h, 6 фолдів,
нова модель виконання) — усі клітинки REJECT. Найближчий кандидат — `regime`
(ETH +0.34%/фолд, BTC −0.07%, 4/6 прибуткових фолдів). Майже скрізь gross > 0, але
комісії ≥ gross.

## 1. Уточнення до першого розбору

Після читання коду три пункти розбору виявились неточними:

| було сказано | насправді |
|---|---|
| vpin_momentum дав 0 угод через `bar_vpin=False` | `VpinMomentum` завжди будує `BarVpin`; причина — фіксований `VPIN_TOXIC_THRESHOLD=0.7` недосяжний на 1h-барах (max ≈ 0.694). Уже закрито комітом «QuantileVpin» (`USE_QUANTILE_VPIN`). |
| стоп заповнюється «по тригеру без гепу» — треба моделювати геп | стоп — справжній `StopMarket` у рушії; бар, що відкрився за стопом, заповнює його по open. На 24/7-крипті open ≈ попередній close, тож гепів майже немає. Оптимізм лишається хіба що всередині бару (1 тік проковзування з імовірністю 25%). Стрес-тест — через комісію (§4). |
| потрібен новий перемикач, щоб вимкнути range-leg | він уже є: `REGIME_LEGS=uptrend,downtrend` (docs/31). |

## 2. Що змінено в коді

1. **`application/trade_breakdown.py` + `scripts/batch_trade_breakdown.py`** — розбір
   кожної клітинки батчу по угодах. Відтворює ручний розбір regime_BTC (142 угоди, net
   −1 536 = gross 8 757 − fees 10 293). Розбиває по фолдах, сторонах, ногах, причинах
   виходу й часу утримання. Ще дає два діагностичні теги, які рахує той самий
   `EntryFilter`, що й ворота: нахил повільної EMA і vol ratio. Окрім Markdown-звіту
   пише `cells/<id>/trades.csv`.
   ```bash
   uv run python scripts/batch_trade_breakdown.py reports/batches/20261002_131115_batch
   # 4h-клітинки: ті самі календарні вікна
   uv run python scripts/batch_trade_breakdown.py <batch> --htf-ema-period 50 \
       --htf-slope-lookback 6 --vol-fast 6 --vol-slow 75
   ```
2. **`REGIME_LEGS` тепер входить в умови преєстрації і в `trial_id`.** Раніше
   реєстрація з усіма ногами могла засвідчити прогін без range-leg, а вимкнена нога
   не додавала спробу до DSR. Нова функція `domain/regime_router.legs_label` дає
   канонічне ім'я (`"downtrend,uptrend"`). Коли ввімкнено всі ноги, ім'я порожнє, тож
   хеші й id, записані раніше, не змінились. Так само в умови тесту потрапляє
   `vpin_quantile`, коли `USE_QUANTILE_VPIN=true`.
3. **`scripts/run_matrix.py`: тір C і `--register`.**
   - Тір C: `regime` H0 і H3 на SOL/BNB/XRP/ADA, 1h (`catalog`) і 4h (`catalog_2019_4h`),
     16 прогонів.
   - `--register` спершу записує умови кожного прогону (`lab research --register`),
     не запускаючи бектест.
   - `MatrixRun.variant` розводить логи H0/H3; `--dry-run` показує env.

## 3. Гіпотези

| id | env | звідки |
|---|---|---|
| H0 | `REGIME_LEGS=uptrend,downtrend` | range-leg: 18 угод, gross ≈ 0, net −1.6k (BTC) |
| H1 | H0 + `ENTRY_FILTER_HTF_TREND=true` | угоди за нахилом +7.9k, проти нахилу −6.2k (BTC), так само в батчі 20261001 |
| H2 | H0 + `ENTRY_FILTER_VOL_EXPANSION=true` | vol ratio ≥ 1: +11.2k, < 1: −9.1k (BTC) |
| H3 | H0 + H1 + H2 | разом лише 28 угод на BTC — мала вибірка |

H1 і H2 знайдено на тих самих OOS-даних **двічі**. Тому прогони на BTC/ETH лише
перевіряють, що ворота працюють як задумано. Доказом вони не є. Доказ дає тільки тір C:
монети, яких розбір не бачив.

Вікна на 4h перераховано на той самий календарний проміжок, а не підібрано:
EMA200×1h ≈ EMA50×4h, нахил 24 год = 6 барів, ATR 24/300×1h = 6/75×4h.

## 4. Порядок запуску

1. Тести й лінтери, коміт (матриця відмовляється стартувати на брудному дереві):
   ```bash
   uv run pytest && uv run ruff check && uv run mypy src tests
   ```
2. **Перевірка воріт на BTC/ETH 1h** (дашборд → Batch backtest; `robots: ["regime"]`,
   `symbols: ["BTCUSDT","ETHUSDT"]`, `interval: "1h"`, `folds: 6`, `is_fraction: "0.7"`,
   `days: 1000`). Гіпотези можна зробити **варіантами одного батчу** (`"variants"`:
   `H0`, `H1`, `H2`, `H3`, `H3-cost-stress` — кожна клітинка виконається по разу на
   варіант, клітинки звуться `regime_BTC__H1`), або, як робилось досі, окремим батчем з
   міткою:

   | label | env |
   |---|---|
   | `C-H0-trend-legs` | `{"REGIME_LEGS": "uptrend,downtrend"}` |
   | `C-H1-htf` | H0 + `{"ENTRY_FILTER_HTF_TREND": "true"}` |
   | `C-H2-vol` | H0 + `{"ENTRY_FILTER_VOL_EXPANSION": "true"}` |
   | `C-H3-both` | H0 + обидва |
   | `C-H3-cost-stress` | H3 + `{"COST_PROFILE": "stress_x1_5"}` (базовий тариф ×1.5: проковзування понад модель філу; `SPOT_TAKER_FEE=0.001` лишається рівнозначним ручним способом) |

   Після кожного батчу: `scripts/batch_trade_breakdown.py <batch>`. Якщо ворота
   заблокували не ті угоди, які розбір позначив як «проти нахилу» чи «стиснута
   волатильність», значить у коді помилка.
3. **Тір C — справжня перевірка:**
   ```bash
   uv run python scripts/run_matrix.py --tier C --dry-run     # команди + env
   uv run python scripts/run_matrix.py --tier C --register    # умови ДО прогону
   uv run python scripts/run_matrix.py --tier C               # 16 прогонів
   ```
   Логи: `reports/matrix/C_regime_<COIN>_<interval>_<H0|H3>[.register].log`.

## 5. Критерії, наперед

Варіант проходить, якщо на тірі C, на більшості монет обох інтервалів:

- mean OOS net вищий за vol-matched buy&hold;
- прибуткових фолдів щонайменше 4 з 6;
- breakeven-витрати ≥ 12 bps (запас 1.6× над 7.5 bps);
- profit factor > 1.2 за `batch_trade_breakdown`;
- щонайменше 100 угод на монету й інтервал;
- `promotion_gate` показує `preregistered=pass`.

H3 має бути кращим за H0 на тих самих монетах. Інакше ворота нічого не додають, і
лишається H0.

## 6. Що свідомо не робилось

- **Maker/лімітні входи.** Комісії — головний важіль: у replay maker 2 bps перетворює
  +0.4k на +6.9k на BTC. Але для цього потрібна модель невиконання лімітки, без неї
  результат завищено. Окрема задача.
- **Ширший стоп і trailing.** На BTC не робастно (×1.5: +1.3k, ×2: ≈ 0). Trailing на
  3 ATR зрізає хвіст: чотири угоди понад 72 год дали +25.7k.
- **formulaic_lgbm, adaptive_ema, ema** — у тір C не входять. lgbm заморожено до
  перенавчання з мітками, що враховують комісію. adaptive_ema має сенс лише на 4h.
- **Нечутливі сітки** (regime завжди `donchian=10 bb_k=2.5`) лишились як були. Для
  преєстрованого тесту це чесно: уся сітка входить в умови й у trial-ledger.
