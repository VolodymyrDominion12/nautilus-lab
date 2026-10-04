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

/** One configuration the in-sample search ran (`application/dtos.py::CandidateScore`). */
export interface CandidateScore {
  label: string;
  /** What the search ranked by; `null` for an Optuna trial, which keeps no per-trial params. */
  score: number | null;
  in_sample_return: number | null;
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
  /** Every candidate the fold's in-sample search ran, best first. */
  candidates?: CandidateScore[];
  candidates_tried?: number | null;
  /** `pnl` | `sharpe` | `calmar` — a score means nothing without the metric it ranks by. */
  selection_metric?: string;
}

export interface GateCheck {
  name: string;
  /** `pass` | `fail` | `not measured` — an unmeasured check is never a pass. */
  status: string;
  detail: string;
}

/**
 * The promotion gate as data (`application/promotion_gate.py`).
 *
 * A batch cell never runs the overfitting audit, so `pbo`/`dsr` read `not measured` and
 * the best label a cell can reach is `INCOMPLETE`. That is the honest answer, and it is
 * the reason a candidate still has to be re-run in the Research tab with `--pbo`.
 */
export interface GateVerdict {
  label: 'PROMOTE' | 'REJECT' | 'INCOMPLETE' | string;
  promoted: boolean;
  summary_line: string;
  checks: GateCheck[];
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
  gate?: GateVerdict | null;
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

/** How far a batch is and how long the rest may take (`batch_store.batch_progress`). */
export interface BatchProgress {
  total: number;
  finished: number;
  remaining: number;
  counts: Record<string, number>;
  /** Mean duration of the cells that finished; null until one has. */
  mean_cell_seconds: number | null;
  elapsed_seconds: number | null;
  /** A guess from finished cells, and absent (null) until there is a basis for one. */
  eta_seconds: number | null;
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
  progress?: BatchProgress;
}

export interface PlannedCell {
  cell_id: string;
  robot: string;
  symbol: string;
  /** The instrument the cell will actually read (`BTCUSDT-PERP.SIM` for funding's perp leg). */
  instrument_id?: string;
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
  | 'headroom'
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
    case 'headroom':
      if (row.numbers?.mean_breakeven_cost == null || row.numbers?.mean_paid_cost_rate == null) {
        return null;
      }
      return row.numbers.mean_breakeven_cost - row.numbers.mean_paid_cost_rate;
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

/** Why a retry is refused, or null when the failed cells can be run again (docs/35 §1 B-4). */
export const retryBlockedReason = (batch: BatchListRow): string | null => {
  if (batch.imported_from) {
    return 'імпортований пакет не має запиту для повторного прогону — запустіть новий';
  }
  if (batch.status === 'running' || batch.status === 'queued') {
    return 'пакет ще виконується: спершу скасуйте його';
  }
  const retryable = (batch.counts?.failed ?? 0) + (batch.counts?.cancelled ?? 0);
  if (retryable === 0) {
    return 'немає клітинок без результату — «Перезапустити» проганяє всю матрицю';
  }
  return null;
};

/** `2 год 05 хв` from seconds; the batch page shows time, not a float. */
export const formatDuration = (seconds: number | null): string => {
  if (seconds == null) return '—';
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours > 0) return `${hours} год ${String(minutes).padStart(2, '0')} хв`;
  if (minutes > 0) return `${minutes} хв ${String(total % 60).padStart(2, '0')} с`;
  return `${total} с`;
};

/** The note under "Створено": that this batch was wiped and re-run in place, and when. */
export const restartHint = (batch: BatchListRow): string | null => {
  if (!batch.restarted_at) return null;
  const count = batch.restart_count ?? 1;
  const when = formatDateTime(batch.restarted_at);
  return count > 1 ? `перезапущено ${count}× · ${when}` : `перезапущено ${when}`;
};

// ---- variants (hypotheses) ------------------------------------------------------------

/** One hypothesis of the matrix: a name plus the settings it changes (`batch_plan.py`). */
export interface BatchVariant {
  name: string;
  env: Record<string, string>;
}

const VARIANT_NAME = /^[A-Za-z0-9_-]{1,24}$/;

/**
 * Parse the variants textarea into named override sets.
 *
 * The format mirrors the single `KEY=value` box next to it, with a header per hypothesis,
 * because the alternative (a row builder) hides what is actually sent:
 *
 *     [H0]
 *     REGIME_LEGS=uptrend,downtrend
 *     [H1]
 *     REGIME_LEGS=uptrend,downtrend
 *     ENTRY_FILTER_HTF_TREND=true
 *
 * Returns an error message instead of a partial list: a half-understood matrix is worse
 * than a refused one, and the batch runs for hours before anyone looks again.
 */
export const parseVariants = (
  text: string,
): { variants: BatchVariant[]; error: string | null } => {
  const variants: BatchVariant[] = [];
  let current: BatchVariant | null = null;
  const lines = text.split('\n');
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim();
    const where = `рядок ${index + 1}`;
    if (!line || line.startsWith('#')) continue;
    const header = /^\[(.+)\]$/.exec(line);
    if (header) {
      const name = header[1].trim();
      if (!VARIANT_NAME.test(name)) {
        return {
          variants: [],
          error: `${where}: ім'я варіанта «${name}» має бути з літер, цифр, «_» або «-» (до 24 символів)`,
        };
      }
      if (variants.some((item) => item.name === name)) {
        return { variants: [], error: `${where}: варіант «${name}» уже оголошено` };
      }
      current = { name, env: {} };
      variants.push(current);
      continue;
    }
    const split = line.indexOf('=');
    if (split <= 0) {
      return { variants: [], error: `${where}: очікую [НАЗВА] або KEY=value, а не «${line}»` };
    }
    if (current === null) {
      return { variants: [], error: `${where}: спершу оголоси варіант рядком [НАЗВА]` };
    }
    const key = line.slice(0, split).trim();
    const value = line.slice(split + 1).trim();
    if (!/^[A-Z][A-Z0-9_]*$/.test(key)) {
      return { variants: [], error: `${where}: «${key}» не схоже на назву налаштування` };
    }
    current.env[key] = value;
  }
  const empty = variants.find((variant) => Object.keys(variant.env).length === 0);
  if (empty) {
    return { variants: [], error: `варіант «${empty.name}» не змінює жодного налаштування` };
  }
  return { variants, error: null };
};

/** The variant name inside a cell id (`regime_BTC__H1`), or null for a plain batch. */
export const variantOfCell = (cellId: string): string | null => {
  const at = cellId.indexOf('__');
  return at >= 0 ? cellId.slice(at + 2) : null;
};
