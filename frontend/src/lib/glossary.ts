/**
 * Centralized glossary of quantitative trading, validation metrics,
 * parameters, and system module descriptions for Nautilus Lab.
 *
 * Professional dual-language style: standard quant terms retained in English,
 * explanations and practical guidelines written in Ukrainian.
 */

export interface GlossaryEntry {
  title: string;
  subtitle?: string;
  formula?: string;
  description: string;
  interpretation?: string;
  importance?: 'critical' | 'high' | 'medium';
  category: 'metric' | 'methodology' | 'parameter' | 'module' | 'safety';
}

export type GlossaryKey =
  | 'oos_return'
  | 'is_return'
  | 'buy_and_hold'
  | 'excess_return'
  | 'profitable_folds'
  | 'breakeven_cost'
  | 'paid_cost_rate'
  | 'cost_headroom'
  | 'pbo'
  | 'cscv'
  | 'deflated_sharpe'
  | 'haircut_sharpe'
  | 'max_drawdown'
  | 'total_fills'
  | 'walk_forward'
  | 'folds'
  | 'is_fraction'
  | 'embargo_bars'
  | 'lookahead_bias'
  | 'optuna_trials'
  | 'fail_closed'
  | 'command_center'
  | 'research_lab'
  | 'parquet_catalog'
  | 'strategy_specs'
  | 'ml_pipeline'
  | 'experiment_journal'
  | 'paper_trading'
  | 'arb_scanner'
  | 'alpha_ideas';

