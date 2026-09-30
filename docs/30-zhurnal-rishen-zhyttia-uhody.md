# 30. Журнал рішень: життєвий цикл угоди в бектесті

Продовження [28-zhurnal-rishen-decision-trace.md](28-zhurnal-rishen-decision-trace.md).
Етап 1–2 плану «сторінка пакетного бектесту» (2026-09-30). Формат лишається
`decision_trace/1`: нові поля лише додаються, старі читачі їх ігнорують.

## Навіщо

Свіп 2026-09-29 (`reports/decision-sweep/`) показав прогалини, через які журнал не
відповідав на питання «чому саме так»:

| Прогалина | Наслідок |
| --- | --- |
| Рівень стопу не логувався (лише `stop_distance`) | У вікні угоди бектесту немає лінії SL, R-множник не рахується |
| Вихід по ратчету = звичайний `EXIT` | Не відрізнити вихід за сигналом від спрацювання ратчета |
| `meta_label` без `last_trace` | 1761 з 1806 записів без кроків; відхилені сигнали невидимі |
| VPIN-крок без порогу | «0 угод» у vpin_momentum не пояснюється (макс VPIN 0.62 < 0.70) |
| Бар після кожного входу = `ENTRY_BLOCKED_RISK` / `execution.order_working` | Статистика блоків завищена на 1 бар на угоду |
| `STOP_LOSS` з `regime=""` і account уже після стопу | Контекст виходу втрачено |
| `regime=UNKNOWN` у роботів без класифікатора | Дайджест показував «UNKNOWN 100%» |

## Нові outcome

| Outcome | Kind | Коли |
| --- | --- | --- |
| `ENTRY_FILLED` | intrabar | Вхідний ордер виконано: ціна, розмір, комісія, прослизання, затримка, рівень стопу |
| `PENDING_FILL` | bar | Попередній ордер ще не виконано — новий вхід не додається. Це не блок ризику |
| `SIGNAL_VETOED` | bar | Фільтр усередині робота (meta-label) відхилив свій сигнал |
| `RATCHET_EXIT` | bar | Ратчет-стоп закрив позицію |

## Нові кроки

- `execution / fill` (`result=entry_filled`): `side, qty, fill_price, decision_price,
  slippage_bps` (> 0 = гірше за close рішення), `fee`, `fill_delay_s`.
- `execution / protective_stop` (`result=stop_placed`): `stop_loss, risk_per_unit, risk_pct`.
- `plan / ratchet` на кожному барі в позиції: `stop, prior_stop, armed, close, adverse,
  dist_to_stop_pct`; `result` = `hold` | `tightened` | `exit`. На виході ще додається
  `execution / paper_broker` (`result=exit`).
- `filter / meta_label`: `p_success, primary_side, margin_pct`, поріг `threshold`;
  `verdict` = `pass` | `block`.
- `filter / vpin` (vpin_momentum і regime): `margin_pct` і поріг `toxic_threshold`.
- `gate / execution.order_working` тепер `verdict=info` з `order_id, order_side`.

`margin_pct = (значення − поріг) / |поріг| · 100` — єдина шкала «наскільки не дотягнуло»
для різних роботів (`domain/decision_trace.py::margin_pct`). Дайджест рахує фільтр із
`margin_pct ∈ [−5%, 0)` як «майже-сигнал».

## Стоп у `states.stop_loss`

Кожен бар у позиції несе `states.stop_loss` — рівень, що зараз обмежує позицію
(тісніший із захисного стопу на біржі і ратчета). Так `trade_history` без змін малює лінію
SL і бачить, як вона рухалась. `STOP_LOSS` тепер несе режим і account останнього бару
**до** стопу, `entry_price` і `gross_pnl`.

## Реконструкція угод (`application/trade_history.py`)

- `qty` береться з кроку `execution/entry` (раніше завжди 1 «припущено»).
- `ENTRY_FILLED` додає `entry_fill_price`, `entry_slippage_bps`, `entry_fill_delay_s`, `fee`;
  цей рядок є в таймлайні угоди, але не рахується як бар утримання.
- `initial_stop_loss` — стоп на момент входу; R-множник рахується від нього (ратчет, що
  підтягнув стоп до беззбитку, більше не роздуває R).
- `entry_price` навмисно лишається close бару рішення: вихід у бектесті теж оцінюється за
  close, тож PnL порівнює однакове з однаковим. Розрив до фактичного виконання видно окремо.

## Що з цього варто перевірити першим

У свіпі 29.09 після кожного входу наступний бар показував `FLAT` + «ордер уже в роботі»:
ринковий ордер у бар-бектесті виконується з затримкою приблизно на бар. `fill_delay_s` і
`slippage_bps` у `ENTRY_FILLED` покажуть, скільки це коштує кожній стратегії. Якщо
затримка систематична, це кандидат на першу «дрібницю»: вхід фактично відбувається за
ціною наступного бару, а не того, на якому з’явився сигнал.

## Ще не зроблено

- pairs (`spread_strategy.py`) і funding (`funding_strategy.py`) досі не пишуть журнал.
- Лінії індикаторів і сходинка SL на графіку угоди — етап 6 плану.
- `run_header` замість `params` у кожному записі — етап 5 (`decision_trace/2`).
