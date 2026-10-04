import { apiUrl } from '../config';
import { withWsToken } from '../lib/apiAuth';
import type {
  BatchDetail,
  BatchListRow,
  BatchRow,
  BatchVariant,
  CandidateScore,
  FoldRef,
  PlannedCell,
} from '../lib/batch';
import type {
  ActionResult,
  CatalogBarPoint,
  CatalogBarsResponse,
  CatalogInstrument,
  CatalogResponse,
  CatalogSummary,
  CatalogsResponse,
  JobLogResponse,
  JobState,
  MlModelInfo,
  MlModelsResponse,
  ReportItem,
  ReportsResponse,
  SettingField,
  SettingGroup,
  SettingsResponse,
  SettingsSchemaResponse,
  StatusResponse,
  StrategiesResponse,
  StrategyParam,
  StrategySpec,
  StressSliceInfo,
} from './api.gen';

// Response types generated from the API's Pydantic models (api.gen.ts, docs/27 E-2.3).
// Re-exported so components keep importing from here; the rest move over route by route.
export type {
  ActionResult,
  CatalogBarPoint,
  CatalogBarsResponse,
  CatalogInstrument,
  CatalogResponse,
  CatalogSummary,
  CatalogsResponse,
  JobLogResponse,
  JobState,
  MlModelInfo,
  MlModelsResponse,
  ReportItem,
  ReportsResponse,
  SettingField,
  SettingGroup,
  SettingsResponse,
  SettingsSchemaResponse,
  StatusResponse,
  StrategiesResponse,
  StrategyParam,
  StrategySpec,
  StressSliceInfo,
};

export type JobKey = keyof StatusResponse['jobs'];


export interface ResearchRunParams {
  robot: string;
  source: 'catalog' | 'synthetic';
  bars?: number;
  days?: number;
  folds?: number;
  is_fraction?: number;
  embargo_bars?: number;
  use_optuna?: boolean;
  optuna_trials?: number;
  pbo?: boolean;
  pbo_blocks?: number;
  bar_vpin?: boolean;
  /** Reads the aggregated-trade series; refused when the catalog has none. */
  tick_vpin?: boolean;
  /** Hawkes self-exciting intensity from the same tick series. */
  hawkes?: boolean;
  stress_slice?: string;
  generate_tearsheet?: boolean;
  journal?: boolean;
  notify?: boolean;
  full_sample?: boolean;
  catalog_path?: string;
  instrument_id?: string;
  bar_interval?: string;
  /** Hypothesis text: pre-register this walk-forward before running it. */
  register?: string;
  /** Candidate mode: run the PBO/CSCV audit as well and judge the gate on both halves. */
  promote?: boolean;
  is_start?: string;
  is_end?: string;
  oos_start?: string;
  oos_end?: string;
  param_overrides?: Record<string, string>;
}

export interface HistoryEntry {
  history_id: string;
  robot: string;
  run_type: string;
  finished_at?: string;
  archived_at?: string;
  report_label?: string;
  source?: string;
  is_error?: boolean;
  starting_equity?: number | null;
  tearsheet_url?: string | null;
  multi_window?: MultiWindowSummary | null;
  walk_forward?: WalkForwardSummary | null;
  single_backtest?: SingleBacktestSummary | null;
  pbo?: PboSummary | null;
  config?: ResearchRunConfig;
}

export interface BacktestCosts {
  /** Two-sided traded notional. `turnover` is entry-only, so it cannot carry a cost rate. */
  traded_notional: number | null;
  /** Largest constant fee per unit of traded notional that leaves PnL at zero. */
  breakeven_cost: number | null;
  paid_cost_rate: number | null;
  /** `breakeven - paid`. Negative means the result only worked because execution was cheap. */
  cost_headroom: number | null;
}

export interface FoldSummary {
  index: number;
  oos_return: string;
  oos_return_raw: string | null;
  buy_and_hold_return: string;
  buy_and_hold_return_raw: string | null;
  excess_return: string;
  excess_return_raw: string | null;
  /** null when either side is unmeasurable — never a guess. */
  beats_buy_and_hold: boolean | null;
  /** Buy & hold scaled to the robot's realized OOS volatility (docs/27 R-4). */
  vol_matched_buy_and_hold_return?: string;
  vol_matched_buy_and_hold_return_raw?: string | null;
  excess_vs_vol_matched_raw?: string | null;
  selected: string;
  candidates_tried: number;
  /** The in-sample ranking behind `selected`: why these parameters (docs/35 L-2). */
  candidates?: CandidateScore[];
  selection_metric?: string;
  fills: number;
  in_sample_fills: number;
  oos_ending_balance: number | null;
  oos_metrics: BacktestMetricsPayload | null;
  window: { out_of_sample_start: string; out_of_sample_end: string };
}

export interface BacktestMetricsPayload {
  fees_paid: number;
  max_drawdown: number;
  max_dd_pct: string;
  turnover: number;
  sharpe_like: number | null;
  traded_notional: number | null;
  breakeven_cost: number | null;
  paid_cost_rate: number | null;
  cost_headroom: number | null;
}

