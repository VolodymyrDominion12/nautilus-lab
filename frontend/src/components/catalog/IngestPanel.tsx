import React, { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Download, Plus, RefreshCw, Square } from 'lucide-react';

import { cancelIngest, runIngest } from '../../services/api';
import type { IngestSeries } from '../../services/api';
import { ingestLogQuery } from '../../services/queries';

interface IngestPanelProps {
  selectedCatalogPath: string;
  /** The ingest ended (finished, failed or cancelled): its data may have changed. */
  onFinished: () => void;
  onError: (message: string) => void;
}

function startMessage(series: IngestSeries, incremental: boolean): string {
  if (series === 'trades') {
    return 'Fetching aggregated trades (ticks) — needed by the tick-level VPIN and Hawkes filters...\n';
  }
  if (series === 'funding') return 'Fetching funding settlements for the perpetual...\n';
  if (series === 'depth') {
    return 'Opening the Binance depth WebSocket — this records until you press Stop...\n';
  }
  return incremental
    ? 'Incremental update: fetching bars after the last stored timestamp...\n'
    : 'Launching Binance klines download into the Parquet catalog...\n';
}

/** The ingest form, its start/stop buttons and the streamed log of the running job. */
export const IngestPanel: React.FC<IngestPanelProps> = ({
  selectedCatalogPath,
  onFinished,
  onError,
}) => {
  const [symbols, setSymbols] = useState('ETHUSDT,BTCUSDT');
  const [startDate, setStartDate] = useState('2024-01-01');
  const [endDate, setEndDate] = useState('');
  const [ingestSeries, setIngestSeries] = useState<IngestSeries>('klines');
  const [ingestLog, setIngestLog] = useState('');
  /** Button state: true from the click until the server reports the job idle. */
  const [ingestRunning, setIngestRunning] = useState(false);
  /** Log polling: only once the API has accepted the job. */
  const [polling, setPolling] = useState(false);
  /** When polling began; an answer older than this is from a previous run. */
  const pollingSince = useRef(0);

  const logQuery = useQuery(ingestLogQuery(polling));

  useEffect(() => {
    const res = logQuery.data;
    if (!polling || !res || logQuery.dataUpdatedAt < pollingSince.current) return;
    setIngestLog(res.log);
    // Stop as soon as the server reports idle, whatever the log says (BUG-1: waiting for
    // "Process finished" left the button stuck when the process crashed or was cancelled).
    if (!res.is_running) {
      setPolling(false);
      setIngestRunning(false);
      onFinished();
    }
  }, [logQuery.data, logQuery.dataUpdatedAt, polling, onFinished]);

  const startIngest = async (incremental: boolean) => {
    onError('');
    setIngestRunning(true);
    setIngestLog(startMessage(ingestSeries, incremental));
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
      if (response.status === 'started') {
        pollingSince.current = Date.now();
        setPolling(true);
      } else {
        setIngestRunning(false);
        onError(response.message ?? 'The ingest was refused by the API.');
      }
    } catch (err) {
      setIngestRunning(false);
      setIngestLog((prev) => `${prev}\nError: ${err instanceof Error ? err.message : err}\n`);
    }
  };

  const cancel = async () => {
    try {
      const response = await cancelIngest();
      setIngestLog((prev) => `${prev}\n${response.message ?? response.status}\n`);
      if (response.status === 'idle') {
        setPolling(false);
        setIngestRunning(false);
      }
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Failed to cancel the ingest');
    }
  };

  return (
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
              onClick={cancel}
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
  );
};
