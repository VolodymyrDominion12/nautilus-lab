import { apiUrl } from '../config';
import { withWsToken } from '../lib/apiAuth';
import type {
  ActionResult,
  CatalogSummary,
  CatalogsResponse,
  JobLogResponse,
  JobState,
  MlModelInfo,
  MlModelsResponse,
  ReportsResponse,
  StatusResponse,
} from './api.gen';

// Response types generated from the API's Pydantic models (api.gen.ts, docs/27 E-2.3).
// Re-exported so components keep importing from here; the rest move over route by route.
export type {
  ActionResult,
  CatalogSummary,
  CatalogsResponse,
  JobLogResponse,
  JobState,
  MlModelInfo,
  StatusResponse,
};
export type { ReportItem, StressSliceInfo } from './api.gen';

export type JobKey = keyof StatusResponse['jobs'];

export interface CatalogInstrument {
  instrument_id: string;
  raw_symbol: string;
  bars_count: number;
  first_date: string | null;
  last_date: string | null;
  quote_currency: string;
  maker_fee: number;
  taker_fee: number;
}

export interface CatalogResponse {
  catalog_path: string;
  exists: boolean;
  /** One catalog holds one interval; the chart needs it to request the right bar type. */
  bar_interval?: string;
  total_instruments?: number;
  instruments: CatalogInstrument[];
  error?: string;
}

export interface StrategySpec {
  name: string;
  title?: string;
  domain_module: string | null;
  strategy_class: string | null;
  backtest_adapter?: string | null;
  wired_in_backtest: boolean;
  minimum_bars: number;
  /** 'explicit' = own grid branch in param_grid.py; 'default_branch' = the regime grid applies. */
  grid_source: string | null;
  signal_kind?: string | null;
  status: string;
  summary: string;
  hypothesis?: string;
  invariants?: unknown[];
  /** `env` is required by the spec schema (`params[].env` is validated against Settings). */
  params: Array<{ env: string; name?: string; type?: string; default?: unknown; description?: string }>;
}

export interface ResearchRunParams {
  robot: string;
  source: 'catalog' | 'synthetic';
  bars?: number;
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
  is_start?: string;
  is_end?: string;
  oos_start?: string;
  oos_end?: string;
  param_overrides?: Record<string, string>;
}

export interface CatalogBarPoint {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CatalogBarsResponse {
  instrument_id: string;
  bar_type: string;
  bar_interval: string;
  catalog_path: string;
  count: number;
  first_date: string | null;
  last_date: string | null;
  bars: CatalogBarPoint[];
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
  selected: string;
  candidates_tried: number;
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

export interface SettingField {
  key: string;
  label: string;
  field_type: 'string' | 'number' | 'boolean' | 'select' | 'secret';
  description?: string;
  options?: string[] | null;
}

export interface SettingGroup {
  id: string;
  title: string;
  description: string;
  fields: SettingField[];
}

async function parseJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Request failed (${res.status})`);
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

/** Which tree an ingest writes into. One catalog holds all four side by side. */
export type IngestSeries = 'klines' | 'trades' | 'funding' | 'depth';

export async function runIngest(params: {
  symbols: string;
  start?: string;
  end?: string;
  catalog?: string;
  incremental?: boolean;
  series?: IngestSeries;
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

export async function fetchStrategies(): Promise<{ strategies: StrategySpec[] }> {
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

export async function fetchSettingsSchema(): Promise<{ groups: SettingGroup[] }> {
  return parseJson(await fetch(apiUrl('/api/settings/schema')));
}

export async function fetchSettings(): Promise<{ settings: Record<string, string> }> {
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
  funding: DataSeriesCoverage;
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

export async function fetchDecisionLogs(sessionId: string, lines: number = 100): Promise<any> {
  return parseJson(
    await fetch(sessionPath(sessionId, `decision-log?lines=${lines}`), { method: 'GET' })
  );
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
