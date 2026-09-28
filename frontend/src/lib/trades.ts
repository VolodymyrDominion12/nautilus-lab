/**
 * Pure logic behind the trade pages (list + detail), shared by paper trading and backtests.
 *
 * Everything here is a function of data the API already returned: the route that a trade
 * link carries, where the entry/exit/SL/TP markers land on a candle series, which
 * indicators are worth showing side by side, and how a money number has to be labelled.
 * Keeping it out of the components is what makes it testable — `lib/trades.test.ts` runs
 * without a chart, a session or an API.
 */
import type {
  TradeChartBar,
  TradeDecisionRow,
  TradeDetail,
  TradeSummary,
} from '../services/api';
import { toNumber } from './format';

// ---- the deep link -------------------------------------------------------------------

export type TradeOrigin = 'paper' | 'backtest';

/** What a trade page needs to render on its own, straight from the URL fragment. */
export interface TradeRoute {
  session: string;
  id: string;
  /** Instrument/interval/catalog are the run's context, not the trade's: the chart needs them. */
  instrument?: string;
  interval?: string;
  catalog?: string;
  /** Human label for the header (session name or run id). */
  title?: string;
  origin?: TradeOrigin;
}

const TRADE_HASH_PREFIX = '#/trade';

/**
 * `#/trade?session=…&id=…` — a real, copyable address for one trade.
 *
 * The dashboard has no router, and adding one for a single view would rewrite every tab.
 * A hash fragment gives the page what a router was wanted for: a link that can be pasted,
 * bookmarked, opened in a new tab and reached with the browser's Back button, without a
 * round trip to the server (which has no SPA fallback route).
 */
export const buildTradeHash = (route: TradeRoute): string => {
  const params = new URLSearchParams();
  params.set('session', route.session);
  params.set('id', route.id);
  if (route.instrument) params.set('instrument', route.instrument);
  if (route.interval) params.set('interval', route.interval);
  if (route.catalog) params.set('catalog', route.catalog);
  if (route.title) params.set('title', route.title);
  if (route.origin) params.set('origin', route.origin);
  return `${TRADE_HASH_PREFIX}?${params.toString()}`;
};

/** The trade route in a location hash, or null when the fragment is something else. */
export const parseTradeHash = (hash: string): TradeRoute | null => {
  if (!hash.startsWith(TRADE_HASH_PREFIX)) return null;
  const query = hash.slice(TRADE_HASH_PREFIX.length).replace(/^\?/, '');
  const params = new URLSearchParams(query);
  const session = params.get('session');
  const id = params.get('id');
  if (!session || !id) return null;
  const origin = params.get('origin');
  return {
    session,
    id,
    instrument: params.get('instrument') ?? undefined,
    interval: params.get('interval') ?? undefined,
    catalog: params.get('catalog') ?? undefined,
    title: params.get('title') ?? undefined,
    origin: origin === 'paper' || origin === 'backtest' ? origin : undefined,
  };
};

// ---- chart geometry ------------------------------------------------------------------

/** A marker as lightweight-charts wants it, already snapped onto a candle. */
export interface TradeMarker {
  time: number;
  position: 'aboveBar' | 'belowBar' | 'inBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square';
  text: string;
}

export interface TradePriceLine {
  price: number;
  color: string;
  title: string;
  lineStyle: number;
}

/**
 * The candle a decision belongs to: the nearest bar time, within a sane distance.
 *
 * A decision carries the bar's **close** (the log stores the bar's `ts_event`, e.g.
 * `00:59:59.999` for a one-minute bar), while a chart plots a candle at the time the API
 * reports for it — and the two conventions are not the same between a live session and the
 * parquet catalog. An exact match therefore never holds, and lightweight-charts drops a
 * marker that lands on no candle without saying anything. Nearest-within-tolerance lands on
 * the candle that contains the decision under either convention, and answers `null` — not a
 * distance-inventing guess — when nothing is close enough (a trade older than the window).
 */
