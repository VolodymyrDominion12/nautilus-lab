import React, { useState } from 'react';
import { Check, Copy, GitCommit, Terminal } from 'lucide-react';
import type { LeaderboardEntry } from '../../services/api';

interface LeaderboardRowDetailsProps {
  entry: LeaderboardEntry;
}

export const LeaderboardRowDetails: React.FC<LeaderboardRowDetailsProps> = ({ entry }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(entry.reproduce_command);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const params = Object.entries(entry.strategy_params || {});
  const runArgs = Object.entries(entry.run_args || {});
  const prov = entry.provenance;

  return (
    <div className="bg-[#0b101b] border-t border-gray-800/80 p-5 flex flex-col gap-5 text-xs">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Strategy Parameters */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-gray-300 font-semibold">
            <span>Параметри стратегії</span>
            <span className="text-[10px] text-gray-500 font-mono">({params.length})</span>
          </div>
          {params.length === 0 ? (
            <p className="text-gray-500 italic">Базові налаштування (за замовчуванням)</p>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {params.map(([key, val]) => (
                <div
                  key={key}
                  className="bg-gray-900/90 border border-gray-800 rounded-lg px-2.5 py-1.5 flex flex-col gap-0.5"
                >
                  <span className="text-[10px] text-gray-400 font-mono truncate" title={key}>
                    {key}
                  </span>
                  <span className="text-xs font-mono font-bold text-gray-100">
                    {String(val)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Provenance & Environment */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-gray-300 font-semibold">
            <GitCommit className="w-3.5 h-3.5 text-purple-400" />
            <span>Аудит походження (Provenance)</span>
          </div>
          <div className="bg-gray-900/90 border border-gray-800 rounded-lg p-3 flex flex-col gap-1.5 font-mono text-[11px]">
            <div className="flex justify-between items-center text-gray-400">
              <span>Git commit:</span>
              <span className="text-gray-200">
                {prov?.code_revision ? prov.code_revision.slice(0, 8) : 'n/a'}
                {prov?.code_dirty ? ' (dirty)' : ''}
              </span>
            </div>
            <div className="flex justify-between items-center text-gray-400">
              <span>Рушій / Python:</span>
              <span className="text-gray-200">
                Nautilus {prov?.nautilus_version ?? 'n/a'} · Py {prov?.python_version ?? 'n/a'}
              </span>
            </div>
            <div className="flex justify-between items-center text-gray-400">
              <span>Fingerprint каталогу:</span>
              <span className="text-gray-200 truncate max-w-[180px]" title={prov?.catalog_fingerprint}>
                {prov?.catalog_fingerprint ? prov.catalog_fingerprint.slice(0, 12) + '…' : 'n/a'}
              </span>
            </div>
            {entry.notes && (
              <div className="pt-1 mt-1 border-t border-gray-800 text-[10px] text-gray-400">
                Примітка: <span className="text-gray-300">{entry.notes}</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Reproduction Command */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-gray-300 font-semibold">
            <Terminal className="w-3.5 h-3.5 text-amber-400" />
            <span>Команда для 100% точного відтворення бектесту</span>
          </div>
          <button
            type="button"
            onClick={handleCopy}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-gray-800 hover:bg-gray-700 text-gray-200 text-xs transition-colors"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? 'Скопійовано!' : 'Копіювати CLI'}</span>
          </button>
        </div>
        <pre className="p-3 bg-gray-950 border border-gray-800 rounded-lg font-mono text-[11px] text-amber-300/90 whitespace-pre-wrap break-all select-all">
          {entry.reproduce_command}
        </pre>
      </div>
    </div>
  );
};
