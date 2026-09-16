import React, { useEffect, useState } from 'react';
import { BookOpen, RefreshCw } from 'lucide-react';
import { ProposeAlpha } from './ProposeAlpha';
import { fetchJournal, patchJournalDecision } from '../services/api';
import type { JournalEntry } from '../services/api';

const COLUMNS = ['pending', 'accepted', 'rejected', 'rerun'] as const;

export const JournalKanban: React.FC = () => {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = () => {
    setLoading(true);
    fetchJournal()
      .then((data) => setEntries(data.entries))
      .catch(console.error)
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
      console.error(err);
    }
  };

  const byDecision = (decision: string) =>
    entries.filter((entry) => (entry.decision ?? 'pending') === decision);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-100 flex items-center gap-2">
            <BookOpen className="w-6 h-6 text-purple-400" />
            Experiment Journal
          </h2>
          <p className="text-sm text-gray-400 mt-1">
            Review walk-forward outcomes and record accept / reject / rerun decisions.
          </p>
        </div>
        <button
          onClick={refresh}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-2 rounded-xl bg-gray-800 hover:bg-gray-700 text-sm text-gray-300"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      <ProposeAlpha />

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {COLUMNS.map((column) => (
          <div key={column} className="bg-gray-900/60 border border-gray-800 rounded-2xl p-4 min-h-[320px]">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-300">{column}</h3>
              <span className="text-xs font-mono text-gray-500">{byDecision(column).length}</span>
            </div>
            <div className="space-y-3">
              {byDecision(column).map((entry) => (
                <div
                  key={`${entry.index}-${entry.created_at}`}
                  className="p-3 rounded-xl bg-gray-950 border border-gray-800 text-sm space-y-2"
                >
                  <div className="font-mono text-blue-300 text-xs">{entry.subject}</div>
                  <div className="text-gray-400 text-xs">{entry.source}</div>
                  {entry.oos_return != null && (
                    <div className="text-xs text-gray-300">
                      OOS: {entry.oos_return} · B&H: {entry.buy_and_hold_return ?? 'n/a'}
                    </div>
                  )}
                  <div className="flex flex-wrap gap-1 pt-1">
                    {COLUMNS.filter((d) => d !== column).map((target) => (
                      <button
                        key={target}
                        onClick={() => moveEntry(entry.index!, target)}
                        className="text-[10px] px-2 py-0.5 rounded-md bg-gray-800 hover:bg-gray-700 text-gray-300"
                      >
                        → {target}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
