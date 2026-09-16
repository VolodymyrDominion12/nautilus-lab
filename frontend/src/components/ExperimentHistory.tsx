import React, { useEffect, useState } from 'react';
import { History } from 'lucide-react';
import { fetchResearchHistory } from '../services/api';
import type { HistoryEntry } from '../services/api';

interface ExperimentHistoryProps {
  onRerun?: (entry: HistoryEntry) => void;
}

export const ExperimentHistory: React.FC<ExperimentHistoryProps> = ({ onRerun }) => {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const data = await fetchResearchHistory(12);
      setEntries(data.history);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <History className="w-4 h-4 text-purple-400" />
          <h3 className="text-sm font-bold text-gray-100">Experiment History</h3>
        </div>
        <button
          type="button"
          onClick={load}
          className="text-xs text-blue-400 hover:text-blue-300"
        >
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {entries.length === 0 ? (
        <p className="text-xs text-gray-500">No archived runs yet. Finish a research job to populate history.</p>
      ) : (
        <div className="flex flex-col gap-2 max-h-56 overflow-y-auto">
          {entries.map((entry) => (
            <div
              key={entry.history_id}
              className="p-3 rounded-xl bg-gray-950/70 border border-gray-800/80 flex flex-col gap-1"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-mono text-gray-200">
                  {entry.robot} · {entry.run_type}
                </span>
                <span className="text-[10px] text-gray-500">{entry.finished_at?.slice(0, 19)}</span>
              </div>
              <div className="text-[11px] text-gray-400">
                {entry.multi_window?.mean_oos && (
                  <span>OOS mean {entry.multi_window.mean_oos}</span>
                )}
                {entry.single_backtest?.ending_balance != null && !entry.multi_window && (
                  <span>Ending ${entry.single_backtest.ending_balance.toLocaleString()}</span>
                )}
                {entry.report_label && !entry.multi_window && !entry.single_backtest && (
                  <span>{entry.report_label}</span>
                )}
              </div>
              {onRerun && entry.config && (
                <button
                  type="button"
                  onClick={() => onRerun(entry)}
                  className="self-start mt-1 text-[11px] text-blue-400 hover:text-blue-300"
                >
                  Load config
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