export const snapToBar = (timeSeconds: number, barTimes: number[]): number | null => {
  if (barTimes.length === 0) return null;
  let low = 0;
  let high = barTimes.length - 1;
  while (low < high) {
    const mid = (low + high) >> 1;
    if ((barTimes[mid] as number) < timeSeconds) low = mid + 1;
    else high = mid;
  }
  const after = barTimes[low] as number;
  const before = low > 0 ? (barTimes[low - 1] as number) : null;
  const nearest =
    before != null && Math.abs(timeSeconds - before) <= Math.abs(after - timeSeconds)
      ? before
      : after;

  const first = barTimes[0] as number;
  const last = barTimes[barTimes.length - 1] as number;
  const spacing = barTimes.length > 1 ? (last - first) / (barTimes.length - 1) : 0;
  const tolerance = spacing * 1.5;
  if (tolerance > 0 && Math.abs(timeSeconds - nearest) > tolerance) return null;
  return nearest;
};

const EXIT_COLORS: Record<string, string> = {
  STOP_LOSS: '#ef4444',
  TAKE_PROFIT: '#10b981',
  EXIT: '#38bdf8',
  FLATTEN_REGIME_CHANGE: '#a78bfa',
  MANUAL_CLOSE: '#f59e0b',
};

export const exitColor = (outcome?: string | null): string =>
  (outcome && EXIT_COLORS[outcome]) || '#3b82f6';

/** Entry, exit and the SL/TP touches, each snapped onto a candle that exists. */
export const tradeMarkers = (
  trade: Pick<
    TradeSummary,
    'side' | 'entry_time' | 'exit_time' | 'exit_outcome' | 'stop_loss' | 'take_profit'
  >,
  bars: TradeChartBar[],
): TradeMarker[] => {
  const times = bars.map((bar) => bar.time);
  const markers: TradeMarker[] = [];
  const long = trade.side !== 'SHORT';

  const entry = snapToBar(Date.parse(trade.entry_time) / 1000, times);
  if (entry != null) {
    markers.push({
      time: entry,
      position: long ? 'belowBar' : 'aboveBar',
      color: long ? '#10b981' : '#ef4444',
      shape: long ? 'arrowUp' : 'arrowDown',
      text: `Вхід ${trade.side}`,
    });
  }

  if (trade.exit_time) {
    const exit = snapToBar(Date.parse(trade.exit_time) / 1000, times);
    if (exit != null && exit !== entry) {
      markers.push({
        time: exit,
        position: long ? 'aboveBar' : 'belowBar',
        color: exitColor(trade.exit_outcome),
        shape: long ? 'arrowDown' : 'arrowUp',
        text: `Вихід ${trade.exit_outcome ?? ''}`.trim(),
      });
    }
  }
  return markers;
};

/**
 * Entry, exit, stop and target as price lines.
 *
 * The stop and the target are drawn where the trade *ended* with them, which for a
 * trailing stop is its final level, not the level it opened with — the panel notes the
 * difference instead of drawing a ratchet as a single line with no history.
 */
export const tradePriceLines = (
  trade: Pick<
    TradeSummary,
    'entry_price' | 'exit_price' | 'mark_price' | 'stop_loss' | 'take_profit' | 'status'
  >,
): TradePriceLine[] => {
  const lines: TradePriceLine[] = [
    { price: trade.entry_price, color: '#60a5fa', title: 'Вхід', lineStyle: 0 },
  ];
  const exit = toNumber(trade.exit_price ?? trade.mark_price ?? null);
  if (exit != null) {
    lines.push({
      price: exit,
      color: trade.status === 'OPEN' ? '#94a3b8' : '#e5e7eb',
      title: trade.status === 'OPEN' ? 'Поточна ціна' : 'Вихід',
      lineStyle: 0,
    });
  }
  const stop = toNumber(trade.stop_loss ?? null);
  if (stop != null) lines.push({ price: stop, color: '#ef4444', title: 'Стоп-лос', lineStyle: 2 });
  const target = toNumber(trade.take_profit ?? null);
  if (target != null) {
    lines.push({ price: target, color: '#10b981', title: 'Тейк-профіт', lineStyle: 2 });
  }
  return lines;
};

// ---- presentation --------------------------------------------------------------------

