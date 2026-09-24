import React, { useEffect, useState } from 'react';
import { AlertTriangle, History, ListOrdered, Play, RefreshCw, Square, Terminal, Zap } from 'lucide-react';
import { cancelPaper, fetchPaperLog, fetchPaperSessions, runPaper } from '../services/api';
import type {
  PaperOrder,
  PaperPortfolio,
  PaperSessionRow,
  PaperSummary,
  StatusResponse,
  StrategySpec,
} from '../services/api';
import { LiveTradingTerminal } from './LiveTradingTerminal';
import { SessionsPanel } from './SessionsPanel';

interface PaperSimulatorProps {
  strategies: StrategySpec[];
  status: StatusResponse | null;
}

/**
 * Paper mode supports both interactive real-time simulation with live charts/stops
 * and historical batch replay for order generation checks.
 */
export const PaperSimulator: React.FC<PaperSimulatorProps> = ({ strategies, status }) => {
  const supported = status?.paper_robots ?? ['regime', 'ema', 'adaptive_ema'];
  const liveRobots = status?.live_paper_robots ?? ['regime', 'ema', 'adaptive_ema', 'hold'];
  const available = strategies.filter((spec) => supported.includes(spec.name));

  // Live sessions: the table above the terminal, and which one the terminal shows.
  const [sessionRows, setSessionRows] = useState<PaperSessionRow[]>([]);
  const [portfolio, setPortfolio] = useState<PaperPortfolio | null>(null);
  const [selectedSession, setSelectedSession] = useState<string | null>(null);
  const [autoSelected, setAutoSelected] = useState(false);

  const refreshSessions = async () => {
    try {
      const data = await fetchPaperSessions();
      setSessionRows(data.sessions);
      setPortfolio(data.portfolio);
      if (!autoSelected) {
        // Open on the first running session once; afterwards the user's choice wins.
        const first = data.sessions.find((row) => row.status !== 'stopped');
        if (first) setSelectedSession(first.session_id);
        setAutoSelected(true);
      }
    } catch (err) {
      console.error('Failed to load paper sessions:', err);
    }
  };

  useEffect(() => {
    refreshSessions();
    const timer = setInterval(refreshSessions, 5000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoSelected]);

  const handleSessionChange = (sessionId: string | null) => {
    setSelectedSession(sessionId);
    setAutoSelected(true);
    refreshSessions();
  };

  const [activeSubTab, setActiveSubTab] = useState<'live' | 'batch'>('live');
  const [robot, setRobot] = useState(supported[0] ?? 'regime');
  const [bars, setBars] = useState(500);
  const [source, setSource] = useState<'synthetic' | 'catalog'>('synthetic');
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState('');
  const [summary, setSummary] = useState<PaperSummary | null>(null);
  const [orders, setOrders] = useState<PaperOrder[]>([]);
  const [error, setError] = useState<string | null>(null);

  const pollLog = async () => {
    try {
      const data = await fetchPaperLog();
      setLog(data.log);
      setSummary(data.summary);
      setRunning(data.is_running);
      const payload = data.result as { orders?: PaperOrder[] } | null;
      setOrders(payload?.orders ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to read the paper log');
    }
  };

  useEffect(() => {
    pollLog();
    const timer = setInterval(pollLog, 3000);
    return () => clearInterval(timer);
  }, []);

  const handleRun = async () => {
    setError(null);
    try {
      const response = await runPaper({ robot, bars, source });
      if (response.status !== 'started') {
        setError(response.message ?? 'The paper run was refused by the API.');
        return;
      }
      setRunning(true);
      setOrders([]);
      pollLog();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start the paper run');
    }
  };

  const handleCancel = async () => {
    try {
      const response = await cancelPaper();
      if (response.status === 'idle') setError(response.message ?? null);
      pollLog();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel');
    }
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Subtab Navigation */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-gray-800 pb-3">
        <div className="flex items-center gap-2 bg-[#0d131f] border border-gray-800 p-1 rounded-xl">
          <button
            type="button"
            onClick={() => setActiveSubTab('live')}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              activeSubTab === 'live'
                ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            <Zap className="w-3.5 h-3.5 text-blue-400" /> Live Interactive Terminal
          </button>
          {status?.lab_role !== 'paper' && (
            <button
              type="button"
              onClick={() => setActiveSubTab('batch')}
              className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                activeSubTab === 'batch'
                  ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              <History className="w-3.5 h-3.5" /> Batch Historical Replay
            </button>
          )}
        </div>

        <span className="text-[11px] font-mono text-gray-500">
          {activeSubTab === 'live'
            ? 'Real-time WebSocket streaming, visual SL/TP & floating PnL'
            : 'Static order log simulation against historical bars'}
        </span>
      </div>

      {activeSubTab === 'live' ? (
        <div className="flex flex-col gap-5">
          <SessionsPanel
            rows={sessionRows}
            portfolio={portfolio}
            selectedId={selectedSession}
            onSelect={handleSessionChange}
            onChanged={refreshSessions}
          />
          <LiveTradingTerminal
            key={selectedSession ?? 'new'}
            supportedRobots={liveRobots}
            sessionId={selectedSession}
            onSessionChange={handleSessionChange}
          />
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          <div>
            <h2 className="text-xl font-bold text-gray-100">Paper Simulator (Batch Replay)</h2>
            <p className="text-sm text-gray-400 mt-1">
              Logs the orders a robot would have sent. No exchange submission and no position state —
              the log can contain several consecutive buys, which is a simplification rather than a bug.
            </p>
          </div>

          <div className="p-4 rounded-xl bg-amber-950/20 border border-amber-800/30 flex gap-3 text-sm text-amber-200">
            <AlertTriangle className="w-5 h-5 shrink-0" />
            <span>
              Paper mode is not live trading. There is no execution adapter in this lab, so nothing here
              can reach an exchange.
            </span>
          </div>

          {error && (
            <div className="p-3 rounded-xl bg-red-950/30 border border-red-800/40 text-red-300 text-xs">
              {error}
            </div>
          )}

          {available.length < strategies.filter((spec) => spec.wired_in_backtest).length && (
            <div className="p-3 rounded-xl bg-gray-900 border border-gray-800 text-[11px] text-gray-400">
              Offered robots: <span className="font-mono text-gray-300">{supported.join(', ')}</span>. The
              other wired robots have no paper adapter yet; the API refuses them instead of substituting
              a different robot.
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 space-y-4">
              <label className="text-xs text-gray-400">Robot</label>
              <select
                value={robot}
                onChange={(e) => setRobot(e.target.value)}
                className="w-full bg-gray-950 border border-gray-800 rounded-xl px-3 py-2 text-sm"
              >
                {available.map((spec) => (
                  <option key={spec.name} value={spec.name}>
                    {spec.name}
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
                  type="button"
                  onClick={handleRun}
                  disabled={running}
                  className="flex-1 flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-xl py-2.5 text-sm"
                >
                  <Play className="w-4 h-4" /> Run paper
                </button>
                {running && (
                  <button
                    type="button"
                    onClick={handleCancel}
                    className="px-4 bg-red-950/50 border border-red-800/40 text-red-300 rounded-xl"
                  >
                    <Square className="w-4 h-4" />
                  </button>
                )}
                <button
                  type="button"
                  onClick={pollLog}
                  className="px-3 bg-gray-800 rounded-xl text-gray-300"
                >
                  <RefreshCw className="w-4 h-4" />
                </button>
              </div>

              {summary && (
                <div className="text-xs font-mono text-gray-400 border-t border-gray-800 pt-3 space-y-1">
                  <div>
                    order_count:{' '}
                    <span className="text-gray-200">{summary.order_count ?? 0}</span>
                  </div>
                  {summary.robot && <div>robot: {summary.robot}</div>}
                  {summary.is_error && (
                    <div className="text-red-400">{summary.error_message ?? 'run failed'}</div>
                  )}
                  {summary.disclaimer && <div className="text-gray-600">{summary.disclaimer}</div>}
                </div>
              )}
            </div>

            <div className="lg:col-span-2 flex flex-col gap-4">
              <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-3">
                <div className="flex items-center gap-2">
                  <ListOrdered className="w-5 h-5 text-gray-400" />
                  <h3 className="font-semibold text-gray-100">Orders logged</h3>
                  <span className="text-xs font-mono text-gray-500">{orders.length}</span>
                </div>
                {orders.length === 0 ? (
                  <p className="text-xs text-gray-500">No orders logged yet.</p>
                ) : (
                  <div className="overflow-auto max-h-64 border border-gray-800 rounded-xl">
                    <table className="w-full text-[11px] font-mono">
                      <thead className="bg-gray-950/80 text-gray-400 sticky top-0">
                        <tr>
                          <th className="text-left p-2">time (UTC)</th>
                          <th className="text-left p-2">instrument</th>
                          <th className="text-left p-2">side</th>
                          <th className="text-right p-2">qty</th>
                          <th className="text-left p-2">reason</th>
                        </tr>
                      </thead>
                      <tbody className="text-gray-300">
                        {orders.map((order: PaperOrder, index: number) => (
                          <tr key={`${order.ts}-${index}`} className="border-t border-gray-800/60">
                            <td className="p-2 whitespace-nowrap">{order.ts.slice(0, 19)}</td>
                            <td className="p-2">{order.instrument_id}</td>
                            <td
                              className={`p-2 ${
                                order.side.toUpperCase().includes('BUY')
                                  ? 'text-emerald-400'
                                  : 'text-red-400'
                              }`}
                            >
                              {order.side}
                            </td>
                            <td className="p-2 text-right">{order.qty}</td>
                            <td className="p-2 text-gray-500">{order.reason}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
                <div className="flex items-center gap-2 mb-3">
                  <Terminal className="w-5 h-5 text-gray-400" />
                  <h3 className="font-semibold text-gray-100">Paper log</h3>
                  {running && <span className="text-xs text-amber-400 animate-pulse">running…</span>}
                </div>
                <pre className="min-h-[200px] bg-gray-950 border border-gray-800 rounded-xl p-4 text-xs font-mono text-gray-300 overflow-auto whitespace-pre-wrap">
                  {log || 'No paper run yet.'}
                </pre>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
