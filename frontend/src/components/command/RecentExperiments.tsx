import React from 'react';
import { FlaskConical, TrendingDown, TrendingUp } from 'lucide-react';

import { formatDateTime, formatPct, toNumber } from '../../lib/format';
import type { HistoryEntry } from '../../services/api';

/** The archived runs, newest first, with the best excess return over buy & hold. */
export const RecentExperiments: React.FC<{ experimentRows: HistoryEntry[] }> = ({ experimentRows }) => {
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
  );
};
