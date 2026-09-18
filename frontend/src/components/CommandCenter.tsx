import React, { useEffect, useState } from 'react';
import {
  Activity,
  BookOpen,
  Brain,
  Database,
  FlaskConical,
  Gauge,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { fetchCommandCenter } from '../services/api';
import type { CommandCenterResponse } from '../services/api';
import { MetricCard } from './MetricCard';
import { formatBps, formatDateTime, formatElapsed, formatPct, toNumber } from '../lib/format';
import { verdictFor } from '../lib/research';

/**
 * The lab's front page.
 *
 * Deliberately built around the two questions that decide whether work continues: what did
 * the last out-of-sample run actually prove, and is anything running right now. The old
 * version dumped `last_run.json` as raw JSON, which is data without a reading.
 */
export const CommandCenter: React.FC = () => {
  const [data, setData] = useState<CommandCenterResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    fetchCommandCenter()
      .then((payload) => {
        setData(payload);
        setError(null);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Failed to load the command center'),
      );
  };

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, []);

  const jobs = data?.jobs ?? {};
  const journal = data?.journal ?? {};
  const last = data?.last_research ?? null;
  const verdict = verdictFor(last);
  const multi = last?.multi_window ?? null;
  const single = last?.single_backtest ?? null;

  const meanOos = toNumber(multi?.mean_oos_raw);
  const excess = toNumber(multi?.mean_excess_return_raw);

  const experimentRows = data?.recent_experiments ?? [];
  const bestExperiment = experimentRows.reduce<{ label: string; value: number } | null>(
    (best, entry) => {
      const value = toNumber(entry.multi_window?.mean_excess_return_raw);
      if (value == null) return best;
      if (best == null || value > best.value) {
        return { label: `${entry.robot} · ${entry.finished_at?.slice(0, 16) ?? ''}`, value };
      }
      return best;
    },
    null,
  );

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-100 flex items-center gap-2">
            <Activity className="w-6 h-6 text-blue-400" />
            Command Center
          </h2>
          <p className="text-sm text-gray-400 mt-1">
            Research jobs, the last measured result, catalog coverage and the experiment journal.
          </p>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-emerald-950/40 border border-emerald-800/40 text-emerald-400 text-xs">
          <ShieldCheck className="w-4 h-4" />
          {data?.safety?.mode ?? 'FAIL_CLOSED'}
          <span className="text-emerald-600/80 font-mono">
            {data?.safety?.live_enabled ? 'live flag set (ignored)' : 'live disabled'}
          </span>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-950/30 border border-red-800/40 text-red-300 text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {Object.entries(jobs).map(([key, job]) => (
          <div
            key={key}
            className={`bg-gray-900 border rounded-2xl p-4 transition-colors ${
              job.running ? 'border-amber-800/50 bg-amber-950/10' : 'border-gray-800'
            }`}
          >
            <div className="flex items-center justify-between mb-2 gap-2">
              <span className="text-xs text-gray-400 uppercase tracking-wide">
                {key.replace('_', ' ')}
              </span>
              <span
                className={`text-[10px] px-2 py-0.5 rounded-full font-mono shrink-0 flex items-center gap-1.5 ${
                  job.running
                    ? 'bg-amber-950/50 text-amber-300 border border-amber-800/40'
                    : 'bg-gray-950 text-gray-500 border border-gray-800'
                }`}
              >
                {job.running && (
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                )}
                {job.running ? 'RUNNING' : 'IDLE'}
              </span>
            </div>
            <p className="text-sm text-gray-200">{job.label}</p>
            {job.running && (
              <p className="text-[11px] font-mono text-amber-300 mt-1">
                {formatElapsed(job.elapsed_seconds ?? null) || 'starting…'} elapsed
              </p>
            )}
          </div>
        ))}
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-4">
        <div className="flex items-center gap-2 flex-wrap">
          <Gauge className="w-5 h-5 text-blue-400" />
          <h3 className="font-semibold text-gray-100">Last measured result</h3>
          {last?.robot && (
            <span className="text-[11px] font-mono px-2 py-0.5 rounded-full border bg-gray-950 text-gray-300 border-gray-800">
              {last.robot} · {last.run_type}
            </span>
          )}
          <span className={`text-[11px] font-mono px-2 py-0.5 rounded-full border ${verdict.badge.className}`}>
            {verdict.badge.label}
          </span>
          {last?.finished_at && (
            <span className="text-[11px] font-mono text-gray-500">
              {formatDateTime(last.finished_at)}
            </span>
          )}
        </div>

        {!last ? (
          <p className="text-sm text-gray-500">
            No research run recorded yet. Start one from the Research &amp; Backtest tab.
          </p>
        ) : (
          <>
            <p
              className={`text-sm font-medium ${
                verdict.beatsBuyHold === true
                  ? 'text-emerald-400'
                  : verdict.beatsBuyHold === false
                    ? 'text-red-400'
                    : 'text-gray-300'
              }`}
            >
              {verdict.headline}
            </p>

            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
              {multi ? (
                <>
                  <MetricCard
                    label="OOS mean"
                    value={multi.mean_oos}
                    tone={meanOos != null && meanOos > 0 ? 'positive' : 'negative'}
                    hint={
                      excess == null
                        ? 'Baseline not measurable'
                        : `Excess over buy&hold ${multi.mean_excess_return}`
                    }
                  />
                  <MetricCard
                    label="Buy & hold"
                    value={multi.buy_and_hold_mean}
                    hint={`Mean of ${multi.fold_count} fold baselines`}
                  />
                  <MetricCard
                    label="Profitable folds"
                    value={multi.profitable}
                    hint={`Worst ${multi.worst_oos} · best ${multi.best_oos}`}
                  />
                  <MetricCard
                    label="Breakeven headroom"
                    value={formatBps(multi.cost_headroom)}
                    tone={(multi.cost_headroom ?? 0) > 0 ? 'positive' : 'negative'}
                    hint={`Paid ${formatBps(multi.mean_paid_cost_rate)} · breakeven ${formatBps(multi.mean_breakeven_cost)}`}
                  />
                </>
              ) : (
                <>
                  <MetricCard
                    label="Ending balance"
                    value={
                      single?.ending_balance != null
                        ? `$${single.ending_balance.toLocaleString()}`
                        : 'n/a'
                    }
                    hint={`${single?.fills ?? 0} fills / ${single?.positions ?? 0} positions`}
                  />
                  <MetricCard
                    label="Buy & hold"
                    value="n/a"
                    hint="Not measured for this run type"
                  />
                  <MetricCard label="Max drawdown" value={single?.max_dd_pct ?? 'n/a'} />
                  <MetricCard
                    label="Sharpe-like"
                    value={single?.sharpe != null ? single.sharpe.toFixed(3) : 'n/a'}
                    hint="Undeflated"
                  />
                </>
              )}
            </div>

            {verdict.concerns.length > 0 && (
              <div className="flex flex-col gap-1">
                {verdict.concerns.map((concern) => (
                  <span key={concern} className="text-[11px] text-amber-400/90">
                    · {concern}
                  </span>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 xl:col-span-2 flex flex-col gap-3">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <FlaskConical className="w-5 h-5 text-blue-400" />
              <h3 className="font-semibold text-gray-100">Recent experiments</h3>
            </div>
            {bestExperiment && (
              <span className="text-[11px] text-gray-400 flex items-center gap-1">
                {bestExperiment.value > 0 ? (
                  <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
                ) : (
                  <TrendingDown className="w-3.5 h-3.5 text-red-400" />
                )}
                best excess vs buy&hold{' '}
                <span
                  className={`font-mono ${bestExperiment.value > 0 ? 'text-emerald-400' : 'text-red-400'}`}
                >
                  {formatPct(bestExperiment.value)}
                </span>
              </span>
            )}
          </div>
          {experimentRows.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-center gap-2">
              <FlaskConical className="w-10 h-10 text-gray-700" />
              <p className="text-sm text-gray-500">No archived experiments yet.</p>
              <p className="text-xs text-gray-600">
                Run a backtest from the{' '}
                <span className="font-mono text-gray-400">Research &amp; Backtest</span> tab
                to populate this table.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[11px] font-mono">
                <thead className="text-gray-500">
                  <tr>
                    <th className="text-left p-1.5">robot</th>
                    <th className="text-left p-1.5">run</th>
                    <th className="text-right p-1.5">OOS</th>
                    <th className="text-right p-1.5">buy&hold</th>
                    <th className="text-right p-1.5">excess</th>
                    <th className="text-right p-1.5">folds</th>
                    <th className="text-left p-1.5">finished</th>
                  </tr>
                </thead>
                <tbody className="text-gray-300">
                  {experimentRows.map((entry) => {
                    const rowExcess = toNumber(entry.multi_window?.mean_excess_return_raw);
                    return (
                      <tr key={entry.history_id} className="border-t border-gray-800/60">
                        <td className="p-1.5 text-blue-300">{entry.robot}</td>
                        <td className="p-1.5 text-gray-500">{entry.run_type}</td>
                        <td className="p-1.5 text-right">{entry.multi_window?.mean_oos ?? 'n/a'}</td>
                        <td className="p-1.5 text-right">
                          {entry.multi_window?.buy_and_hold_mean ?? 'n/a'}
                        </td>
                        <td
                          className={`p-1.5 text-right ${
                            rowExcess == null ? '' : rowExcess > 0 ? 'text-emerald-400' : 'text-red-400'
                          }`}
                        >
                          {entry.multi_window?.mean_excess_return ?? 'n/a'}
                        </td>
                        <td className="p-1.5 text-right">{entry.multi_window?.profitable ?? 'n/a'}</td>
                        <td className="p-1.5 text-gray-500 whitespace-nowrap">
                          {formatDateTime(entry.finished_at)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <BookOpen className="w-5 h-5 text-purple-400" />
            <h3 className="font-semibold text-gray-100">Journal decisions</h3>
          </div>
          {Object.keys(journal).length === 0 ? (
            <p className="text-sm text-gray-500">No journal rows yet.</p>
          ) : (
            <div className="grid grid-cols-2 gap-2 text-sm">
              {Object.entries(journal).map(([decision, count]) => (
                <div key={decision} className="p-2 rounded-lg bg-gray-950 border border-gray-800">
                  <div className="text-[10px] uppercase text-gray-500">{decision}</div>
                  <div className="text-lg font-mono text-gray-100">{count}</div>
                </div>
              ))}
            </div>
          )}
          <p className="text-[11px] text-gray-500">
            Decisions live in research/journal.jsonl; the Experiment Journal tab edits them.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Brain className="w-5 h-5 text-emerald-400" />
            <h3 className="font-semibold text-gray-100">Trained models</h3>
          </div>
          {(data?.models?.length ?? 0) === 0 ? (
            <p className="text-sm text-gray-500">No models in models/</p>
          ) : (
            <div className="space-y-2">
              {data?.models?.map((model) => (
                <div
                  key={model.path}
                  className="flex justify-between text-sm p-2 rounded-lg bg-gray-950 border border-gray-800 font-mono"
                >
                  <span className="text-gray-200">{model.filename}</span>
                  <span className="text-gray-500">{model.size_kb} KB</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Database className="w-5 h-5 text-cyan-400" />
            <h3 className="font-semibold text-gray-100">System</h3>
          </div>
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between gap-3">
              <dt className="text-gray-500">Catalog</dt>
              <dd className="text-gray-300 font-mono truncate max-w-[60%]">
                {data?.catalog_path ?? '—'}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500">Robots wired</dt>
              <dd className="text-gray-300">
                {data?.robots?.wired?.length ?? 0} / {data?.robots?.total ?? 0}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-gray-500">Wired names</dt>
              <dd className="text-gray-300 font-mono text-[11px] text-right">
                {data?.robots?.wired?.join(', ') ?? '—'}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500">Live trading</dt>
              <dd className="text-emerald-400">disabled by design</dd>
            </div>
            {data?.catalog_last_date && (
              <div className="flex justify-between gap-3">
                <dt className="text-gray-500">Data last date</dt>
                <dd className="text-gray-300 font-mono text-xs">{data.catalog_last_date}</dd>
              </div>
            )}
            {data?.catalog_total_bars != null && data.catalog_total_bars > 0 && (
              <div className="flex justify-between gap-3">
                <dt className="text-gray-500">Total bars stored</dt>
                <dd className="text-gray-300 font-mono text-xs">
                  {data.catalog_total_bars.toLocaleString()}
                </dd>
              </div>
            )}
          </dl>
        </div>
      </div>
    </div>
  );
};