export interface MultiWindowSummary {
  profitable: string;
  fold_count: number;
  mean_oos: string;
  mean_oos_raw: string | null;
  median_oos: string;
  worst_oos: string;
  best_oos: string;
  spread: string;
  spread_raw: string | null;
  buy_and_hold_mean: string;
  buy_and_hold_mean_raw: string | null;
  mean_excess_return: string;
  mean_excess_return_raw: string | null;
  vol_matched_buy_and_hold_mean?: string;
  vol_matched_buy_and_hold_mean_raw?: string | null;
  beats_vol_matched_buy_and_hold?: boolean | null;
  total_oos_fills: number;
  beats_buy_and_hold?: boolean | null;
  mean_breakeven_cost: number | null;
  breakeven_costs: (number | null)[];
  mean_paid_cost_rate: number | null;
  cost_headroom: number | null;
  folds: FoldSummary[];
  notes?: string;
  summary_line?: string;
}

export interface DeflatedSharpeSummary {
  summary_line: string;
  probability: string | null;
  sharpe: string | null;
  threshold_sharpe: string | null;
  observations: number;
  trials: number;
  /** Every configuration ever tried on this data (research/trials.jsonl); the threshold uses it. */
  trials_total?: number;
  note: string;
}

export interface PboSummary {
  pbo: string | null;
  blocks: number;
  configuration_count: number;
  split_count: number;
  is_meaningful: boolean;
  summary_line: string;
  deflated_sharpe: DeflatedSharpeSummary;
  labels: string[];
  /** blocks x configurations. null = the engine reported no balance for that run. */
  block_returns: (number | null)[][];
  best_configuration_index: number | null;
  best_configuration_label: string | null;
  notes?: string;
}

export interface WalkForwardSummary {
  selected: string;
  candidates_tried: number;
  window: {
    in_sample_start: string;
    in_sample_end: string;
    out_of_sample_start: string;
    out_of_sample_end: string;
  };
  in_sample: SingleBacktestSummary;
  out_of_sample: SingleBacktestSummary;
  in_sample_return: string | null;
  in_sample_return_raw: string | null;
  out_of_sample_return: string | null;
  out_of_sample_return_raw: string | null;
  notes?: string;
}

export interface SingleBacktestSummary {
  fills: number;
  positions: number;
  ending_balance: number | null;
  fees_paid: number;
  max_dd_pct: string;
  turnover: number;
  sharpe: number | null;
  breakeven_cost: number | null;
  paid_cost_rate: number | null;
  cost_headroom: number | null;
  traded_notional: number | null;
  session_id?: string | null;
  metrics?: BacktestMetricsPayload | null;
  notes?: string;
}

export interface ResearchRunConfig {
  config_version?: number;
  robot?: string;
  source?: string;
  bars?: number;
  folds?: number;
  is_fraction?: string;
  embargo_bars?: number | null;
  use_optuna?: boolean;
  optuna_trials?: number;
  pbo?: boolean;
  pbo_blocks?: number;
  bar_vpin?: boolean;
  tick_vpin?: boolean;
  hawkes?: boolean;
  stress_slice?: string | null;
  generate_tearsheet?: boolean;
  journal?: boolean;
  notify?: boolean;
  full_sample?: boolean;
  catalog_path?: string | null;
  instrument_id?: string | null;
  bar_interval?: string | null;
  is_start?: string | null;
  is_end?: string | null;
  oos_start?: string | null;
  oos_end?: string | null;
  param_overrides?: Record<string, string>;
}

export type ResearchRunType =
  | 'multi_window'
  | 'walk_forward'
  | 'full_sample'
  | 'backtest'
  | 'pbo'
  | 'error';

export interface ResearchSummary {
  is_finished: boolean;
  is_error: boolean;
  run_type?: ResearchRunType | string | null;
  robot?: string | null;
  source?: string | null;
  finished_at?: string | null;
  report_label?: string | null;
  config?: ResearchRunConfig | null;
  starting_equity?: number | null;
  error_message?: string | null;
  tearsheet_url: string | null;
  multi_window: MultiWindowSummary | null;
  walk_forward?: WalkForwardSummary | null;
  single_backtest: SingleBacktestSummary | null;
  pbo?: PboSummary | null;
  raw_summary?: string | null;
}

export interface ResearchLogResponse {
  is_running: boolean;
  log: string;
  summary: ResearchSummary;
  result?: Record<string, unknown> | null;
}

/**
 * What to show a person when a request fails.
 *
 * FastAPI answers a refusal with `{"detail": "..."}` and a validation error with a list in
 * the same field. The panel used to print the whole body, so the Backtest Details modal
 * showed `{"detail":"no live paper session '0d83e156-…'"}` instead of the sentence. The
 * body is kept as-is when there is no readable string in it (a validation list, HTML).
 */
