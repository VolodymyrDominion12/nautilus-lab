import React, { useState } from 'react';
import { AlertTriangle, Pause, Play, Plus, Square } from 'lucide-react';
import { pauseLivePaper, stopLivePaper } from '../services/api';
import type { PaperPortfolio, PaperSessionRow } from '../services/api';

interface SessionsPanelProps {
  rows: PaperSessionRow[];
  portfolio: PaperPortfolio | null;
  selectedId: string | null;
  onSelect: (sessionId: string | null) => void;
  onChanged: () => void;
}

const INTERVAL_SECONDS: Record<string, number> = {
  '1m': 60,
  '3m': 180,
  '5m': 300,
  '15m': 900,
  '30m': 1800,
  '1h': 3600,
  '4h': 14400,
  '1d': 86400,
};

const pct = (value: number | null | undefined, digits = 2) =>
  value === null || value === undefined ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;

const pp = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(2)} pp`;

const tone = (value: number | null | undefined) =>
  value === null || value === undefined ? 'text-gray-400' : value >= 0 ? 'text-emerald-400' : 'text-red-400';

/** "10:00 UTC", flagged when no bar closed for 2.5 intervals (the feed may be stuck). */
function lastBar(row: PaperSessionRow): { label: string; stale: boolean } {
  if (!row.last_bar_ts) return { label: '—', stale: row.status !== 'stopped' };
  const ts = new Date(row.last_bar_ts);
  const step = INTERVAL_SECONDS[row.interval] ?? 3600;
  // The stored time is the bar's open; it closed one interval later.
  const ageSeconds = (Date.now() - ts.getTime()) / 1000 - step;
  return {
    label: `${ts.toISOString().slice(11, 16)} UTC`,
    stale: row.status !== 'stopped' && ageSeconds > step * 2.5,
  };
}

const STATUS_STYLE: Record<PaperSessionRow['status'], string> = {
  active: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  paused: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  stopped: 'bg-gray-700/30 text-gray-400 border-gray-700',
};

/**
 * All live paper sessions at a glance: is everything running, and which robot beats the
 * buy-and-hold benchmark on its own market. Clicking a row opens it in the terminal.
 */
export const SessionsPanel: React.FC<SessionsPanelProps> = ({
  rows,
  portfolio,
  selectedId,
  onSelect,
  onChanged,
}) => {
  const [showStopped, setShowStopped] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const live = rows.filter((row) => row.status !== 'stopped');
  const stopped = rows.filter((row) => row.status === 'stopped');
  const visible = showStopped ? [...live, ...stopped] : live;

  const act = async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed');
    }
  };

  const stop = (row: PaperSessionRow) => {
    const confirmed = window.confirm(
      `Stop "${row.name}" for good?\n\nA stopped session is not resumed after a restart and is ` +
        'not restarted from the portfolio file. Use Pause to only halt new entries.',
    );
    if (!confirmed) return;
    act(() => stopLivePaper(row.session_id)).then(() => {
      if (selectedId === row.session_id) onSelect(null);
    });
  };

  return (
    <div className="bg-[#0d131f] border border-gray-800 rounded-2xl p-4 flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-200">Paper sessions</h3>
          <p className="text-[11px] text-gray-500">
            One robot, one virtual account and one journal per session. Compare each robot with
            the <span className="font-mono">hold</span> benchmark on the same market.
          </p>
        </div>
        <div className="flex items-center gap-4 text-xs">
          {portfolio && (
            <>
              <span className="text-gray-400">
                Equity{' '}
                <span className="font-mono text-gray-100">
                  {portfolio.equity.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </span>{' '}
                <span className={`font-mono ${tone(portfolio.return_pct)}`}>
                  {pct(portfolio.return_pct)}
                </span>
              </span>
              <span className="text-gray-400">
                {portfolio.sessions_active} active · {portfolio.sessions_paused} paused ·{' '}
                max {portfolio.max_sessions}
              </span>
            </>
          )}
          <button
            type="button"
            onClick={() => onSelect(null)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-semibold ${
              selectedId === null
                ? 'bg-blue-600/25 border-blue-500/40 text-blue-300'
                : 'border-gray-700 text-gray-300 hover:bg-gray-800/60'
            }`}
          >
            <Plus className="w-3.5 h-3.5" /> New session
          </button>
        </div>
      </div>

      {portfolio && portfolio.feeds.length > 0 && (
        <div className="flex flex-wrap gap-2 text-[11px]">
          {portfolio.feeds.map((feed) => (
            <span
              key={`${feed.symbol}-${feed.interval}`}
              className={`px-2 py-0.5 rounded-md border font-mono ${
                feed.connected
                  ? 'border-emerald-700/50 text-emerald-300'
                  : 'border-red-700/50 text-red-300'
              }`}
              title={`${feed.sessions} session(s), ${feed.messages} messages`}
            >
              {feed.symbol} {feed.interval} {feed.connected ? 'live' : 'reconnecting'}
            </span>
          ))}
        </div>
      )}

      {portfolio?.warnings.map((warning) => (
        <div
          key={warning}
          className="flex items-center gap-2 text-[11px] text-amber-300 bg-amber-950/30 border border-amber-800/40 rounded-lg px-2.5 py-1.5"
        >
          <AlertTriangle className="w-3.5 h-3.5" /> {warning}
        </div>
      ))}

      {error && <div className="text-[11px] text-red-400">{error}</div>}

      {visible.length === 0 ? (
        <div className="text-xs text-gray-500 border border-dashed border-gray-800 rounded-xl py-5 text-center">
          No sessions yet. Declare them in deploy/paper_portfolio.yaml, or press “New session”.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-gray-500 text-left">
                <th className="py-1.5 pr-3 font-medium">Session</th>
                <th className="py-1.5 pr-3 font-medium">Status</th>
                <th className="py-1.5 pr-3 font-medium text-right">Equity</th>
                <th className="py-1.5 pr-3 font-medium text-right">Return</th>
                <th className="py-1.5 pr-3 font-medium text-right" title="Return minus the hold session on the same symbol and interval">
                  vs hold
                </th>
                <th className="py-1.5 pr-3 font-medium">Position</th>
                <th className="py-1.5 pr-3 font-medium text-right">Trades</th>
                <th className="py-1.5 pr-3 font-medium text-right">Max DD</th>
                <th className="py-1.5 pr-3 font-medium">Last bar</th>
                <th className="py-1.5 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => {
                const bar = lastBar(row);
                const selected = row.session_id === selectedId;
                return (
                  <tr
                    key={row.session_id}
                    onClick={() => !row.history_only && onSelect(row.session_id)}
                    className={`border-t border-gray-800/70 ${
                      row.history_only ? 'opacity-60' : 'cursor-pointer hover:bg-gray-800/30'
                    } ${selected ? 'bg-blue-600/10' : ''}`}
                    title={row.notes || row.status_message || ''}
                  >
                    <td className="py-2 pr-3">
                      <div className="font-mono text-gray-100">{row.name}</div>
                      <div className="text-[10px] text-gray-500">
                        {row.robot} · {row.symbol} {row.interval}
                        {row.created_from ? ` · ${row.created_from}` : ''}
                      </div>
                    </td>
                    <td className="py-2 pr-3">
                      <span className={`px-2 py-0.5 rounded-md border text-[10px] ${STATUS_STYLE[row.status]}`}>
                        {row.status}
                      </span>
                      {row.risk_refusals ? (
                        <span
                          className="ml-1.5 text-[10px] text-amber-400"
                          title="Entries refused by the risk breakers"
                        >
                          {row.risk_refusals} blocked
                        </span>
                      ) : null}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono text-gray-200">
                      {Number(row.equity || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                    </td>
                    <td className={`py-2 pr-3 text-right font-mono ${tone(row.return_pct)}`}>
                      {pct(row.return_pct)}
                    </td>
                    <td className={`py-2 pr-3 text-right font-mono ${tone(row.vs_benchmark_pp)}`}>
                      {row.robot === 'hold' ? 'benchmark' : pp(row.vs_benchmark_pp)}
                    </td>
                    <td className="py-2 pr-3 font-mono text-gray-300">{row.position ?? 'flat'}</td>
                    <td className="py-2 pr-3 text-right font-mono text-gray-300">
                      {row.closed_trades ?? row.fills}
                      {row.wins !== undefined ? ` / ${row.wins}w` : ''}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono text-gray-300">
                      {row.max_drawdown_pct !== undefined ? `${row.max_drawdown_pct.toFixed(2)}%` : '—'}
                    </td>
                    <td className={`py-2 pr-3 font-mono ${bar.stale ? 'text-red-400' : 'text-gray-400'}`}>
                      {bar.label}
                      {bar.stale ? ' ⚠' : ''}
                    </td>
                    <td className="py-2 text-right whitespace-nowrap">
                      {row.status !== 'stopped' && (
                        <div className="inline-flex gap-1.5" onClick={(e) => e.stopPropagation()}>
                          <button
                            type="button"
                            onClick={() => act(() => pauseLivePaper(row.session_id, row.status === 'active'))}
                            className="p-1.5 rounded-md border border-gray-700 text-gray-300 hover:bg-gray-800"
                            title={row.status === 'active' ? 'Pause new entries' : 'Resume entries'}
                          >
                            {row.status === 'active' ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                          </button>
                          <button
                            type="button"
                            onClick={() => stop(row)}
                            className="p-1.5 rounded-md border border-red-800/60 text-red-300 hover:bg-red-950/40"
                            title="Stop for good"
                          >
                            <Square className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {stopped.length > 0 && (
        <button
          type="button"
          onClick={() => setShowStopped((value) => !value)}
          className="self-start text-[11px] text-gray-500 hover:text-gray-300"
        >
          {showStopped ? 'Hide' : 'Show'} stopped sessions ({stopped.length})
        </button>
      )}
    </div>
  );
};
