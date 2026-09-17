import React, { useEffect, useState } from 'react';
import { AlertTriangle, BookOpen, FileText, RefreshCw, ShieldQuestion } from 'lucide-react';
import { ProposeAlpha } from './ProposeAlpha';
import { fetchJournal, patchJournalDecision } from '../services/api';
import type { JournalEntry } from '../services/api';
import { formatDateTime, formatPct, toNumber } from '../lib/format';

const COLUMNS = ['pending', 'accepted', 'rejected', 'rerun'] as const;

const DECISION_STYLE: Record<string, string> = {
  pending: 'text-amber-300 border-amber-800/50 bg-amber-950/40',
  accepted: 'text-emerald-300 border-emerald-800/50 bg-emerald-950/40',
  rejected: 'text-red-300 border-red-800/50 bg-red-950/40',
  rerun: 'text-blue-300 border-blue-800/50 bg-blue-950/40',
};

/**
 * The journal exists so a run is not repeated by accident, and so a decision is recorded
 * with the gates it was made under. The row therefore shows `gates`, `reason`, `fills` and
 * the artifact: a card that only says "OOS better than buy&hold" invites accepting a
 * result whose conditions nobody can check afterwards.
 */
export const JournalKanban: React.FC = () => {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    setLoading(true);
    fetchJournal()
      .then((data) => {
        setEntries(data.entries);
        setError(null);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Failed to load the journal'),
      )
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    refresh();
  }, []);

  const moveEntry = async (index: number, decision: string) => {
    try {
      await patchJournalDecision(index, decision);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update the decision');
    }
  };

  const byDecision = (decision: string) =>
    entries.filter((entry) => (entry.decision ?? 'pending') === decision);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-xl font-bold text-gray-100 flex items-center gap-2">
            <BookOpen className="w-6 h-6 text-purple-400" />
            Experiment Journal
          </h2>
          <p className="text-sm text-gray-400 mt-1">
            Review what was tested and under which gates, then record accept / reject / rerun.
            Rows are append-only in <span className="font-mono">research/journal.jsonl</span>; only
            the decision column is editable.
          </p>
        </div>
        <button
          type="button"
          onClick={refresh}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-2 rounded-xl bg-gray-800 hover:bg-gray-700 text-sm text-gray-300"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="p-3 rounded-xl bg-red-950/30 border border-red-800/40 text-red-300 text-xs flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      <ProposeAlpha />

      {entries.length === 0 && !loading && !error && (
        <div className="p-8 bg-gray-900 border border-gray-800 rounded-2xl text-center text-gray-500 text-sm">
          No journal rows yet. Enable &quot;Append a row to research/journal.md&quot; on a research
          run, or use the proposal panel above.
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {COLUMNS.map((column) => (
          <div
            key={column}
            className="bg-gray-900/60 border border-gray-800 rounded-2xl p-4 min-h-[320px]"
          >
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-300">
                {column}
              </h3>
              <span className="text-xs font-mono text-gray-500">{byDecision(column).length}</span>
            </div>
            <div className="space-y-3">
              {byDecision(column).map((entry) => {
                const oos = toNumber(entry.oos_return ?? null);
                const buyHold = toNumber(entry.buy_and_hold_return ?? null);
                const beats = oos != null && buyHold != null ? oos > buyHold : null;
                return (
                  <div
                    key={`${entry.index}-${entry.created_at}`}
                    className="p-3 rounded-xl bg-gray-950 border border-gray-800 text-sm space-y-2"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="font-mono text-blue-300 text-xs">{entry.subject}</span>
                      <span
                        className={`text-[9px] px-1.5 py-0.5 rounded border font-mono shrink-0 ${
                          DECISION_STYLE[entry.decision] ?? DECISION_STYLE.pending
                        }`}
                      >
                        {entry.decision}
                      </span>
                    </div>

                    <div className="text-[10px] text-gray-500 font-mono">
                      {entry.source} · {formatDateTime(entry.created_at)}
                    </div>

                    {entry.gates && (
                      <div className="text-[10px] text-gray-400 font-mono bg-gray-900/70 border border-gray-800 rounded-lg px-2 py-1">
                        gates: {entry.gates}
                      </div>
                    )}

                    {entry.oos_return != null && (
                      <div className="text-xs">
                        <span className="text-gray-500">OOS </span>
                        <span className={oos != null && oos > 0 ? 'text-emerald-400' : 'text-red-400'}>
                          {formatPct(oos)}
                        </span>
                        {entry.buy_and_hold_return != null && (
                          <>
                            <span className="text-gray-500"> · buy&amp;hold </span>
                            <span className="text-gray-300">{formatPct(buyHold)}</span>
                            <span
                              className={`ml-1 text-[10px] ${
                                beats === true ? 'text-emerald-400' : beats === false ? 'text-red-400' : ''
                              }`}
                            >
                              {beats === true ? '(beat it)' : beats === false ? '(behind it)' : ''}
                            </span>
                          </>
                        )}
                      </div>
                    )}

                    {entry.oos_return == null && (
                      <div className="text-[10px] text-amber-400/80 flex items-center gap-1">
                        <ShieldQuestion className="w-3 h-3" />
                        no out-of-sample number on this row
                      </div>
                    )}

                    {entry.fills != null && (
                      <div className="text-[10px] text-gray-500 font-mono">fills: {entry.fills}</div>
                    )}

                    {entry.reason && (
                      <div className="text-[10px] text-gray-400 leading-snug">{entry.reason}</div>
                    )}

                    {entry.artifact && (
                      <div className="text-[10px] text-gray-600 font-mono truncate flex items-center gap-1">
                        <FileText className="w-3 h-3 shrink-0" />
                        <span className="truncate" title={entry.artifact}>
                          {entry.artifact}
                        </span>
                      </div>
                    )}

                    <div className="flex flex-wrap gap-1 pt-1">
                      {COLUMNS.filter((decision) => decision !== column).map((target) => (
                        <button
                          type="button"
                          key={target}
                          onClick={() => moveEntry(entry.index ?? -1, target)}
                          className="text-[10px] px-2 py-0.5 rounded-md bg-gray-800 hover:bg-gray-700 text-gray-300"
                        >
                          → {target}
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