export function errorText(body: string, status: number): string {
  let parsed: unknown = null;
  try {
    parsed = JSON.parse(body);
  } catch {
    parsed = null;
  }
  if (parsed && typeof parsed === 'object') {
    const fields = parsed as { detail?: unknown; message?: unknown };
    for (const value of [fields.detail, fields.message]) {
      if (typeof value === 'string' && value.trim()) return value;
    }
  }
  return body || `Request failed (${status})`;
}

async function parseJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(errorText(text, res.status));
  }
  return res.json();
}

export async function fetchStatus(catalogPath?: string): Promise<StatusResponse> {
  const query = catalogPath ? `?catalog_path=${encodeURIComponent(catalogPath)}` : '';
  return parseJson(await fetch(apiUrl(`/api/status${query}`)));
}

export async function fetchCatalog(catalogPath?: string): Promise<CatalogResponse> {
  const query = catalogPath ? `?catalog_path=${encodeURIComponent(catalogPath)}` : '';
  return parseJson(await fetch(apiUrl(`/api/catalog${query}`)));
}

export async function fetchCatalogs(): Promise<CatalogsResponse> {
  return parseJson(await fetch(apiUrl('/api/catalogs')));
}

export async function fetchCatalogBars(params: {
  instrument_id?: string;
  catalog_path?: string;
  bar_interval?: string;
  start?: string;
  end?: string;
  limit?: number;
}): Promise<CatalogBarsResponse> {
  const query = new URLSearchParams();
  if (params.instrument_id) query.set('instrument_id', params.instrument_id);
  if (params.catalog_path) query.set('catalog_path', params.catalog_path);
  if (params.bar_interval) query.set('bar_interval', params.bar_interval);
  if (params.start) query.set('start', params.start);
  if (params.end) query.set('end', params.end);
  if (params.limit != null) query.set('limit', String(params.limit));
  return parseJson(await fetch(apiUrl(`/api/catalog/bars?${query.toString()}`)));
}

/** Which tree an ingest writes into. One catalog holds all five side by side. */
export type IngestSeries = 'klines' | 'trades' | 'funding' | 'depth' | 'premium_index';

export async function runIngest(params: {
  symbols: string;
  start?: string;
  end?: string;
  catalog?: string;
  incremental?: boolean;
  series?: IngestSeries;
  interval?: string;
  /** `archive` = data.binance.vision (history, verified); `rest` = public REST/WebSocket. */
  source?: 'archive' | 'rest';
  /** Archive klines only: spot or USD-M perpetuals. */
  market?: 'spot' | 'um';
}): Promise<ActionResult> {
  return parseJson(
    await fetch(apiUrl('/api/catalog/ingest'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),
  );
}

export async function cancelIngest(): Promise<ActionResult> {
  return parseJson(
    await fetch(apiUrl('/api/catalog/ingest/cancel'), {
      method: 'POST',
    }),
  );
}

export async function fetchIngestLog(): Promise<JobLogResponse> {
  return parseJson(await fetch(apiUrl('/api/catalog/ingest/log')));
}

export async function fetchStrategies(): Promise<StrategiesResponse> {
  return parseJson(await fetch(apiUrl('/api/strategies')));
}

export async function runResearch(params: ResearchRunParams): Promise<ActionResult> {
  return parseJson(
    await fetch(apiUrl('/api/research'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),
  );
}

export async function cancelResearch(): Promise<ActionResult> {
  return parseJson(
    await fetch(apiUrl('/api/research/cancel'), {
      method: 'POST',
    }),
  );
}

export async function fetchResearchLog(): Promise<ResearchLogResponse> {
  return parseJson(await fetch(apiUrl('/api/research/log')));
}

export async function fetchResearchHistory(limit = 20): Promise<{ history: HistoryEntry[] }> {
  return parseJson(await fetch(apiUrl(`/api/research/history?limit=${limit}`)));
}

export async function fetchReports(): Promise<ReportsResponse> {
  return parseJson(await fetch(apiUrl('/api/reports')));
}

export async function fetchSettingsSchema(): Promise<SettingsSchemaResponse> {
  return parseJson(await fetch(apiUrl('/api/settings/schema')));
}

export async function fetchSettings(): Promise<SettingsResponse> {
  return parseJson(await fetch(apiUrl('/api/settings')));
}

export async function saveSettings(settings: Record<string, string>): Promise<ActionResult> {
  return parseJson(
    await fetch(apiUrl('/api/settings'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings }),
    }),
  );
}

export interface CommandCenterJob {
  running: boolean;
  label: string;
  started_at?: string | null;
  elapsed_seconds?: number | null;
}

export interface DataSeriesCoverage {
  present: boolean;
  /** Bars/taker flow/funding: rows. Ticks: rows across all day shards, null when unreadable. */
  rows: number | null;
  first: string | null;
  last: string | null;
}

export interface TickCoverage extends DataSeriesCoverage {
  /** Aggregated trades are stored one Parquet file per UTC day. */
  files: number;
  bytes: number;
}

