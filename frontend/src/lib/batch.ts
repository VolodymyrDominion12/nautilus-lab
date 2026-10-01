/**
 * Pure logic of the batch-backtest pages: the hash routes, the table rows' shape and their
 * sorting. The components only draw; `lib/batch.test.ts` checks this without a browser.
 *
 * Routes (the dashboard has no router; `lib/trades.ts` explains why a fragment is enough):
 *   #/batch                    — batch list + launch form
 *   #/batch/<batchId>          — the table of runs of one batch
 *   #/run/<batchId>/<cellId>   — one run: folds, trades, decisions, analysis
 */

import { formatDateTime } from './format';

export type BatchRoute =
  | { page: 'list' }
  | { page: 'batch'; batchId: string }
  | { page: 'run'; batchId: string; cellId: string; fold?: number; tab?: RunTab };

export type RunTab = 'trades' | 'decisions' | 'analysis' | 'log';

const RUN_TABS: RunTab[] = ['trades', 'decisions', 'analysis', 'log'];
const ID = /^[A-Za-z0-9_-]{1,120}$/;

export const buildBatchHash = (route: BatchRoute): string => {
  if (route.page === 'list') return '#/batch';
  if (route.page === 'batch') return `#/batch/${route.batchId}`;
  const params = new URLSearchParams();
  if (route.fold != null) params.set('fold', String(route.fold));
  if (route.tab) params.set('tab', route.tab);
  const query = params.toString();
  return `#/run/${route.batchId}/${route.cellId}${query ? `?${query}` : ''}`;
};

