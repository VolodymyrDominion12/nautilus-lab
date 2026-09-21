import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertCircle,
  CheckCircle,
  Clock,
  Database,
  Download,
  Layers,
  Plus,
  RefreshCw,
  Square,
} from 'lucide-react';
import { CatalogChart } from './CatalogChart';
import {
  cancelIngest,
  fetchCatalog,
  fetchCatalogs,
  fetchDataHealth,
  fetchIngestLog,
  runIngest,
} from '../services/api';
import type { CatalogResponse, CatalogSummary, DataHealthInstrument, IngestSeries } from '../services/api';
import { formatBps } from '../lib/format';

interface CatalogManagerProps {
  selectedCatalogPath: string;
  onCatalogChange: (path: string) => void;
}

export const CatalogManager: React.FC<CatalogManagerProps> = ({
  selectedCatalogPath,
  onCatalogChange,
}) => {
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [catalogOptions, setCatalogOptions] = useState<CatalogSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [symbols, setSymbols] = useState('ETHUSDT,BTCUSDT');
  const [startDate, setStartDate] = useState('2024-01-01');
  const [endDate, setEndDate] = useState('');
  const [ingestRunning, setIngestRunning] = useState(false);
  const [ingestSeries, setIngestSeries] = useState<IngestSeries>('klines');
  const [ingestLog, setIngestLog] = useState('');
  const [errorMsg, setErrorMsg] = useState('');
  const [chartInstrument, setChartInstrument] = useState<string | undefined>(undefined);
  const [health, setHealth] = useState<DataHealthInstrument[] | null>(null);

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    try {
      const [data, catalogs, coverage] = await Promise.all([
        fetchCatalog(selectedCatalogPath),
        fetchCatalogs(),
        fetchDataHealth(selectedCatalogPath).catch(() => null),
      ]);
      setCatalog(data);
      setCatalogOptions(catalogs.catalogs);
      setHealth(coverage?.instruments ?? null);
      setChartInstrument((current) =>
        data.instruments?.some((item) => item.instrument_id === current)
          ? current
          : data.instruments?.[0]?.instrument_id,
      );
      if (!selectedCatalogPath && catalogs.default) {
        onCatalogChange(catalogs.default);
      }
      setErrorMsg(data.error ?? '');
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to load the catalog');
    } finally {
      setLoading(false);
    }
  }, [selectedCatalogPath, onCatalogChange]);

  useEffect(() => {
    loadCatalog();
  }, [loadCatalog]);

  useEffect(() => {
    if (!ingestRunning) return;
    let cancelled = false;
    const interval = setInterval(async () => {
      try {
        const res = await fetchIngestLog();
        if (cancelled) return;
        setIngestLog(res.log);
        // BUG-1 fix: stop as soon as the server reports idle, regardless of
        // log content. The old guard `res.log.includes('Process finished')`
        // left the button stuck forever if the process crashed or was cancelled.
        if (!res.is_running) {
          setIngestRunning(false);
          loadCatalog();
        }
      } catch (err) {
        if (!cancelled) console.error(err);
      }
    }, 1500);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [ingestRunning, loadCatalog]);

  const startIngest = async (incremental: boolean) => {
    setErrorMsg('');
    setIngestRunning(true);
    setIngestLog(
      ingestSeries === 'trades'
        ? 'Fetching aggregated trades (ticks) — needed by the tick-level VPIN and Hawkes filters...\n'
        : ingestSeries === 'funding'
          ? 'Fetching funding settlements for the perpetual...\n'
          : ingestSeries === 'depth'
            ? 'Opening the Binance depth WebSocket — this records until you press Stop...\n'
            : incremental
              ? 'Incremental update: fetching bars after the last stored timestamp...\n'
              : 'Launching Binance klines download into the Parquet catalog...\n',
    );
    try {
      const response = await runIngest({
        symbols: symbols.trim(),
        // `--incremental` walks forward from the last stored bar, which only the bar
        // series has: for the others the whole requested window is re-read. A depth
        // capture has no window at all — it starts when it starts.
        start:
          incremental && ingestSeries === 'klines'
            ? undefined
            : ingestSeries === 'depth'
              ? undefined
              : startDate || undefined,
        end: ingestSeries === 'depth' ? undefined : endDate || undefined,
        catalog: selectedCatalogPath || undefined,
        incremental: incremental && ingestSeries === 'klines',
        series: ingestSeries,
      });
      if (response.status !== 'started') {
        setIngestRunning(false);
        setErrorMsg(response.message ?? 'The ingest was refused by the API.');
      }
    } catch (err) {
      setIngestRunning(false);
      setIngestLog((prev) => `${prev}\nError: ${err instanceof Error ? err.message : err}\n`);
    }
  };

  const handleCancelIngest = async () => {
    try {
      const response = await cancelIngest();
      setIngestLog((prev) => `${prev}\n${response.message ?? response.status}\n`);
      if (response.status === 'idle') setIngestRunning(false);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to cancel the ingest');
    }
  };

  const totalBars = (catalog?.instruments ?? []).reduce((sum, item) => sum + item.bars_count, 0);
  const firstOverall = (catalog?.instruments ?? [])
    .map((item) => item.first_date)
    .filter((value): value is string => Boolean(value))
    .sort()[0];
  const lastOverall = (catalog?.instruments ?? [])
    .map((item) => item.last_date)
    .filter((value): value is string => Boolean(value))
    .sort()
    .reverse()[0];

  // One catalog is four independent trees. The engine reads a missing optional series as
  // an empty one, so "the bars are here" says nothing about whether a tick-level filter
  // would have had any data behind it.
  const seriesRows = (health ?? []).map((item) => {
    const inst = (catalog?.instruments ?? []).find(
      (candidate) => candidate.instrument_id === item.instrument_id,
    );
    return { item, symbol: inst?.raw_symbol ?? item.instrument_id };
  });
  const tickReady = (health ?? []).some((item) => item.ticks.present);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-gray-900 border border-gray-800 p-6 rounded-2xl">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <Database className="w-6 h-6 text-blue-400" />
            <h2 className="text-xl font-bold text-gray-100">Parquet Data Catalog</h2>
            {catalog?.bar_interval && (
              <span className="text-[11px] font-mono px-2 py-0.5 rounded-full border bg-gray-950 text-gray-300 border-gray-800">
                {catalog.bar_interval} bars
              </span>
            )}
          </div>
          <p className="text-sm text-gray-400 mt-1">
            One catalog directory holds one bar interval. Selection here drives research, ML and the
            charts below.
          </p>
          <div className="mt-3 flex flex-col sm:flex-row gap-2 sm:items-center">
            <label className="text-xs text-gray-500">Catalog path</label>
            <select
              value={selectedCatalogPath}
              onChange={(e) => onCatalogChange(e.target.value)}
              className="bg-gray-950 border border-gray-800 text-sm text-gray-200 rounded-xl px-3 py-2 font-mono min-w-[240px]"
            >
              {catalogOptions.map((item) => (
                <option key={item.path} value={item.path}>
                  {item.path} ({item.total_instruments} inst.)
                </option>
              ))}
              {catalogOptions.length === 0 && (
                <option value={selectedCatalogPath}>{selectedCatalogPath || 'catalog'}</option>
              )}
            </select>
          </div>

          {(catalog?.instruments?.length ?? 0) > 0 && (
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[11px] font-mono text-gray-400">
              <span>
                instruments: <span className="text-gray-200">{catalog?.total_instruments ?? 0}</span>
              </span>
              <span>
                bars: <span className="text-gray-200">{totalBars.toLocaleString()}</span>
              </span>
              {firstOverall && lastOverall && (
                <span>
                  coverage:{' '}
                  <span className="text-gray-200">
                    {firstOverall.slice(0, 10)} → {lastOverall.slice(0, 10)}
                  </span>
                </span>
              )}
            </div>
          )}
        </div>

        <button
          type="button"
          onClick={loadCatalog}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-200 text-sm font-medium rounded-xl transition-colors self-start md:self-auto"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {errorMsg && (
        <div className="p-4 bg-red-950/40 border border-red-800/50 rounded-xl flex items-center gap-3 text-red-400 text-sm">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {(catalog?.instruments?.length ?? 0) > 0 ? (
          catalog?.instruments.map((inst) => {
            const spanDays =
              inst.first_date && inst.last_date
                ? Math.round(
                    (Date.parse(inst.last_date) - Date.parse(inst.first_date)) / 86_400_000,
                  )
                : null;
            return (
              <div
                key={inst.instrument_id}
                className={`bg-gray-900 border p-5 rounded-2xl flex flex-col gap-3 transition-colors ${
                  chartInstrument === inst.instrument_id ? 'border-blue-600/60' : 'border-gray-800'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-lg font-bold text-gray-100">{inst.raw_symbol}</span>
                  <span className="px-2.5 py-0.5 text-xs font-medium bg-blue-950/60 text-blue-400 border border-blue-800/50 rounded-full">
                    {inst.quote_currency}
                  </span>
                </div>

                <div className="grid grid-cols-3 gap-2 text-xs pt-2 border-t border-gray-800/80">
                  <div>
                    <span className="text-gray-500 block">Bars</span>
                    <span className="font-mono text-sm font-semibold text-gray-200">
                      {inst.bars_count.toLocaleString()}
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-500 block">Taker fee</span>
                    <span className="font-mono text-sm text-gray-300">
                      {formatBps(inst.taker_fee, 2)}
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-500 block">Maker fee</span>
                    <span className="font-mono text-sm text-gray-300">
                      {formatBps(inst.maker_fee, 2)}
                    </span>
                  </div>
                </div>

                <div className="text-xs pt-2 border-t border-gray-800/80 flex flex-col gap-1 text-gray-400 font-mono">
                  <div className="flex items-center gap-1.5">
                    <Clock className="w-3.5 h-3.5 text-gray-500" />
                    <span className="text-gray-500">From:</span> {inst.first_date?.slice(0, 19) || 'n/a'}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Clock className="w-3.5 h-3.5 text-gray-500" />
                    <span className="text-gray-500">To:</span> {inst.last_date?.slice(0, 19) || 'n/a'}
                  </div>
                  {spanDays != null && (
                    <div className="text-gray-500">
                      span: {spanDays.toLocaleString()} days ·{' '}
                      {spanDays > 0 ? Math.round(inst.bars_count / spanDays) : '?'} bars/day
                    </div>
                  )}
                </div>

                <div className="flex items-center justify-between gap-2 mt-1">
                  <span className="flex items-center gap-1 text-xs text-emerald-400">
                    <CheckCircle className="w-3.5 h-3.5" />
                    <span>Ready for walk-forward</span>
                  </span>
                  <button
                    type="button"
                    onClick={() => setChartInstrument(inst.instrument_id)}
                    className={`text-[11px] px-2 py-0.5 rounded-lg border ${
                      chartInstrument === inst.instrument_id
                        ? 'bg-blue-600 text-white border-blue-500'
                        : 'bg-gray-950 text-gray-400 border-gray-800 hover:text-gray-200'
                    }`}
                  >
                    chart this
                  </button>
                </div>
              </div>
            );
          })
        ) : (
          <div className="col-span-full p-8 bg-gray-900 border border-gray-800 rounded-2xl text-center text-gray-500">
            No instruments found in this catalog. Run an ingest below to download Binance klines.
          </div>
        )}
      </div>

      {seriesRows.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-3">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <Layers className="w-5 h-5 text-cyan-400" />
              <h3 className="text-sm font-bold text-gray-100">Series beside the bars</h3>
            </div>
            <span
              className={`text-[11px] font-mono px-2 py-0.5 rounded-full border ${
                tickReady
                  ? 'bg-emerald-950/60 text-emerald-400 border-emerald-800/50'
                  : 'bg-amber-950/60 text-amber-300 border-amber-800/50'
              }`}
            >
              {tickReady
                ? 'tick filters usable'
                : 'no ticks: tick VPIN / Hawkes would run on defaults'}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px] font-mono">
              <thead className="text-gray-500">
                <tr>
                  <th className="text-left p-1.5">instrument</th>
                  <th className="text-right p-1.5">bars</th>
                  <th className="text-right p-1.5">taker flow</th>
                  <th className="text-right p-1.5">ticks</th>
                  <th className="text-right p-1.5">depth</th>
                  <th className="text-left p-1.5">ticks until</th>
                  <th className="text-right p-1.5">funding</th>
                </tr>
              </thead>
              <tbody className="text-gray-300">
                {seriesRows.map(({ item, symbol }) => (
                  <tr key={item.instrument_id} className="border-t border-gray-800/60">
                    <td className="p-1.5 text-blue-300">
                      {symbol}
                      {item.symbol && <span className="text-gray-600"> · {item.symbol}</span>}
                    </td>
                    <td className="p-1.5 text-right">{item.bars.rows?.toLocaleString() ?? 'n/a'}</td>
                    <td className="p-1.5 text-right">
                      {item.taker_flow.present ? (
                        <span className="text-emerald-400">
                          {item.taker_flow.rows?.toLocaleString() ?? 'yes'}
                        </span>
                      ) : (
                        <span className="text-amber-400">missing</span>
                      )}
                    </td>
                    <td className="p-1.5 text-right">
                      {item.ticks.present ? (
                        <span className="text-emerald-400">
                          {item.ticks.rows?.toLocaleString() ?? `${item.ticks.files} files`}
                        </span>
                      ) : (
                        <span className="text-amber-400">missing</span>
                      )}
                    </td>
                    <td className="p-1.5 text-right">
                      {item.orderbook.present ? (
                        <span className="text-emerald-400">
                          {item.orderbook.rows?.toLocaleString() ??
                            `${item.orderbook.files} files`}
                        </span>
                      ) : (
                        <span className="text-gray-600">—</span>
                      )}
                    </td>
                    <td className="p-1.5 text-gray-500">
                      {item.ticks.last ? item.ticks.last.slice(0, 10) : '—'}
                    </td>
                    <td className="p-1.5 text-right">
                      {item.funding.present ? (
                        <span className="text-emerald-400">
                          {item.funding.rows?.toLocaleString() ?? 'yes'}
                        </span>
                      ) : (
                        <span className="text-amber-400">missing</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[10px] text-gray-600">
            Tick spans are UTC-day resolution (one Parquet shard per day), so the last day is the
            newest day present, not the newest tick. An empty optional series is read as an empty
            one by the engine — it does not fail the run.
          </p>
        </div>
      )}

      {chartInstrument && (
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-3">
          <h3 className="text-sm font-bold text-gray-100">
            Price preview
            <span className="text-gray-500 font-normal ml-2">
              {catalog?.instruments.find((item) => item.instrument_id === chartInstrument)?.raw_symbol}
            </span>
          </h3>
          <CatalogChart
            instrumentId={chartInstrument}
            catalogPath={selectedCatalogPath}
            barInterval={catalog?.bar_interval}
            limit={600}
            height={300}
            title={catalog?.instruments.find((item) => item.instrument_id === chartInstrument)?.raw_symbol}
          />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="bg-gray-900 border border-gray-800 p-6 rounded-2xl flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <Download className="w-5 h-5 text-emerald-400" />
            <h3 className="text-lg font-bold text-gray-100">Ingest Binance data</h3>
          </div>
          <p className="text-xs text-gray-400">
            Public endpoints only, no API keys. One catalog holds every series; each ingest kind
            writes its own tree, so bars, ticks and funding can be fetched independently.
          </p>

          <div className="flex flex-col gap-3 mt-2">
            <div>
              <label className="text-xs font-medium text-gray-300 block mb-1">Series</label>
              <div className="grid grid-cols-3 gap-1.5">
                {(
                  [
                    ['klines', 'Klines', 'OHLCV bars'],
                    ['trades', 'Trades', 'ticks for VPIN/Hawkes'],
                    ['funding', 'Funding', 'perp settlements'],
                    ['depth', 'Depth', 'live L2 snapshots'],
                  ] as const
                ).map(([value, label, hint]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setIngestSeries(value)}
                    title={hint}
                    className={`px-2 py-2 rounded-xl text-xs font-medium border transition-colors ${
                      ingestSeries === value
                        ? 'bg-blue-600/15 text-blue-300 border-blue-500/40'
                        : 'bg-gray-950 text-gray-400 border-gray-800 hover:text-gray-200'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <span className="text-[10px] text-gray-600 block mt-1">
                {ingestSeries === 'klines'
                  ? 'The bar series every robot reads; supports incremental updates.'
                  : ingestSeries === 'trades'
                    ? 'Aggregated trades into data/agg_trade/ — one file per UTC day. Enables the tick-level VPIN and Hawkes filters.'
                    : ingestSeries === 'funding'
                      ? 'Funding settlements into data/funding/. Always walks the whole requested window.'
                      : 'Live L2 order-book capture over a WebSocket into data/orderbook/. It has no start/end window and runs until you stop it, so keep the start/end fields empty.'}
              </span>
            </div>

            <div>
              <label className="text-xs font-medium text-gray-300 block mb-1">Symbols</label>
              <input
                type="text"
                value={symbols}
                onChange={(e) => setSymbols(e.target.value)}
                placeholder="ETHUSDT,BTCUSDT"
                className="w-full bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 font-mono"
              />
              <span className="text-[10px] text-gray-600">
                USDT pairs only — the catalog maps them to *.SIM instruments.
              </span>
            </div>

            <div>
              <label className="text-xs font-medium text-gray-300 block mb-1">Start date UTC</label>
              <input
                type="text"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                placeholder="2024-01-01"
                className="w-full bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 font-mono"
              />
            </div>

            <div>
              <label className="text-xs font-medium text-gray-300 block mb-1">
                End date UTC (exclusive)
              </label>
              <input
                type="text"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                placeholder="leave empty for now"
                className="w-full bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 font-mono"
              />
            </div>

            <button
              type="button"
              onClick={() => startIngest(false)}
              disabled={ingestRunning || !symbols.trim()}
              className="w-full py-3 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-800 text-white font-medium rounded-xl flex items-center justify-center gap-2"
            >
              {ingestRunning ? (
                <RefreshCw className="w-5 h-5 animate-spin" />
              ) : (
                <Download className="w-5 h-5" />
              )}
              {ingestSeries === 'klines'
                ? 'Full ingest (klines)'
                : ingestSeries === 'trades'
                  ? 'Fetch aggregated trades'
                  : ingestSeries === 'funding'
                    ? 'Fetch funding history'
                    : 'Start live depth capture'}
            </button>

            <button
              type="button"
              onClick={() => startIngest(true)}
              disabled={ingestRunning || !symbols.trim() || ingestSeries !== 'klines'}
              title={
                ingestSeries === 'klines'
                  ? 'Fetch only bars newer than the last stored one'
                  : 'Only the bar series supports incremental updates'
              }
              className="w-full py-3 bg-blue-700 hover:bg-blue-600 disabled:bg-gray-800 disabled:text-gray-500 text-white font-medium rounded-xl flex items-center justify-center gap-2"
            >
              <Plus className="w-5 h-5" />
              Update bars (incremental)
            </button>

            {ingestRunning && (
              <button
                type="button"
                onClick={handleCancelIngest}
                className="w-full py-2 bg-red-950/60 hover:bg-red-900/60 text-red-300 border border-red-800/60 text-sm font-medium rounded-xl flex items-center justify-center gap-2"
              >
                <Square className="w-3.5 h-3.5" />
                Stop ingest
              </button>
            )}
          </div>
        </div>

        <div className="lg:col-span-2 bg-[#0a0f18] border border-gray-800 rounded-2xl flex flex-col overflow-hidden h-[400px]">
          <div className="bg-gray-900/80 px-4 py-2.5 border-b border-gray-800 flex justify-between items-center">
            <span className="text-xs font-mono text-gray-400">Ingest log</span>
            <span className="text-[11px] font-mono text-gray-500">
              {ingestRunning ? 'streaming…' : 'idle'}
            </span>
          </div>
          <div className="p-4 flex-1 overflow-y-auto font-mono text-xs text-emerald-400 whitespace-pre-wrap">
            {ingestLog || 'Ready to download data.\n'}
          </div>
        </div>
      </div>
    </div>
  );
};
