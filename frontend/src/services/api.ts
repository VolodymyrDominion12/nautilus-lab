import { apiUrl } from '../config';

export interface StatusResponse {
  active_bots: number;
  research_running: boolean;
  ingest_running: boolean;
  strategies_available: string[];
  wired_robots: string[];
  catalog_exists: boolean;
  catalog_instruments: number;
  catalog_path?: string;
  is_live: boolean;
  live_safe_mode: string;
}

export interface CatalogSummary {
  path: string;
  exists: boolean;
  total_instruments: number;
  error?: string;
}

export interface CatalogsResponse {
  default: string;
  catalogs: CatalogSummary[];
}

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
  total_instruments?: number;
  instruments: CatalogInstrument[];
  error?: string;
}

export interface StrategySpec {
  name: string;
  domain_module: string;
  strategy_class: string;
  wired_in_backtest: boolean;
  minimum_bars: number;
  grid_source: string;
  status: string;
  summary: string;
  hypothesis?: string;
  params: Array<{ name: string; type: string; default: any; env: string }>;
}

export interface ReportItem {
  filename: string;
  path: string;
  url: string;
  modified: string;
  size_kb: number;
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
  report_label?: string;
  multi_window?: MultiWindowSummary | null;
  single_backtest?: SingleBacktestSummary | null;
  config?: Record<string, unknown>;
}

export interface MultiWindowSummary {
  profitable: string;
  mean_oos: string;
  median_oos: string;
  worst_oos: string;
  best_oos: string;
  buy_and_hold_mean: string;
  total_oos_fills: number;
  beats_buy_and_hold?: boolean | null;
}

export interface SingleBacktestSummary {
  fills: number;
  positions: number;
  ending_balance: number;
  fees_paid: number;
  max_dd_pct: string;
  turnover: number;
  sharpe: number;
}

export interface ResearchSummary {
  is_finished: boolean;
  is_error: boolean;
  run_type?: string | null;
  report_label?: string | null;
  error_message?: string | null;
  tearsheet_url: string | null;
  multi_window: MultiWindowSummary | null;
  walk_forward?: Record<string, unknown> | null;
  single_backtest: SingleBacktestSummary | null;
  pbo?: Record<string, unknown> | null;
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

export async function fetchStatus(): Promise<StatusResponse> {
  return parseJson(await fetch(apiUrl('/api/status')));
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

export async function runIngest(params: {
  symbols: string;
  start?: string;
  end?: string;
  catalog?: string;
  incremental?: boolean;
}) {
  return parseJson(
    await fetch(apiUrl('/api/catalog/ingest'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),
  );
}

export async function cancelIngest() {
  return parseJson(
    await fetch(apiUrl('/api/catalog/ingest/cancel'), {
      method: 'POST',
    }),
  );
}

export async function fetchIngestLog(): Promise<{ is_running: boolean; log: string }> {
  return parseJson(await fetch(apiUrl('/api/catalog/ingest/log')));
}

export async function fetchStrategies(): Promise<{ strategies: StrategySpec[] }> {
  return parseJson(await fetch(apiUrl('/api/strategies')));
}

export async function runResearch(params: ResearchRunParams) {
  return parseJson(
    await fetch(apiUrl('/api/research'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),
  );
}

export async function cancelResearch() {
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

export async function fetchReports(): Promise<{ reports: ReportItem[] }> {
  return parseJson(await fetch(apiUrl('/api/reports')));
}

export async function fetchSettingsSchema(): Promise<{ groups: SettingGroup[] }> {
  return parseJson(await fetch(apiUrl('/api/settings/schema')));
}

export async function fetchSettings(): Promise<{ settings: Record<string, string> }> {
  return parseJson(await fetch(apiUrl('/api/settings')));
}

export async function saveSettings(settings: Record<string, string>) {
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
}

export interface CommandCenterResponse {
  jobs: Record<string, CommandCenterJob>;
  safety: { live_enabled: boolean; mode: string };
  robots: { total: number; wired: string[] };
  catalog_path: string;
  recent_experiments: HistoryEntry[];
  models: MlModelInfo[];
  journal: Record<string, number>;
  last_research: Record<string, unknown> | null;
}

export interface JournalEntry {
  index?: number;
  created_at: string;
  source: string;
  subject: string;
  decision: string;
  reason?: string;
  oos_return?: string | null;
  buy_and_hold_return?: string | null;
  fills?: number | null;
  artifact?: string | null;
}

export interface MlModelInfo {
  filename: string;
  path: string;
  size_kb: number;
  modified: number;
}

export interface MlTrainSummary {
  is_finished: boolean;
  is_error: boolean;
  model_type?: string;
  model_path?: string;
  accuracy?: string;
  rows?: number;
  error_message?: string;
}

export interface MlTrainLogResponse {
  is_running: boolean;
  log: string;
  summary: MlTrainSummary;
  result?: Record<string, unknown> | null;
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

export async function fetchMlModels(): Promise<{ models: MlModelInfo[] }> {
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
}) {
  return parseJson(
    await fetch(apiUrl('/api/ml/train'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),
  );
}

export async function cancelMlTrain() {
  return parseJson(
    await fetch(apiUrl('/api/ml/train/cancel'), {
      method: 'POST',
    }),
  );
}

export async function fetchMlTrainLog(): Promise<MlTrainLogResponse> {
  return parseJson(await fetch(apiUrl('/api/ml/train/log')));
}

export async function runPaper(params: { robot: string; bars?: number; source?: string }) {
  return parseJson(
    await fetch(apiUrl('/api/paper/run'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),
  );
}

export async function cancelPaper() {
  return parseJson(
    await fetch(apiUrl('/api/paper/cancel'), {
      method: 'POST',
    }),
  );
}

export async function fetchPaperLog(): Promise<PaperLogResponse> {
  return parseJson(await fetch(apiUrl('/api/paper/log')));
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
