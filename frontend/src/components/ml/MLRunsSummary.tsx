import React from 'react';
import { Sparkles } from 'lucide-react';
import type { MlTrainSummary } from '../../services/api';
import { formatDateTime } from '../../lib/format';

interface Props {
  summary: MlTrainSummary;
}

export const MLRunsSummary: React.FC<Props> = ({ summary }) => {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-sm text-gray-100 flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-emerald-400" />
          Latest Training Summary
        </h3>
        {summary.created_at && (
          <span className="text-[11px] text-gray-500 font-mono">
            {formatDateTime(summary.created_at)}
          </span>
        )}
      </div>

      {summary.runs && summary.runs.length > 0 ? (
        <div className="overflow-x-auto border border-gray-800 rounded-xl">
          <table className="w-full text-left text-xs font-mono">
            <thead className="bg-gray-950 text-gray-400 border-b border-gray-800">
              <tr>
                <th className="p-2.5">Model</th>
                <th className="p-2.5">Pair</th>
                <th className="p-2.5">Status</th>
                <th className="p-2.5">Purged CV Acc</th>
                <th className="p-2.5">Majority</th>
                <th className="p-2.5">Rows</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/60">
              {summary.runs.map((r, idx) => (
                <tr key={idx} className="hover:bg-gray-800/30 transition-colors">
                  <td className="p-2.5 font-semibold text-gray-200">{r.model_type}</td>
                  <td className="p-2.5 text-gray-300">{r.instrument}</td>
                  <td className="p-2.5">
                    {r.is_error ? (
                      <span className="px-2 py-0.5 rounded bg-red-950/60 text-red-400 text-[10px] border border-red-800/40">
                        failed
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded bg-emerald-950/60 text-emerald-300 text-[10px] border border-emerald-800/40">
                        saved
                      </span>
                    )}
                  </td>
                  <td className="p-2.5 text-emerald-400 font-bold">{r.accuracy ?? '—'}</td>
                  <td className="p-2.5 text-gray-400">{r.majority_rate ?? '—'}</td>
                  <td className="p-2.5 text-gray-400">{r.rows ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs font-mono">
          <div className="bg-gray-950 p-2.5 rounded-xl border border-gray-800">
            <div className="text-[10px] text-gray-500 uppercase">CV Accuracy</div>
            <div className="text-emerald-400 font-bold text-sm">
              {summary.accuracy ?? 'n/a'}
            </div>
          </div>
          <div className="bg-gray-950 p-2.5 rounded-xl border border-gray-800">
            <div className="text-[10px] text-gray-500 uppercase">Majority Rate</div>
            <div className="text-gray-200 font-bold text-sm">
              {summary.majority_rate ?? 'n/a'}
            </div>
          </div>
          <div className="bg-gray-950 p-2.5 rounded-xl border border-gray-800">
            <div className="text-[10px] text-gray-500 uppercase">Beats Majority</div>
            <div className="text-gray-200 font-bold text-sm">
              {summary.beats_majority ?? 'n/a'}
            </div>
          </div>
          <div className="bg-gray-950 p-2.5 rounded-xl border border-gray-800">
            <div className="text-[10px] text-gray-500 uppercase">Total Bars/Rows</div>
            <div className="text-gray-200 font-bold text-sm">
              {summary.rows?.toLocaleString() ?? 'n/a'}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
