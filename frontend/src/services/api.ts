export interface StatusResponse {
  active_bots: number;
  research_running: boolean;
  ingest_running: boolean;
  strategies_available: string[];
  is_live: boolean;
  live_safe_mode: string;
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
}

export interface ResearchSummary {
  is_finished: boolean;
  is_error: boolean;
  tearsheet_url: string | null;
  multi_window: {
    profitable: string;
    mean_oos: string;
    median_oos: string;
    worst_oos: string;
    best_oos: string;
    buy_and_hold_mean: string;
    total_oos_fills: number;
  } | null;
  single_backtest: {
    fills: number;
    positions: number;
    ending_balance: number;
    fees_paid: number;
    max_dd_pct: string;
    turnover: number;
    sharpe: number;
  } | null;
}

export interface ResearchLogResponse {
  is_running: boolean;
  log: string;
  summary: ResearchSummary;
}

const API_BASE = 'http://localhost:8000/api';

export async function fetchStatus(): Promise<StatusResponse> {
  const res = await fetch(`${API_BASE}/status`);
  if (!res.ok) throw new Error('Failed to fetch status');
  return res.json();
}

export async function fetchCatalog(): Promise<CatalogResponse> {
  const res = await fetch(`${API_BASE}/catalog`);
  if (!res.ok) throw new Error('Failed to fetch catalog');
  return res.json();
}

export async function runIngest(params: { symbols: string; start?: string; end?: string }) {
  const res = await fetch(`${API_BASE}/catalog/ingest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error('Failed to start ingest');
  return res.json();
}

export async function fetchIngestLog(): Promise<{ is_running: boolean; log: string }> {
  const res = await fetch(`${API_BASE}/catalog/ingest/log`);
  if (!res.ok) throw new Error('Failed to fetch ingest log');
  return res.json();
}

export async function fetchStrategies(): Promise<{ strategies: StrategySpec[] }> {
  const res = await fetch(`${API_BASE}/strategies`);
  if (!res.ok) throw new Error('Failed to fetch strategies');
  return res.json();
}

export async function runResearch(params: ResearchRunParams) {
  const res = await fetch(`${API_BASE}/research`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error('Failed to start research');
  return res.json();
}

export async function fetchResearchLog(): Promise<ResearchLogResponse> {
  const res = await fetch(`${API_BASE}/research/log`);
  if (!res.ok) throw new Error('Failed to fetch research log');
  return res.json();
}

export async function fetchReports(): Promise<{ reports: ReportItem[] }> {
  const res = await fetch(`${API_BASE}/reports`);
  if (!res.ok) throw new Error('Failed to fetch reports');
  return res.json();
}

export async function fetchSettings(): Promise<{ settings: Record<string, string> }> {
  const res = await fetch(`${API_BASE}/settings`);
  if (!res.ok) throw new Error('Failed to fetch settings');
  return res.json();
}

export async function saveSettings(settings: Record<string, string>) {
  const res = await fetch(`${API_BASE}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ settings }),
  });
  if (!res.ok) throw new Error('Failed to save settings');
  return res.json();
}
