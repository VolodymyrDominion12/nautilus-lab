/**
 * Pure logic of the ingest form: what a choice of source/market/series/interval means,
 * which request it becomes, and what to warn about before it is sent (docs/34 F4–F6).
 */
import type { IngestSeries } from '../services/api';

export type IngestSource = 'archive' | 'rest';
export type ArchiveMarket = 'spot' | 'um';

export interface IngestFormState {
  source: IngestSource;
  market: ArchiveMarket;
  series: IngestSeries;
  symbols: string;
  start: string;
  end: string;
  interval: string;
}

/** History comes from the archive by default: verified files, delisted coins included. */
export const DEFAULT_FORM: IngestFormState = {
  source: 'archive',
  market: 'spot',
  series: 'klines',
  symbols: 'BTCUSDT,ETHUSDT',
  start: '2019-01-01',
  end: '',
  interval: '1d',
};

/** Series each source can fetch. Ticks and live depth are REST/WebSocket only. */
export const SERIES_BY_SOURCE: Record<IngestSource, readonly IngestSeries[]> = {
  archive: ['klines', 'funding', 'premium_index'],
  rest: ['klines', 'premium_index', 'funding', 'trades', 'depth'],
};

const TOP_11 = 'BTC,ETH,SOL,BNB,XRP,DOGE,ADA,AVAX,DOT,LINK,LTC'.split(',');

export interface SymbolPreset {
  label: string;
  value: string;
}

export function symbolPresets(form: IngestFormState): SymbolPreset[] {
  const perp = form.source === 'rest' && form.market === 'um';
  const top = TOP_11.map((base) => `${base}USDT${perp ? '-PERP' : ''}`).join(',');
  const presets: SymbolPreset[] = [
    { label: 'Top 2', value: perp ? 'BTCUSDT-PERP,ETHUSDT-PERP' : 'BTCUSDT,ETHUSDT' },
    { label: 'Top 11', value: top },
  ];
  if (form.source === 'archive') {
    // Every *USDT crypto symbol the archive has ever listed, delisted ones included:
    // the only universe without survivorship bias.
    presets.push({ label: 'All *USDT', value: 'all' });
  }
  return presets;
}

/** Whether the series is written as bars of a given interval (and so needs one). */
export function usesInterval(series: IngestSeries): boolean {
  return series === 'klines' || series === 'premium_index';
}

/** Where an archive run writes when no catalog is forced: one catalog per market+interval. */
export function archiveTarget(form: IngestFormState): string {
  if (form.series === 'funding') return 'every catalog_perp_* catalog';
  const kind = form.series === 'premium_index' || form.market === 'um' ? 'perp' : 'spot';
  return `catalog_${kind}_${form.interval}`;
}

export interface IngestRequestBody {
  symbols: string;
  start?: string;
  end?: string;
  catalog?: string;
  incremental?: boolean;
  series: IngestSeries;
  interval?: string;
  source: IngestSource;
  market?: ArchiveMarket;
}

export function buildIngestRequest(
  form: IngestFormState,
  selectedCatalogPath: string,
  incremental: boolean,
): IngestRequestBody {
  const symbols = form.symbols.trim();
  const interval = usesInterval(form.series) ? form.interval : undefined;
  if (form.source === 'archive') {
    // No catalog: the archive path picks catalog_<market>_<interval> itself, so a 4h run
    // never lands in the 1d catalog that happens to be selected in the header.
    return {
      symbols,
      start: form.start || undefined,
      end: form.end || undefined,
      series: form.series,
      interval,
      source: 'archive',
      market: form.series === 'klines' ? form.market : undefined,
    };
  }
  const windowless = form.series === 'depth' || (incremental && form.series === 'klines');
  return {
    symbols,
    start: windowless ? undefined : form.start || undefined,
    end: form.series === 'depth' ? undefined : form.end || undefined,
    catalog: selectedCatalogPath || undefined,
    incremental: incremental && form.series === 'klines',
    series: form.series,
    interval,
    source: 'rest',
  };
}

const DAY_MS = 86_400_000;
const SUB_HOUR = new Set(['1m', '5m', '15m']);

/** Things worth saying before the request is sent. Empty when there is nothing to say. */
export function ingestWarnings(form: IngestFormState, now: Date = new Date()): string[] {
  const warnings: string[] = [];
  const start = form.start ? Date.parse(form.start) : Number.NaN;
  const end = form.end ? Date.parse(form.end) : now.getTime();
  if (!Number.isNaN(start) && start >= end) warnings.push('Start must be before end.');
  if (usesInterval(form.series) && SUB_HOUR.has(form.interval) && !Number.isNaN(start)) {
    const days = Math.round((end - start) / DAY_MS);
    if (days > 90) {
      warnings.push(
        `${form.interval} bars over ${days} days is a very large series; research here runs on 1h+.`,
      );
    }
  }
  if (form.source === 'archive' && form.symbols.trim().toLowerCase() === 'all') {
    warnings.push(
      'All symbols: hundreds of series. The first run downloads for a long time; re-runs reuse the cache.',
    );
  }
  if (form.source === 'rest' && form.series === 'funding') {
    warnings.push(
      'REST funding before late 2023 has no mark price in the response; the archive is the reference source.',
    );
  }
  return warnings;
}

export function startMessage(form: IngestFormState, incremental: boolean): string {
  if (form.source === 'archive') {
    return `Archive ingest (data.binance.vision, SHA256-verified) -> ${archiveTarget(form)}...\n`;
  }
  switch (form.series) {
    case 'trades':
      return 'Fetching aggregated trades (ticks) — needed by the tick-level VPIN and Hawkes filters...\n';
    case 'funding':
      return 'Fetching funding settlements for the perpetual...\n';
    case 'premium_index':
      return 'Fetching premium index klines (basis mark vs index) for perpetual contracts...\n';
    case 'depth':
      return 'Opening the Binance depth WebSocket — this records until you press Stop...\n';
    default:
      return incremental
        ? 'Incremental update: fetching bars after the last stored timestamp...\n'
        : 'Launching Binance klines download into the Parquet catalog...\n';
  }
}
