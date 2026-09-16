import React, { useEffect, useState } from 'react';
import { AlertTriangle, Play, RefreshCw, Square, Terminal } from 'lucide-react';
import {
  cancelPaper,
  fetchPaperLog,
  runPaper,
} from '../services/api';
import type { PaperSummary, StrategySpec } from '../services/api';

interface PaperSimulatorProps {
  strategies: StrategySpec[];
}

export const PaperSimulator: React.FC<PaperSimulatorProps> = ({ strategies }) => {
  const [robot, setRobot] = useState('regime');
  const [bars, setBars] = useState(500);
  const [source, setSource] = useState<'synthetic' | 'catalog'>('synthetic');
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState('');
  const [summary, setSummary] = useState<PaperSummary | null>(null);

  const wired = strategies.filter((s) => s.wired_in_backtest);

  const pollLog = async () => {
    try {
      const data = await fetchPaperLog();
      setLog(data.log);
      setSummary(data.summary);
      setRunning(data.is_running);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    pollLog();
    const timer = setInterval(pollLog, 2000);
    return () => clearInterval(timer);
  }, []);

  const handleRun = async () => {
    try {
      await runPaper({ robot, bars, source });
      setRunning(true);
      pollLog();
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-bold text-gray-100">Paper Simulator</h2>
        <p className="text-sm text-gray-400 mt-1">
          Log hypothetical orders from strategy signals. No exchange submission, no position state.
        </p>
      </div>

      <div className="p-4 rounded-xl bg-amber-950/20 border border-amber-800/30 flex gap-3 text-sm text-amber-200">
        <AlertTriangle className="w-5 h-5 shrink-0" />
        <span>
          Paper mode is not live trading. Orders are written to the log only — there is no execution
          adapter and no portfolio tracking.
        </span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 space-y-4">
          <label className="text-xs text-gray-400">Robot</label>
          <select
            value={robot}
            onChange={(e) => setRobot(e.target.value)}
            className="w-full bg-gray-950 border border-gray-800 rounded-xl px-3 py-2 text-sm"
          >
            {wired.map((s) => (
              <option key={s.name} value={s.name}>
                {s.name}
              </option>
            ))}
          </select>

          <label className="text-xs text-gray-400">Bar source</label>
          <select
            value={source}
            onChange={(e) => setSource(e.target.value as 'synthetic' | 'catalog')}
            className="w-full bg-gray-950 border border-gray-800 rounded-xl px-3 py-2 text-sm"
          >
            <option value="synthetic">Synthetic (smoke)</option>
            <option value="catalog">Parquet catalog</option>
          </select>

          <label className="text-xs text-gray-400">Bars</label>
          <input
            type="number"
            value={bars}
            onChange={(e) => setBars(Number(e.target.value))}
            className="w-full bg-gray-950 border border-gray-800 rounded-xl px-3 py-2 text-sm font-mono"
          />

          <div className="flex gap-2">
            <button
              onClick={handleRun}
              disabled={running}
              className="flex-1 flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-xl py-2.5 text-sm"
            >
              <Play className="w-4 h-4" /> Run paper
            </button>
            {running && (
              <button
                onClick={() => cancelPaper().then(pollLog)}
                className="px-4 bg-red-950/50 border border-red-800/40 text-red-300 rounded-xl"
              >
                <Square className="w-4 h-4" />
              </button>
            )}
            <button onClick={pollLog} className="px-3 bg-gray-800 rounded-xl text-gray-300">
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>

          {summary && summary.order_count != null && (
            <div className="text-sm font-mono text-gray-400">
              orders logged: {summary.order_count}
            </div>
          )}
        </div>

        <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-2xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <Terminal className="w-5 h-5 text-gray-400" />
            <h3 className="font-semibold text-gray-100">Paper Log</h3>
          </div>
          <pre className="min-h-[280px] bg-gray-950 border border-gray-800 rounded-xl p-4 text-xs font-mono text-gray-300 overflow-auto whitespace-pre-wrap">
            {log || 'No paper run yet.'}
          </pre>
        </div>
      </div>
    </div>
  );
};