/** A number read out of the log: the writer stores indicators as strings. */
export const indicatorRows = (
  entry?: Record<string, unknown>,
  exit?: Record<string, unknown>,
): { name: string; entry: number | null; exit: number | null; delta: number | null }[] => {
  const names = new Set([...Object.keys(entry ?? {}), ...Object.keys(exit ?? {})]);
  return [...names]
    .map((name) => {
      const first = toNumber((entry ?? {})[name] as string | number | null);
      const last = toNumber((exit ?? {})[name] as string | number | null);
      return {
        name,
        entry: first,
        exit: last,
        delta: first != null && last != null ? last - first : null,
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name));
};

/**
 * How a trade's money number was produced, in words.
 *
 * A dashboard that shows `+50.00` alone invites reading it as account PnL. Each basis has
 * its own sentence: the venue's ledger, price arithmetic on an assumed size, or a mark on
 * a trade that has not closed.
 */
export const describePnlBasis = (
  trade: Pick<TradeSummary, 'pnl_source' | 'qty_known' | 'fee_known' | 'status'>,
): string => {
  const size = trade.qty_known ? '' : '; розмір позиції в журналі не записано, узято 1';
  switch (trade.pnl_source) {
    case 'fills':
      return `З журналу угод сесії (реальний розмір і комісії${trade.fee_known ? '' : ', комісію не знайдено'})`;
    case 'price_delta':
      return `Різниця цін входу й виходу${size}. Комісії не враховано: бектест не пише філи в журнал рішень`;
    case 'mark':
      return `Плаваючий результат відкритої позиції на поточній ціні${size}`;
    default:
      return trade.status === 'OPEN' ? 'Позиція відкрита' : 'Результат не пораховано';
  }
};

/** Seconds between entry and exit, as "2г 15хв" / "45с". */
export const formatDuration = (
  seconds: number | null | undefined,
  bars?: number | null,
): string => {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '—';
  const total = Math.floor(seconds);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  let text: string;
  if (days > 0) text = `${days}д ${hours}г`;
  else if (hours > 0) text = `${hours}г ${minutes}хв`;
  else if (minutes > 0) text = `${minutes}хв ${secs}с`;
  else text = `${secs}с`;
  return bars ? `${text} · ${bars} бар.` : text;
};

/** Exit and entry codes as they are read off the log, in Ukrainian. */
const OUTCOME_LABELS: Record<string, string> = {
  ENTRY_OPENED: 'Вхід за сигналом',
  REVERSE: 'Розворот',
  EXIT: 'Вихід за сигналом',
  STOP_LOSS: 'Стоп-лос',
  TAKE_PROFIT: 'Тейк-профіт',
  FLATTEN_REGIME_CHANGE: 'Закриття: зміна режиму',
  MANUAL_CLOSE: 'Ручне закриття',
  NO_SIGNAL: 'Без сигналу',
  HOLD_NOOP: 'Утримання',
  WARMUP: 'Прогрів',
  UNKNOWN_V0: 'Запис без outcome',
};

export const outcomeLabel = (outcome?: string | null): string =>
  (outcome && OUTCOME_LABELS[outcome]) || outcome || '—';

/**
 * A one-line summary of what happened in a decision, for the timeline.
 *
 * The panel shows the raw `steps` and indicator dump underneath; this is the readable line
 * a person scans, and it prefers the record's own narrative when the writer produced one.
 */
export const describeDecision = (row: TradeDecisionRow): string => {
  if (row.narrative) return row.narrative;
  const parts: string[] = [];
  if (row.signal) parts.push(`сигнал ${row.signal.toUpperCase()}`);
  if (row.regime) parts.push(`режим ${row.regime}`);
  if (row.signal_reason) parts.push(row.signal_reason);
  if (row.blocked_by) parts.push(`заблоковано: ${row.blocked_by}`);
  return parts.join(' · ') || outcomeLabel(row.outcome);
};

/** Decisions whose outcome changed the position, i.e. the rows worth highlighting. */
export const isPivotalDecision = (row: TradeDecisionRow): boolean =>
  Boolean(row.outcome && row.outcome !== 'HOLD_NOOP' && row.outcome !== 'NO_SIGNAL');

/** A backtest log carries no `bar`/`narrative` and no `steps`: the page says so instead of
 * rendering empty sections that look like a robot that decided nothing. */
export const describeMissingDetail = (trade: Pick<TradeDetail, 'decisions'>): string | null => {
  const rows = trade.decisions ?? [];
  if (rows.length === 0) return 'У журналі немає жодного запису про цю угоду.';
  const withSteps = rows.filter((row) => (row.steps ?? []).length > 0).length;
  if (withSteps === 0) {
    return (
      'Жоден запис не містить ланцюжка рішень (`steps`): ці записи написано до того, ' +
      'як бектест почав писати повний ланцюжок, тому нижче видно індикатори й outcome, ' +
      'але не покрокові вердикти фільтрів.'
    );
  }
  return null;
};