export interface DataHealthInstrument {
  instrument_id: string;
  /** Binance symbol the side series (taker flow, ticks, funding, depth) are keyed by. */
  symbol: string | null;
  bars: DataSeriesCoverage;
  taker_flow: DataSeriesCoverage;
  ticks: TickCoverage;
  /** L2 depth snapshots, captured live — day-sharded like the ticks. */
  orderbook: TickCoverage;
  /** Funding may come from a sibling catalog; `catalog` names it when it does. */
  funding: DataSeriesCoverage & { catalog?: string };
  premium_index?: DataSeriesCoverage;
  /** QC verdict written by the archive ingest (`<catalog>/quality.json`), if any. */
  quality?: SeriesQuality | null;
}

export interface SeriesQuality {
  status: 'ok' | 'warn' | 'fail';
  bars: number;
  expected_bars: number;
  missing_bars: number;
  gap_count: number;
  zero_volume: number;
  extreme_move_count: number;
  relisting_suspects: { ts: string; ratio: string }[];
  partial_dropped: number;
}

export interface DataHealthResponse {
  catalog_path: string;
  exists: boolean;
  bar_interval: string;
  error?: string | null;
  instruments: DataHealthInstrument[];
  /** True when at least one instrument has tick data, i.e. tick filters can run. */
  tick_filters_ready: boolean;
  /** True when at least one instrument has L2 snapshots recorded. */
  orderbook_ready: boolean;
}

export async function fetchDataHealth(catalogPath?: string): Promise<DataHealthResponse> {
  const query = catalogPath ? `?catalog_path=${encodeURIComponent(catalogPath)}` : '';
  return parseJson(await fetch(apiUrl(`/api/data${query}`)));
}

export interface CommandCenterSeriesRow {
  instrument_id: string;
  symbol: string | null;
  bars: number;
  bars_last: string | null;
  taker_flow: boolean;
  ticks: boolean;
  tick_rows: number | null;
  tick_last: string | null;
  orderbook: boolean;
  orderbook_rows: number | null;
  funding: boolean;
}

export interface CommandCenterResponse {
  jobs: Record<string, CommandCenterJob>;
  safety: { live_enabled: boolean; mode: string };
  robots: { total: number; wired: string[] };
  catalog_path: string;
  /** ISO date string of the most recent bar across all catalog instruments (for staleness check). */
  catalog_last_date?: string | null;
  /** Total bar count across all instruments in the current catalog. */
  catalog_total_bars?: number | null;
  catalog_bar_interval?: string | null;
  /** Which optional series exist beside the bars, one row per instrument. */
  data_series?: CommandCenterSeriesRow[];
  recent_experiments: HistoryEntry[];
  models: MlModelInfo[];
  journal: Record<string, number>;
  /** The raw `last_run.json`, which carries the same fields as a research summary. */
  last_research: ResearchSummary | null;
}

export interface JournalEntry {
  index?: number;
  created_at: string;
  source: string;
  subject: string;
  /** What was enforced for this run, e.g. "walk-forward catalog folds=4". */
  gates?: string;
  decision: string;
  reason?: string;
  oos_return?: string | null;
  buy_and_hold_return?: string | null;
  fills?: number | null;
  artifact?: string | null;
}

export interface MlTrainSummary {
  is_finished: boolean;
  is_error: boolean;
  model_type?: string;
  model_path?: string;
  accuracy?: string;
  rows?: number;
  /** Meta-label runs only: share of labels that hit the profit barrier. */
  take_profit_rate?: string | null;
  oof_precision?: string | null;
  oof_recall?: string | null;
  beats_always_take?: string | null;
  majority_rate?: string | null;
  beats_majority?: string | null;
  train_window?: string | null;
  created_at?: string | null;
  error_message?: string;
}

export interface MlTrainLogResponse {
  is_running: boolean;
  log: string;
  summary: MlTrainSummary;
  result?: Record<string, unknown> | null;
}

export interface PaperOrder {
  ts: string;
  instrument_id: string;
  side: string;
  qty: string;
  reason: string;
}

export interface PaperSummary {
  is_finished: boolean;
  is_error: boolean;
  robot?: string;
  order_count?: number;
  error_message?: string;
  disclaimer?: string;
}

export interface PaperLogResponse {
  is_running: boolean;
  log: string;
  summary: PaperSummary;
  result?: Record<string, unknown> | null;
}

export async function fetchCommandCenter(): Promise<CommandCenterResponse> {
  return parseJson(await fetch(apiUrl('/api/command-center')));
}

export async function fetchJournal(): Promise<{ entries: JournalEntry[] }> {
  return parseJson(await fetch(apiUrl('/api/journal')));
}

export async function patchJournalDecision(index: number, decision: string) {
  return parseJson(
    await fetch(apiUrl(`/api/journal/${index}`), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision }),
    }),
  );
}

export async function fetchMlModels(): Promise<MlModelsResponse> {
  return parseJson(await fetch(apiUrl('/api/ml/models')));
}