export const GLOSSARY: Record<GlossaryKey, GlossaryEntry> = {
  // --- METRICS ---
  oos_return: {
    title: 'Out-of-Sample (OOS) Return',
    subtitle: 'Позавіконна дохідність (Єдиний валідний звіт)',
    formula: 'R_oos = (Equity_end / Equity_start) - 1',
    description:
      'Середня або кумулятивна прибутковість стратегії на незалежних даних, які модель НЕ бачила під час підбору параметрів (In-Sample).',
    interpretation:
      'Лише це число показує справжню прогнозну силу стратегії. Позитивний OOS має обовʼязково порівнюватись із Buy&Hold за той самий період.',
    importance: 'critical',
    category: 'metric',
  },
  is_return: {
    title: 'In-Sample (IS) Return',
    subtitle: 'Внутрішньовіконна дохідність (Лише вибір параметрів)',
    formula: 'R_is = Maximize(Objective(params)) on Train Window',
    description:
      'Прибутковість на періоді оптимізації/тренування. Використовується рушієм виключно для вибору найкращої конфігурації параметрів.',
    interpretation:
      'УВАГА: Високий IS Return ніколи не є результатом або досягненням! Зазвичай він завищений через підгонку під історичні дані (curve-fitting).',
    importance: 'critical',
    category: 'metric',
  },
  buy_and_hold: {
    title: 'Buy & Hold Baseline',
    subtitle: 'Базова дохідність пасивного утримання активу',
    formula: 'R_bh = (Price_end / Price_start) - 1',
    description:
      'Результат пасивної купівлі та утримання базового активу за той самий OOS-інтервал часу.',
    interpretation:
      'Якщо стратегія заробила +10%, але ринок виріс на +30%, стратегія насправді втратила відносно ринку. Справжня перевага існує лише коли результат вищий за Buy & Hold.',
    importance: 'high',
    category: 'metric',
  },
  excess_return: {
    title: 'Excess Return (Alpha)',
    subtitle: 'Надлишкова прибутковість над ринком (Чиста альфа)',
    formula: 'Excess = R_oos - R_buy_and_hold',
    description:
      'Різниця між прибутковістю стратегії на OOS та прибутковістю пасивного ринку (Buy & Hold).',
    interpretation:
      '> 0: стратегія генерує додану вартість (альфу).\n≤ 0: стратегія поступається простому утриманню активу або зазнає збитків.',
    importance: 'critical',
    category: 'metric',
  },
  profitable_folds: {
    title: 'Profitable Folds Ratio',
    subtitle: 'Частка прибуткових часових вікон (Стабільність у часі)',
    formula: 'Ratio = Count(Fold_OOS > 0) / Total_Folds',
    description:
      'Скільки окремих незалежних Out-of-Sample інтервалів завершились у плюсі.',
    interpretation:
      'Захист від випадкових викидів: середній плюс може створити один вдалий місяць при 5 збиткових. Справжня надійна стратегія має прибутковість у більшості фолдів (наприклад, ≥ 60-70%).',
    importance: 'high',
    category: 'metric',
  },
  breakeven_cost: {
    title: 'Breakeven Cost Rate',
    subtitle: 'Точка беззбитковості по комісіях та прослизанню',
    formula: 'Breakeven = Total_Gross_PnL / Total_Traded_Volume (в базисних пунктах bps)',
    description:
      'Максимальна комісія біржі та прослизання (slippage), за якої стратегія ще не стає збитковою. 1 bps = 0.01% = 0.0001.',
    interpretation:
      'Якщо Breakeven нижчий за реальні торгові комісії (Maker ~2 bps, Taker ~5 bps), стратегія буде гарантовано збитковою в реальності через витрати на транзакції.',
    importance: 'high',
    category: 'metric',
  },
  paid_cost_rate: {
    title: 'Paid Cost Rate',
    subtitle: 'Фактичні враховані торгові комісії',
    formula: 'Cost_paid = Total_Fees / Traded_Volume (в bps)',
    description:
      'Середній розмір комісій, списаних біржовим симулятором за здійснені операції (мейкер/тейкер з урахуванням налаштувань оточення).',
    interpretation:
      'За замовчуванням у Nautilus Lab задано 2 bps (0.02%) для maker та 5 bps (0.05%) для taker.',
    importance: 'medium',
    category: 'metric',
  },
  cost_headroom: {
    title: 'Cost Headroom',
    subtitle: 'Запас міцності проти комісій та прослизання',
    formula: 'Headroom = Breakeven_Cost - Paid_Cost_Rate (в bps)',
    description:
      'Резерв прибутковості після сплати всіх торгових зборів.',
    interpretation:
      '> 0: стратегія виживає реальні біржові комісії.\n< 0: стратегія «зʼїдається» комісіями (churning / over-trading).',
    importance: 'critical',
    category: 'metric',
  },
  pbo: {
    title: 'PBO (Probability of Backtest Overfitting)',
    subtitle: 'Ймовірність перенавчання бектесту (метод Бейлі та Лопеса де Прадо)',
    formula: 'PBO = P(Rank_OOS(best_IS) < Median)',
    description:
      'Ймовірність того, що конфігурація параметрів, яка показала найкращий результат на тренуванні (IS), на тестових даних (OOS) виявиться гіршою за медіану всіх конфігурацій.',
    interpretation:
      '< 0.5 (< 50%): процедура відбору краща за випадковий вибір.\n≥ 0.5 (≥ 50%): відбір параметрів не має прогнозної сили (ефект підкидання монети). Модель підігнана під шум.',
    importance: 'critical',
    category: 'metric',
  },
  cscv: {
    title: 'CSCV (Combinatorially Symmetric Cross-Validation)',
    subtitle: 'Комбінаторна симетрична крос-валідація',
    formula: 'C(S, S/2) комбінацій розбиття історії на блоки',
    description:
      'Математична техніка розбиття часового ряду на рівні блоки та генерації всіх парних комбінацій тренувальних і тестових вибірок без порушення структури даних.',
    interpretation:
      'Дозволяє отримати емпіричний розподіл відносного рангу найкращої моделі та точно порахувати PBO.',
    importance: 'high',
    category: 'methodology',
  },
  deflated_sharpe: {
    title: 'Deflated Sharpe Ratio (DSR)',
    subtitle: 'Дефльований коефіцієнт Шарпа (Поправка на множинне тестування)',
    formula: 'DSR = P(Sharpe > 0 | N_trials, Var(Sharpe), Skewness, Kurtosis)',
    description:
      'Статистична ймовірність того, що знайдений коефіцієнт Шарпа дійсно позитивний, з поправкою на кількість перевірених спроб/сіток параметрів (data snooping bias).',
    interpretation:
      '> 0.95: висока статистична достовірність (p-value < 0.05).\n< 0.95: високий ризик, що гарний Шарп знайдено випадково серед сотень перевірених комбінацій.',
    importance: 'high',
    category: 'metric',
  },
  haircut_sharpe: {
    title: 'Haircut Sharpe Ratio',
    subtitle: 'Скоригований (урізаний) коефіцієнт Шарпа',
    formula: 'Sharpe_haircut = Sharpe_observed * (1 - Haircut_penalty)',
    description:
      'Штраф Харві-Лю, що зменшує очікуваний коефіцієнт Шарпа на основі кількості протестованих факторів і тривалості спостереження.',
    interpretation:
      'Реалістична оцінка майбутнього Шарпа в бойових умовах з урахуванням неминучої деградації альфи.',
    importance: 'medium',
    category: 'metric',
  },
  max_drawdown: {
    title: 'Max Drawdown (MDD)',
    subtitle: 'Максимальне просідання капіталу від піку',
    formula: 'MDD = Max((Peak_Equity - Trough_Equity) / Peak_Equity)',
    description:
      'Найглибше падіння кривої капіталу від історичного максимуму до локального мінімуму за досліджуваний період.',
    interpretation:
      'Ключова метрика ризику ліквідації та психологічного навантаження. Звертайте увагу, чи виміряно це на OOS (чесно) чи лише на IS.',
    importance: 'high',
    category: 'metric',
  },
  total_fills: {
    title: 'Total Fills (Trades)',
    subtitle: 'Кількість виконаних біржових угод',
    formula: 'Count(Executed Orders)',
    description:
      'Сумарне число виконань угод за період симуляції.',
    interpretation:
      'Якщо fills = 0: стратегія не відкрила жодної позиції (перевірте фільтри та індикатори).\nЯкщо fills занадто мале (< 30): статистично недостатня вибірка для висновків.\nЯкщо fills занадто велике: ризик перевитрат на спреди та комісії.',
    importance: 'medium',
    category: 'metric',
  },

  // --- METHODOLOGY & PARAMETERS ---
  walk_forward: {
    title: 'Walk-Forward Validation',
    subtitle: 'Ковзна валідація часових рядів',
    description:
      'Стандарт валідації у квант-фінансах: історія ділиться на послідовні вікна. У кожному вікні перша частина (In-Sample) служить для вибору параметрів, а наступна (Out-of-Sample) — для незалежного вимірювання результату.',
    interpretation:
      'Імітує роботу трейдера в реальному часі: налаштовуємо робота на минулих даних, запускаємо на майбутніх, потім пересуваємо вікно вперед.',
    importance: 'critical',
    category: 'methodology',
  },
  folds: {
    title: 'Folds (Часові сегменти)',
    subtitle: 'Кількість вікон розбиття історії',
    description:
      'Параметр --folds N (за замовчуванням 2 або більше). Визначає, на скільки окремих незалежних сегментів нарізається весь Parquet-каталог даних.',
    interpretation:
      'Більше фолдів (наприклад 4 або 6) дають кращу оцінку стійкості стратегії до різних ринкових фаз (бичачий, ведмежий, флет).',
    importance: 'high',
    category: 'parameter',
  },
  is_fraction: {
    title: 'In-Sample Fraction',
    subtitle: 'Частка вікна для оптимізації (Train split)',
    formula: 'IS_bars = Total_Window_Bars * Fraction (напр. 0.7 = 70%)',
    description:
      'Яка частина кожного фолду виділяється на навчання/вибір параметрів. Решта (1 - Fraction) стає Out-of-Sample для тесту.',
    interpretation:
      'Типове значення 0.7 (70% навчання, 30% перевірка). Дозволяє збалансувати глибину історії для калібрування індикаторів та достатність вибірки для тесту.',
    importance: 'medium',
    category: 'parameter',
  },
  embargo_bars: {
    title: 'Embargo & Purging Bars',
    subtitle: 'Захисний барʼєр між тренуванням та тестом',
    description:
      'Кількість барів, що навмисно викидаються між закінченням In-Sample та початком Out-of-Sample.',
    interpretation:
      'КРИТИЧНО для запобігання Lookahead Bias: якщо угода була відкрита наприкінці IS і закрилася на OOS, або індикатор має період усереднення (EMA, ATR), дані можуть «перетікати» з майбутнього в минуле. Ембарго ліквідує цей витік.',
    importance: 'critical',
    category: 'methodology',
  },
  lookahead_bias: {
    title: 'Lookahead Bias (Витік інформації з майбутнього)',
    subtitle: 'Найбільша пастка кількісних бектестів',
    description:
      'Помилка, коли алгоритм під час симуляції отримує доступ до цін чи сигналів, які ще не були відомі в той момент часу.',
    interpretation:
      'Nautilus Lab запобігає цьому: використання виключно закритих барів (RollingWindow.prior()), суворе ембарго та заборона використання OOS для вибору параметрів.',
    importance: 'critical',
    category: 'safety',
  },
  optuna_trials: {
    title: 'Optuna Bayesian Optimization',
    subtitle: 'Байєсівський підбір гіперпараметрів',
    description:
      'Розумний пошук найкращих параметрів робота через Tree-structured Parzen Estimator (TPE) замість сліпої регулярної сітки (Grid Search).',
    interpretation:
      'Дозволяє ефективно дослідити великий простір параметрів за меншу кількість ітерацій (trials). Застосовується виключно на In-Sample!',
    importance: 'medium',
    category: 'parameter',
  },
  fail_closed: {
    title: 'Fail-Closed Safety Mode',
    subtitle: 'Апаратний захист капіталу в дослідному середовищі',
    description:
      'Принцип безпеки, закладений в архітектуру: команда «lab live» свідомо викидає помилку із кодом 1, реальний адаптер виконання відсутній.',
    interpretation:
      'Гарантує, що жоден експериментальний код або тестовий скрипт не зможе відправити реальні фінансові ордери на біржу. Дослідження залишаються безпечними.',
    importance: 'critical',
    category: 'safety',
  },

  // --- MODULES ---
  command_center: {
    title: 'Command Center (Головний огляд)',
    subtitle: 'Пульт моніторингу лабораторії',
    description:
      'Центральний екран: показує чесний статус останнього бектесту, активні фонові процеси, свіжість каталогу даних та історію останніх гіпотез.',
    importance: 'high',
    category: 'module',
  },
  research_lab: {
    title: 'Research & Backtest Lab',
    subtitle: 'Лабораторія запуску валідацій',
    description:
      'Інтерфейс для конфігурації та запуску Walk-Forward тестів, вибору роботів (Regime, EMA, Pairs, VPIN тощо), налаштування фолдів та аудиту PBO.',
    importance: 'critical',
    category: 'module',
  },
  parquet_catalog: {
    title: 'Parquet Catalog (Каталог даних)',
    subtitle: 'Локальне сховище історичних барів',
    description:
      'Керування збереженими klines з публічного API Binance (1m/5m/1h) у високоефективному бінарному форматі Apache Parquet.',
    importance: 'high',
    category: 'module',
  },
  strategy_specs: {
    title: 'Strategy Specs (Специфікації роботів)',
    subtitle: 'Spec-Driven Development контроль',
    description:
      'Каталог специфікацій стратегій (`specs/strategies/*.yaml`). Відображає статус готовності робота (`candidate`, `validated`, `rejected`), джерело сітки параметрів та підключення до бектесту.',
    importance: 'high',
    category: 'module',
  },
  ml_pipeline: {
    title: 'ML Pipeline (Машинне навчання)',
    subtitle: 'Мікроструктурні моделі LightGBM',
    description:
      'Модуль тренування моделей прогнозування напрямку ринку на базі технічних та ордербук-фіч із застосуванням Purged K-Fold крос-валідації та аналізом важливості ознак (Feature Importance).',
    importance: 'high',
    category: 'module',
  },
  experiment_journal: {
    title: 'Experiment Journal (Журнал експериментів)',
    subtitle: 'Kanban-дошка прогресу гіпотез',
    description:
      'Фіксація всіх проведених досліджень: що було перевірено, які параметри спрацювали, які відхилено через перенавчання чи комісії.',
    importance: 'medium',
    category: 'module',
  },
  paper_trading: {
    title: 'Trading Terminal & Paper Simulator',
    subtitle: 'Симуляція виконання замовлень у реальному часі',
    description:
      'Тестування стратегій на потоці реальних ринкових котирувань через WebSocket без фінансового ризику.',
    importance: 'high',
    category: 'module',
  },
  arb_scanner: {
    title: 'Arbitrage Scanner (Сканер арбітражу)',
    subtitle: 'Пошук міжбіржових та трикутних спредів',
    description:
      'Моніторинг розбіжностей цін між парами (Cross-pair / Triangular) та фандингових ставок на деривативах.',
    importance: 'medium',
    category: 'module',
  },
  alpha_ideas: {
    title: 'Alpha Ideas (Генератор альфа-гіпотез)',
    subtitle: 'Офлайн-генератор торгових формул',
    description:
      'Інструмент розробки формульних сигналів та математичних виразів (Alpha 101 тощо) для наступного тестування у Research Lab.',
    importance: 'medium',
    category: 'module',
  },
};