/** The batch route in a location hash, or null when the fragment is something else. */
export const parseBatchHash = (hash: string): BatchRoute | null => {
  const [path, query = ''] = hash.replace(/^#/, '').split('?');
  const parts = (path ?? '').split('/').filter(Boolean);
  if (parts[0] === 'batch') {
    if (parts.length === 1) return { page: 'list' };
    if (parts.length === 2 && ID.test(parts[1] as string)) {
      return { page: 'batch', batchId: parts[1] as string };
    }
    return null;
  }
  if (parts[0] === 'run' && parts.length === 3) {
    const [, batchId, cellId] = parts as [string, string, string];
    if (!ID.test(batchId) || !ID.test(cellId)) return null;
    const params = new URLSearchParams(query);
    const foldRaw = params.get('fold');
    const fold = foldRaw != null && /^\d+$/.test(foldRaw) ? Number(foldRaw) : undefined;
    const tabRaw = params.get('tab') as RunTab | null;
    const tab = tabRaw && RUN_TABS.includes(tabRaw) ? tabRaw : undefined;
    return { page: 'run', batchId, cellId, fold, tab };
  }
  return null;
};

// ---- API shapes -----------------------------------------------------------------------

export interface BatchListRow {
  id: string;
  label: string;
  created_at: string | null;
  finished_at?: string | null;
  /** When this batch was last wiped and re-run in place; absent = never. */
  restarted_at?: string | null;
  restart_count?: number | null;
  status: string;
  cells: number;
  counts: Record<string, number>;
  robots: string[];
  symbols: string[];
  imported_from?: string | null;
}

export interface FoldRef {
  index: number;
  session_id: string;
  window: {
    in_sample_start?: string;
    in_sample_end?: string;
    out_of_sample_start?: string;
    out_of_sample_end?: string;
  };
  oos_return_raw?: string | null;
  buy_and_hold_return_raw?: string | null;
  fills?: number;
  selected?: string;
}

export interface BatchRow {
  cell_id: string;
  robot: string;
  symbol: string;
  instrument_id: string;
  interval: string;
  catalog: string;
  status: string;
  error?: string | null;
  numbers?: {
    profitable?: string | null;
    fold_count?: number | null;
    mean_oos?: number | null;
    worst_oos?: number | null;
    buy_and_hold_mean?: number | null;
    mean_excess?: number | null;
    beats_buy_and_hold?: boolean | null;
    total_oos_fills?: number | null;
    mean_paid_cost_rate?: number | null;
    mean_breakeven_cost?: number | null;
  };
  folds?: FoldRef[];
  decisions?: {
    records: number;
    bars: number;
    untraced_bars: number;
    in_position_pct: number | null;
    outcomes: Record<string, number>;
    blocked_by: Record<string, number>;
    regime_share_pct: Record<string, number>;
    near_misses: number;
    bar_seq_gaps: number;
  };
  trades?: {
    trades: number;
    closed: number;
    win_rate: number | null;
    avg_r: number | null;
    avg_slippage_bps: number | null;
    exits: Record<string, number>;
  };
}

export interface BatchDetail {
  id: string;
  label: string;
  created_at: string | null;
  finished_at?: string | null;
  status: string;
  note?: string;
  imported_from?: string | null;
  request: Record<string, unknown>;
  rows: BatchRow[];
}

export interface PlannedCell {
  cell_id: string;
  robot: string;
  symbol: string;
  interval: string;
  catalog: string;
  runnable: boolean;
  blocked: string | null;
}

// ---- table helpers --------------------------------------------------------------------

export type SortKey =
  | 'cell'
  | 'mean_oos'
  | 'worst_oos'
  | 'excess'
  | 'trades'
  | 'win_rate'
  | 'blocked';

/** The number a column sorts on; missing values sort last whatever the direction. */
export const sortValue = (row: BatchRow, key: SortKey): number | string | null => {
  switch (key) {
    case 'cell':
      return row.cell_id;
    case 'mean_oos':
      return row.numbers?.mean_oos ?? null;
    case 'worst_oos':
      return row.numbers?.worst_oos ?? null;
    case 'excess':
      return row.numbers?.mean_excess ?? null;
    case 'trades':
      return row.trades?.closed ?? null;
    case 'win_rate':
      return row.trades?.win_rate ?? null;
    case 'blocked':
      return blockedShare(row);
    default:
      return null;
  }
};

export const sortRows = (rows: BatchRow[], key: SortKey, descending: boolean): BatchRow[] =>
  [...rows].sort((a, b) => {
    const left = sortValue(a, key);
    const right = sortValue(b, key);
    if (left == null && right == null) return 0;
    if (left == null) return 1;
    if (right == null) return -1;
    const order = left < right ? -1 : left > right ? 1 : 0;
    return descending ? -order : order;
  });

/** Share of bars whose wanted entry was refused (risk, size, pause), 0..1. */
export const blockedShare = (row: BatchRow): number | null => {
  const decisions = row.decisions;
  if (!decisions || !decisions.bars) return null;
  const blocked = Object.entries(decisions.outcomes)
    .filter(([outcome]) => outcome.startsWith('ENTRY_BLOCKED') || outcome.startsWith('ENTRY_SKIPPED'))
    .reduce((sum, [, count]) => sum + count, 0);
  return blocked / decisions.bars;
};

/** The top `n` entries of a count map as "KEY×n" text, largest first. */
export const topCounts = (counts: Record<string, number> | undefined, n = 3): string =>
  Object.entries(counts ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
    .map(([key, count]) => `${key}×${count}`)
    .join(', ') || '—';

/**
 * Warnings a row deserves before anyone reads its numbers: the log does not explain the
 * bars, the robot never traded, or most wanted entries were refused by the risk layer.
 */
export const rowWarnings = (row: BatchRow): string[] => {
  const warnings: string[] = [];
  const decisions = row.decisions;
  if (decisions && decisions.bars > 0 && decisions.untraced_bars / decisions.bars > 0.5) {
    warnings.push('журнал без кроків: робот не пояснює рішення');
  }
  if (decisions && decisions.records === 0 && row.status === 'ok') {
    warnings.push('журнал рішень порожній');
  }
  if (row.numbers && (row.numbers.total_oos_fills ?? 0) === 0 && row.status === 'ok') {
    warnings.push('0 угод за всі фолди');
  }
  const share = blockedShare(row);
  if (share != null && share > 0.2) {
    warnings.push(`${Math.round(share * 100)}% барів — вхід заблоковано`);
  }
  return warnings;
};

export const STATUS_CLASS: Record<string, string> = {
  ok: 'text-emerald-400',
  running: 'text-amber-300',
  queued: 'text-gray-400',
  failed: 'text-red-400',
  blocked: 'text-gray-500',
  cancelled: 'text-gray-500',
  lost: 'text-red-300',
};

// ---- restarting a batch ---------------------------------------------------------------

/**
 * Why this batch cannot be re-run from the list, or null when it can.
 *
 * The rule mirrors the API's refusals, because a button that lets the backend say "no"
 * teaches the researcher nothing: an imported sweep keeps no runnable request, and a
 * batch that is still moving has to be cancelled before it can be started over (`POST
 * /api/batches/{id}/restart` answers 422 and 409 respectively).
 */
export const restartBlockedReason = (batch: BatchListRow): string | null => {
  if (batch.imported_from) {
    return 'імпортований пакет не має запиту для повторного прогону — запустіть новий';
  }
  if (batch.status === 'running' || batch.status === 'queued') {
    return 'пакет ще виконується: спершу скасуйте його';
  }
  return null;
};

/** The note under "Створено": that this batch was wiped and re-run in place, and when. */
export const restartHint = (batch: BatchListRow): string | null => {
  if (!batch.restarted_at) return null;
  const count = batch.restart_count ?? 1;
  const when = formatDateTime(batch.restarted_at);
  return count > 1 ? `перезапущено ${count}× · ${when}` : `перезапущено ${when}`;
};