export async function runMlTrain(params: {
  model_type: string;
  folds?: number;
  embargo?: number;
  horizon?: number;
  catalog_path?: string;
  instrument_id?: string;
  bar_interval?: string;
  output_path?: string;
  start?: string;
  end?: string;
  threshold?: string;
}): Promise<ActionResult> {
  return parseJson(
    await fetch(apiUrl('/api/ml/train'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),
  );
}

export async function cancelMlTrain(): Promise<ActionResult> {
  return parseJson(
    await fetch(apiUrl('/api/ml/train/cancel'), {
      method: 'POST',
    }),
  );
}

export async function fetchMlTrainLog(): Promise<MlTrainLogResponse> {
  return parseJson(await fetch(apiUrl('/api/ml/train/log')));
}

export async function runPaper(params: {
  robot: string;
  bars?: number;
  source?: string;
}): Promise<ActionResult> {
  return parseJson(
    await fetch(apiUrl('/api/paper/run'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),
  );
}

export async function cancelPaper(): Promise<ActionResult> {
  return parseJson(
    await fetch(apiUrl('/api/paper/cancel'), {
      method: 'POST',
    }),
  );
}

export async function fetchPaperLog(): Promise<PaperLogResponse> {
  return parseJson(await fetch(apiUrl('/api/paper/log')));
}

export interface LivePaperConfig {
  symbol: string;
  interval: string;
  robot: string;
  starting_equity: string;
  risk_per_trade: string;
  stop_pct: string;
  take_profit_multiple: string;
  auto_trade: boolean;
  name?: string;
  notes?: string;
}

export interface LivePosition {
  symbol: string;
  side: string;
  qty: string;
  entry_price: string;
  entry_time: string;
  mark_price: string;
  unrealized_pnl: string;
  unrealized_pnl_pct: string;
  stop_loss: string | null;
  take_profit: string | null;
}

export interface LiveFill {
  id: string;
  ts: string;
  symbol: string;
  side: string;
  qty: string;
  price: string;
  fee: string;
  realized_pnl: string;
  reason: string;
}

export interface LiveBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  is_closed: boolean;
}

export interface LiveEquityPoint {
  time: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
}

export interface LivePaperState {
  is_active: boolean;
  session_id?: string | null;
  name?: string;
  notes?: string;
  paused?: boolean;
  created_from?: string;
  risk_refusals?: Record<string, number>;
  last_bar_ts?: string | null;
  started_at?: string | null;
  resumed_at?: string | null;
  persisted?: boolean;
  mode: string;
  config: LivePaperConfig;
  starting_equity: string;
  current_balance: string;
  current_equity: string;
  realized_pnl: string;
  unrealized_pnl: string;
  fees_paid: string;
  position: LivePosition | null;
  fills: LiveFill[];
  equity_history: LiveEquityPoint[];
  recent_bars: LiveBar[];
  last_price: string | null;
  last_update_ts: string;
  status_message: string;
}

/** One row of the sessions table (`GET /api/paper/sessions`). */
export interface PaperSessionRow {
  session_id: string;
  name: string;
  robot: string;
  symbol: string;
  interval: string;
  status: 'active' | 'paused' | 'stopped';
  notes?: string;
  created_from?: string;
  started_at?: string | null;
  stopped_at?: string | null;
  resumed_at?: string | null;
  starting_equity: string;
  equity: string;
  return_pct: number | null;
  vs_benchmark_pp?: number | null;
  position?: string | null;
  unrealized_pnl?: string;
  fees_paid?: string;
  fills: number;
  closed_trades?: number;
  wins?: number;
  max_drawdown_pct?: number;
  last_bar_ts?: string | null;
  risk_refusals?: number;
  status_message?: string;
  history_only?: boolean;
}

export interface PaperFeedStatus {
  symbol: string;
  interval: string;
  connected: boolean;
  sessions: number;
  messages: number;
}

export interface PaperPortfolio {
  sessions_active: number;
  sessions_paused: number;
  starting_equity: number;
  equity: number;
  return_pct: number | null;
  exposure: Record<string, { long: number; short: number; flat: number }>;
  warnings: string[];
  feeds: PaperFeedStatus[];
  persisted: boolean;
  max_sessions: number;
}

const sessionPath = (sessionId: string, action?: string) =>
  apiUrl(`/api/paper/sessions/${encodeURIComponent(sessionId)}${action ? `/${action}` : ''}`);

export async function fetchPaperSessions(): Promise<{
  sessions: PaperSessionRow[];
  portfolio: PaperPortfolio;
}> {
  return parseJson(await fetch(apiUrl('/api/paper/sessions')));
}

/** State of one session; without an id, the primary session (older single-session API). */
export async function fetchLivePaperState(sessionId?: string | null): Promise<LivePaperState> {
  return parseJson(
    await fetch(sessionId ? sessionPath(sessionId) : apiUrl('/api/paper/live/state')),
  );
}

export async function startLivePaper(
  params: Partial<LivePaperConfig> & { mode?: string },
): Promise<ActionResult & { session_id?: string; name?: string }> {
  return parseJson(
    await fetch(apiUrl('/api/paper/sessions'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),
  );
}

export async function stopLivePaper(sessionId: string): Promise<ActionResult> {
  return parseJson(await fetch(sessionPath(sessionId, 'stop'), { method: 'POST' }));
}

export async function pauseLivePaper(sessionId: string, paused: boolean): Promise<ActionResult> {
  return parseJson(
    await fetch(sessionPath(sessionId, paused ? 'pause' : 'resume'), { method: 'POST' }),
  );
}

export async function closeLivePosition(sessionId: string): Promise<ActionResult> {
  return parseJson(await fetch(sessionPath(sessionId, 'close-position'), { method: 'POST' }));
}

export async function updateLiveStops(
  sessionId: string,
  params: {
    stop_loss?: string | null;
    take_profit?: string | null;
  },
): Promise<ActionResult> {
  return parseJson(
    await fetch(sessionPath(sessionId, 'update-stops'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),
  );
}

/** One step of the robot's reasoning chain inside a decision record (`decision_trace/1`). */
export interface TradeDecisionStep {
  stage?: string;
  component?: string;
  verdict?: string;
  result?: string;
  values?: Record<string, unknown>;
  thresholds?: Record<string, unknown>;
  note?: string;
}

/** One line of the decision log, as the trade page receives it. */
export interface TradeDecisionRow {
  ts: string;
  /** Close of the bar the decision was made on; the writer stores it as a string. */
  close?: string | number | null;
  kind?: string;
  outcome?: string | null;
  signal?: string | null;
  regime?: string;
  signal_reason?: string | null;
  narrative?: string | null;
  blocked_by?: string | null;
  indicators?: Record<string, string | number | null>;
  states?: Record<string, string | number | boolean | null>;
  steps?: TradeDecisionStep[];
  account?: Record<string, unknown>;
  bar?: Record<string, number>;
}

/**
 * A reconstructed trade without its per-bar rows (`GET .../trades`).
 *
 * The money fields carry their basis: `pnl_source` says where the number came from and
 * `qty_known` / `fee_known` say whether a size and a fee were actually recorded. A
 * backtest log has no fills, so its PnL is price arithmetic on an assumed size — the UI
 * must show that, not a bare number that reads as account PnL.
 */
export interface TradeSummary {
  id: string;
  session_id: string;
  symbol: string;
  side: 'LONG' | 'SHORT' | string;
  status: 'OPEN' | 'CLOSED' | string;
  /** Which pass over the window this trade belongs to; >1 means the run was replayed. */
  window_index?: number;
  entry_time: string;
  entry_price: number;
  entry_reason?: string;
  exit_time?: string | null;
  exit_price?: number | null;
  exit_outcome?: string | null;
  exit_reason?: string | null;
  stop_loss?: number | null;
  /** The stop the trade opened with (R is measured against it; `stop_loss` may trail). */
  initial_stop_loss?: number | null;
  take_profit?: number | null;
  /** What the venue filled the entry at, vs `entry_price` = the decision bar's close. */
  entry_fill_price?: number | null;
  /** Positive = filled worse than the decision close. */
  entry_slippage_bps?: number | null;
  entry_fill_delay_s?: number | null;
  qty?: number;
  qty_known?: boolean;
  fee?: number | null;
  fee_known?: boolean;
  pnl_source?: 'fills' | 'price_delta' | 'mark' | null;
  realized_pnl?: number | null;
  realized_pnl_pct?: number | null;
  r_multiple?: number | null;
  mfe_close?: number | null;
  mae_close?: number | null;
  mfe_close_pct?: number | null;
  mae_close_pct?: number | null;
  excursion_basis?: string;
  duration_bars?: number;
  duration_seconds?: number;
  regime_at_entry?: string;
  regime_at_exit?: string;
  mark_price?: number | null;
  decision_count?: number;
}

export interface TradeDetail extends TradeSummary {
  decisions: TradeDecisionRow[];
  indicators_at_entry?: Record<string, string | number | null>;
  indicators_at_exit?: Record<string, string | number | null>;
  states_at_entry?: Record<string, string | number | boolean | null>;
  states_at_exit?: Record<string, string | number | boolean | null>;
  steps_at_entry?: TradeDecisionStep[];
  narrative_at_entry?: string;
}

export interface TradeChartBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  is_closed?: boolean;
}

/** Candles for the trade chart, the source they came from, and why they may be empty. */
export interface TradeChart {
  source: 'session' | 'catalog' | 'none';
  instrument_id?: string | null;
  bar_interval?: string | null;
  catalog_path?: string | null;
  note?: string;
  bars: TradeChartBar[];
}

export interface TradesResponse {
  status: string;
  session_id: string;
  records: number;
  limit: number;
  /** The record reader hit its cap: older trades exist and are not in this list. */
  truncated: boolean;
  /** Passes over the same window merged from one log (a walk-forward writes one per fold). */
  windows: number;
  trades: TradeSummary[];
}

export interface TradeDetailResponse {
  status: string;
  session_id: string;
  records: number;
  truncated: boolean;
  windows: number;
  trade: TradeDetail;
  chart: TradeChart;
  /** Bar records before the entry and after the exit (steps + states), for the chart. */
  context?: Pick<TradeDecisionRow, 'ts' | 'close' | 'steps' | 'states'>[];
}

/**
 * Trades reconstructed from a session's decision log.
 *
 * One endpoint for a live paper session and for a research backtest run: the writer keys
 * the log by `session_id` in both cases (`single_backtest.session_id` for a run), so the
 * same list serves the terminal and the Backtest Details modal.
 */
export async function fetchSessionTrades(
  sessionKey: string,
  limit?: number,
): Promise<TradesResponse> {
  const query = limit ? `?limit=${limit}` : '';
  return parseJson(await fetch(sessionPath(sessionKey, `trades${query}`)));
}

/** One trade with its decisions and the candles around it. */
export async function fetchSessionTrade(
  sessionKey: string,
  tradeId: string,
  context: {
    instrumentId?: string;
    barInterval?: string;
    catalogPath?: string;
    bars?: number;
  } = {},
): Promise<TradeDetailResponse> {
  const params = new URLSearchParams();
  if (context.instrumentId) params.set('instrument_id', context.instrumentId);
  if (context.barInterval) params.set('bar_interval', context.barInterval);
  if (context.catalogPath) params.set('catalog_path', context.catalogPath);
  if (context.bars != null) params.set('bars', String(context.bars));
  const query = params.toString();
  return parseJson(
    await fetch(
      sessionPath(sessionKey, `trades/${encodeURIComponent(tradeId)}${query ? `?${query}` : ''}`),
    ),
  );
}

export async function fetchDecisionLogs(
  sessionId: string,
  lines: number = 100,
  outcomes?: string[],
  options: { regime?: string; signal?: string } = {},
): Promise<any> {
  const params = new URLSearchParams({ lines: String(lines) });
  if (outcomes && outcomes.length) params.set('outcome', outcomes.join(','));
  if (options.regime) params.set('regime', options.regime);
  if (options.signal) params.set('signal', options.signal);
  return parseJson(
    await fetch(sessionPath(sessionId, `decision-log?${params.toString()}`), { method: 'GET' })
  );
}

/** Counts and key narratives of one session, computed server-side (`decision_digest.py`). */
export interface DecisionDigest {
  session_id: string | null;
  robots: string[];
  instruments: string[];
  bars: number;
  bar_seq_gaps: number;
  outcomes: Record<string, number>;
  blocked_by: Record<string, number>;
  regime_share_pct: Record<string, number>;
  regime_switches: number;
  regime_flip_flops: number;
  signals: Record<string, number>;
  near_misses: number;
  intrabar: Record<string, number>;
  v0_rows: number;
  /** Forward returns (% of price, signed by side) per group (executed/blocked/vetoed). */
  forward?: Record<
    string,
    Record<string, { n: number; mean_pct: number | null; median_pct: number | null; hit_rate: number | null }>
  >;
  near_miss_examples?: string[];
}

/** Digest of the session's whole log (counts, regimes, blocks) — shown without an LLM call. */
export async function fetchDecisionDigest(
  sessionId: string,
): Promise<{ status: string; digest: DecisionDigest; markdown: string }> {
  return parseJson(await fetch(sessionPath(sessionId, 'decision-digest'), { method: 'GET' }));
}

/** Digest of the session's whole log on the server (counts + key narratives). */
export async function analyzeSessionDecisions(
  sessionId: string,
  options: { question?: string; preset?: string } = {},
): Promise<any> {
  const res = await fetch(apiUrl('/api/decisions/analyze'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session: sessionId, ...options }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function analyzeDecisions(records: any[], question: string): Promise<any> {
  const res = await fetch(apiUrl('/api/decisions/analyze'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ records, question }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export function getLivePaperWsUrl(sessionId?: string | null): string {
  const query = sessionId ? `?session=${encodeURIComponent(sessionId)}` : '';
  const base = apiUrl(`/api/paper/live-stream${query}`);
  return withWsToken(base.replace(/^http/, 'ws'));
}

export async function scanTriangular() {
  return parseJson(
    await fetch(apiUrl('/api/scan/triangular'), {
      method: 'POST',
    }),
  );
}

export interface ProposeResponse {
  status: string;
  message?: string;
  prompt?: string;
  model?: string;
  count?: number;
  summary?: string;
  artifact_path?: string;
  count_parsed?: number;
}

export async function runPropose(params: {
  count?: number;
  dry_run?: boolean;
  prompt?: string;
  as_of?: string;
  model?: string;
  journal?: boolean;
}) {
  return parseJson<ProposeResponse>(
    await fetch(apiUrl('/api/propose'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),
  );
}

export async function fetchHistoryEntry(
  historyId: string,
): Promise<{ entry: HistoryEntry }> {
  return parseJson(await fetch(apiUrl(`/api/research/history/${encodeURIComponent(historyId)}`)));
}

export interface HypothesisItem {
  name: string;
  formula: string;
  mechanism: string;
  horizon_bars: number;
  expected_sign: number;
  kill_condition: string;
  unknown_identifiers?: string[];
}

export interface HypothesisEntry {
  file: string;
  modified: string;
  size_kb: number;
  url: string;
  model?: string;
  as_of?: string;
  count_parsed?: number;
  count_flagged?: number;
  review_status?: string;
}

export interface HypothesisRunDetail {
  version: number;
  created_at: string;
  model: string;
  endpoint_host: string;
  as_of: string;
  prompt_file: string;
  prompt_sha256: string;
  feature_contract: string[];
  count_requested: number;
  count_parsed: number;
  count_flagged: number;
  hypotheses: HypothesisItem[];
  raw_response: string;
  review?: {
    status: string;
    note: string;
    gates: {
      purged_cv: boolean | null;
      walk_forward_oos: boolean | null;
      buy_and_hold_oos: boolean | null;
    };
  };
}

export async function fetchHypotheses(): Promise<{ hypotheses: HypothesisEntry[] }> {
  return parseJson(await fetch(apiUrl('/api/hypotheses')));
}

export async function fetchHypothesisDetail(file: string): Promise<HypothesisRunDetail> {
  return parseJson(await fetch(apiUrl(`/api/hypotheses/${encodeURIComponent(file)}`)));
}

// ---- batch backtests (docs/30) ------------------------------------------------------------

export interface BatchLaunchParams {
  robots: string[];
  symbols: string[];
  interval?: string;
  catalog?: string;
  folds?: number;
  is_fraction?: string;
  parallel?: number;
  label?: string;
  days?: number;
  env?: Record<string, string>;
  /** Named override sets; each cell runs once per variant (see `lib/batch.ts`). */
  variants?: BatchVariant[];
  dry_run?: boolean;
}

export interface BatchLaunchResult {
  status: string;
  batch_id?: string;
  dry_run?: boolean;
  cells: PlannedCell[];
}

export interface RunPayload {
  batch_id: string;
  batch_label?: string;
  cell: BatchRow & { env?: Record<string, string>; started_at?: string | null; finished_at?: string | null };
  result: Record<string, unknown> | null;
  summary: BatchRow | null;
  folds: FoldRef[];
  log_tail: string;
}

export interface BatchTradeSummary extends TradeSummary {
  fold: number;
  fold_session: string;
}

const batchPath = (batchId: string, rest = '') =>
  apiUrl(`/api/batches/${encodeURIComponent(batchId)}${rest}`);

export async function launchBatch(params: BatchLaunchParams): Promise<BatchLaunchResult> {
  return parseJson(
    await fetch(apiUrl('/api/batches'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),
  );
}

export async function fetchBatches(): Promise<{ batches: BatchListRow[] }> {
  return parseJson(await fetch(apiUrl('/api/batches')));
}

export async function fetchBatch(batchId: string): Promise<{ batch: BatchDetail }> {
  return parseJson(await fetch(batchPath(batchId)));
}

export async function cancelBatch(batchId: string): Promise<ActionResult> {
  return parseJson(await fetch(batchPath(batchId, '/cancel'), { method: 'POST' }));
}

export async function deleteBatch(batchId: string): Promise<{ status: string; deleted: string }> {
  return parseJson(await fetch(batchPath(batchId), { method: 'DELETE' }));
}

/** Delete this batch's results and run the same request again, under the same id. */
export async function restartBatch(
  batchId: string,
): Promise<{ status: string; batch_id: string; cells: PlannedCell[] }> {
  return parseJson(await fetch(batchPath(batchId, '/restart'), { method: 'POST' }));
}

export async function importDecisionSweep(): Promise<{ batch_id: string }> {
  return parseJson(await fetch(apiUrl('/api/batches/import-sweep'), { method: 'POST' }));
}

const runPath = (batchId: string, cellId: string, rest = '') =>
  batchPath(batchId, `/runs/${encodeURIComponent(cellId)}${rest}`);

export async function fetchRun(batchId: string, cellId: string): Promise<{ run: RunPayload }> {
  return parseJson(await fetch(runPath(batchId, cellId)));
}

export async function fetchRunTrades(
  batchId: string,
  cellId: string,
  fold?: number,
): Promise<{ trades: BatchTradeSummary[] }> {
  const query = fold != null ? `?fold=${fold}` : '';
  return parseJson(await fetch(runPath(batchId, cellId, `/trades${query}`)));
}

export async function fetchRunDigest(
  batchId: string,
  cellId: string,
  fold?: number,
): Promise<{ digest: DecisionDigest; markdown: string }> {
  const query = fold != null ? `?fold=${fold}` : '';
  return parseJson(await fetch(runPath(batchId, cellId, `/digest${query}`)));
}

export interface MarginBucket {
  component: string;
  key: string;
  unit: string;
  values: number[];
  passed: number;
  total: number;
}

export async function fetchRunMargins(
  batchId: string,
  cellId: string,
  fold?: number,
): Promise<{ margins: Record<string, MarginBucket> }> {
  const query = fold != null ? `?fold=${fold}` : '';
  return parseJson(await fetch(runPath(batchId, cellId, `/margins${query}`)));
}
