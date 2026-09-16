import React, { useState } from 'react';
import { Sparkles, Terminal } from 'lucide-react';
import { runPropose } from '../services/api';
import type { ProposeResponse } from '../services/api';

export const ProposeAlpha: React.FC = () => {
  const [count, setCount] = useState(5);
  const [dryRun, setDryRun] = useState(true);
  const [journal, setJournal] = useState(false);
  const [running, setRunning] = useState(false);
  const [output, setOutput] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleRun = async () => {
    setRunning(true);
    setError(null);
    try {
      const result: ProposeResponse = await runPropose({ count, dry_run: dryRun, journal });
      if (result.status === 'dry_run') {
        setOutput(String(result.prompt ?? result.message ?? JSON.stringify(result, null, 2)));
      } else {
        setOutput(
          [result.summary, result.artifact_path ? `artifact=${result.artifact_path}` : '']
            .filter(Boolean)
            .join('\n\n'),
        );
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-4">
      <div>
        <h3 className="font-semibold text-gray-100 flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-amber-400" />
          Alpha Proposer (offline LLM)
        </h3>
        <p className="text-xs text-gray-500 mt-1">
          Calls the model once to draft hypotheses. Never runs on the backtest hot path.
        </p>
      </div>

      <div className="flex flex-wrap gap-4 items-end">
        <div>
          <label className="text-xs text-gray-400 block mb-1">Count</label>
          <input
            type="number"
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
            className="w-20 bg-gray-950 border border-gray-800 rounded-lg px-2 py-1.5 text-sm font-mono"
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-300">
          <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
          Dry run (no API call)
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-300">
          <input type="checkbox" checked={journal} onChange={(e) => setJournal(e.target.checked)} />
          Write journal entry
        </label>
        <button
          onClick={handleRun}
          disabled={running}
          className="px-4 py-2 bg-amber-700 hover:bg-amber-600 disabled:opacity-50 rounded-xl text-sm text-white"
        >
          {running ? 'Running…' : dryRun ? 'Preview prompt' : 'Run propose'}
        </button>
      </div>

      {error && (
        <div className="text-sm text-red-400 border border-red-900/40 bg-red-950/20 rounded-xl p-3">
          {error}
        </div>
      )}

      {output && (
        <div>
          <div className="flex items-center gap-2 mb-2 text-xs text-gray-500">
            <Terminal className="w-4 h-4" />
            Output
          </div>
          <pre className="text-xs font-mono bg-gray-950 border border-gray-800 rounded-xl p-4 max-h-64 overflow-auto whitespace-pre-wrap text-gray-300">
            {output}
          </pre>
        </div>
      )}
    </div>
  );
};
