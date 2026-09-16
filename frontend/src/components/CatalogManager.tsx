import React, { useEffect, useState } from 'react';
import { Database, Download, RefreshCw, AlertCircle, CheckCircle, Clock, Plus } from 'lucide-react';
import { CatalogChart } from './CatalogChart';
import { fetchCatalog, fetchCatalogs, fetchIngestLog, runIngest } from '../services/api';
import type { CatalogResponse, CatalogSummary } from '../services/api';

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
  const [ingestLog, setIngestLog] = useState('');
  const [errorMsg, setErrorMsg] = useState('');

  const loadCatalog = async () => {
    setLoading(true);
    try {
      const [data, catalogs] = await Promise.all([
        fetchCatalog(selectedCatalogPath),
        fetchCatalogs(),
      ]);
      setCatalog(data);
      setCatalogOptions(catalogs.catalogs);
      if (!selectedCatalogPath && catalogs.default) {
        onCatalogChange(catalogs.default);
      }
      setErrorMsg('');
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to load catalog');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCatalog();
  }, [selectedCatalogPath]);

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    if (ingestRunning) {
      interval = setInterval(async () => {
        try {
          const res = await fetchIngestLog();
          setIngestLog(res.log);
          if (!res.is_running && res.log.includes('Process finished')) {
            setIngestRunning(false);
            loadCatalog();
          }
        } catch (err) {
          console.error(err);
        }
      }, 1500);
    }
    return () => clearInterval(interval);
  }, [ingestRunning]);

  const startIngest = async (incremental: boolean) => {
    setIngestRunning(true);
    setIngestLog(
      incremental
        ? 'Incremental update: fetching bars after last stored timestamp...\n'
        : 'Launching Binance klines download into Parquet catalog...\n',
    );
    try {
      await runIngest({
        symbols: symbols.trim(),
        start: incremental ? undefined : startDate || undefined,
        end: endDate ? endDate : undefined,
        catalog: selectedCatalogPath || undefined,
        incremental,
      });
    } catch (err: any) {
      setIngestRunning(false);
      setIngestLog((prev) => prev + `\nError: ${err.message}`);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-gray-900 border border-gray-800 p-6 rounded-2xl">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <Database className="w-6 h-6 text-blue-400" />
            <h2 className="text-xl font-bold text-gray-100">Parquet Data Catalog</h2>
          </div>
          <p className="text-sm text-gray-400 mt-1">
            One catalog directory = one bar interval. Select the catalog used by research and ML jobs.
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
        </div>

        <button
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
        {catalog?.instruments && catalog.instruments.length > 0 ? (
          catalog.instruments.map((inst) => (
            <div
              key={inst.instrument_id}
              className="bg-gray-900 border border-gray-800 p-5 rounded-2xl flex flex-col gap-3 hover:border-gray-700 transition-colors"
            >
              <div className="flex items-center justify-between">
                <span className="text-lg font-bold text-gray-100">{inst.raw_symbol}</span>
                <span className="px-2.5 py-0.5 text-xs font-medium bg-blue-950/60 text-blue-400 border border-blue-800/50 rounded-full">
                  {inst.quote_currency}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-2 text-xs pt-2 border-t border-gray-800/80">
                <div>
                  <span className="text-gray-500 block">Bars Count</span>
                  <span className="font-mono text-sm font-semibold text-gray-200">
                    {inst.bars_count.toLocaleString()}
                  </span>
                </div>
                <div>
                  <span className="text-gray-500 block">Taker Fee</span>
                  <span className="font-mono text-sm text-gray-300">
                    {(inst.taker_fee * 100).toFixed(3)}%
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
              </div>

              <div className="flex items-center gap-1 text-xs text-emerald-400 mt-1">
                <CheckCircle className="w-3.5 h-3.5" />
                <span>Ready for Walk-Forward</span>
              </div>
            </div>
          ))
        ) : (
          <div className="col-span-full p-8 bg-gray-900 border border-gray-800 rounded-2xl text-center text-gray-500">
            No instruments found in catalog. Run ingest below to download Binance klines.
          </div>
        )}
      </div>

      {catalog?.instruments?.[0] && (
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-3">
          <h3 className="text-sm font-bold text-gray-100">
            Catalog preview — {catalog.instruments[0].raw_symbol}
          </h3>
          <CatalogChart
            instrumentId={catalog.instruments[0].instrument_id}
            catalogPath={selectedCatalogPath}
            limit={600}
            height={300}
          />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="bg-gray-900 border border-gray-800 p-6 rounded-2xl flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <Download className="w-5 h-5 text-emerald-400" />
            <h3 className="text-lg font-bold text-gray-100">Ingest Binance Klines</h3>
          </div>
          <p className="text-xs text-gray-400">
            Full ingest uses the start date below. Incremental update appends only new bars after the last stored bar.
          </p>

          <div className="flex flex-col gap-3 mt-2">
            <div>
              <label className="text-xs font-medium text-gray-300 block mb-1">Symbols</label>
              <input
                type="text"
                value={symbols}
                onChange={(e) => setSymbols(e.target.value)}
                placeholder="ETHUSDT,BTCUSDT"
                className="w-full bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 font-mono"
              />
            </div>

            <div>
              <label className="text-xs font-medium text-gray-300 block mb-1">Start Date UTC</label>
              <input
                type="text"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                placeholder="2024-01-01"
                className="w-full bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 font-mono"
              />
            </div>

            <div>
              <label className="text-xs font-medium text-gray-300 block mb-1">End Date UTC</label>
              <input
                type="text"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                placeholder="Leave empty for Now"
                className="w-full bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 font-mono"
              />
            </div>

            <button
              onClick={() => startIngest(false)}
              disabled={ingestRunning || !symbols.trim()}
              className="w-full py-3 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-800 text-white font-medium rounded-xl flex items-center justify-center gap-2"
            >
              {ingestRunning ? <RefreshCw className="w-5 h-5 animate-spin" /> : <Download className="w-5 h-5" />}
              Full ingest
            </button>

            <button
              onClick={() => startIngest(true)}
              disabled={ingestRunning || !symbols.trim()}
              className="w-full py-3 bg-blue-700 hover:bg-blue-600 disabled:bg-gray-800 text-white font-medium rounded-xl flex items-center justify-center gap-2"
            >
              <Plus className="w-5 h-5" />
              Update catalog (incremental)
            </button>
          </div>
        </div>

        <div className="lg:col-span-2 bg-[#0a0f18] border border-gray-800 rounded-2xl flex flex-col overflow-hidden h-[340px]">
          <div className="bg-gray-900/80 px-4 py-2.5 border-b border-gray-800">
            <span className="text-xs font-mono text-gray-400">Ingest Log Output</span>
          </div>
          <div className="p-4 flex-1 overflow-y-auto font-mono text-xs text-emerald-400 whitespace-pre-wrap">
            {ingestLog || 'Ready to download data.\n'}
          </div>
        </div>
      </div>
    </div>
  );
};
