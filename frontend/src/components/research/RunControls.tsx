import React, { useState } from 'react';
import { AlertTriangle, ClipboardCopy, Play, RefreshCw, RotateCcw, Square } from 'lucide-react';

import { formatDateTime } from '../../lib/format';
import type { PreflightIssue } from '../../lib/research';
import type { StrategySpec } from '../../services/api';

interface RunControlsProps {
  issues: PreflightIssue[];
  blocked: boolean;
  running: boolean;
  launchedAtIso: string | null;
  onRun: () => void;
  onCancel: () => void;
  onReset: () => void;
  /** The equivalent `lab research` command, built when the button is pressed. */
  cliText: () => string;
  strategy: StrategySpec | undefined;
}

/** Preflight findings, the run/cancel/reset/copy buttons and the selected robot's spec. */
export const RunControls: React.FC<RunControlsProps> = ({
  issues,
  blocked,
  running,
  launchedAtIso,
  onRun,
  onCancel,
  onReset,
  cliText,
  strategy,
}) => {
  const [copiedCli, setCopiedCli] = useState(false);
  const errors = issues.filter((issue) => issue.level === 'error');
  const warnings = issues.filter((issue) => issue.level === 'warning');
  const selectedStrategyInfo = strategy;
  return (
    <>
      {(errors.length > 0 || warnings.length > 0) && (
        <div className="flex flex-col gap-1.5 border-t border-gray-800/80 pt-4">
          {errors.map((issue) => (
            <div key={issue.message} className="flex items-start gap-2 text-[11px] text-red-400">
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span>{issue.message}</span>
            </div>
          ))}
          {warnings.map((issue) => (
            <div key={issue.message} className="flex items-start gap-2 text-[11px] text-amber-400/90">
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span>{issue.message}</span>
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-col md:flex-row gap-3 md:items-center flex-wrap">
        <button
          type="button"
          onClick={onRun}
          disabled={running || blocked}
          title={blocked ? 'Fix the blocking issues above first' : 'Run research (⌘/Ctrl + Enter)'}
          className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-800 disabled:text-gray-500 text-white font-medium rounded-xl transition-colors flex items-center justify-center gap-2"
        >
          {running ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
          {running ? 'Simulating…' : blocked ? 'Run blocked' : 'Run research'}
          {!running && !blocked && (
            <kbd className="ml-1 text-[10px] font-mono bg-blue-800/70 px-1.5 py-0.5 rounded border border-blue-700/60 leading-tight">
              ⌘↵
            </kbd>
          )}
        </button>

        {running && (
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2.5 bg-red-950/60 hover:bg-red-900/60 text-red-300 border border-red-800/60 text-sm font-medium rounded-xl transition-colors flex items-center justify-center gap-2"
          >
            <Square className="w-3.5 h-3.5" />
            Cancel
          </button>
        )}

        <button
          type="button"
          onClick={onReset}
          className="px-3 py-2.5 text-xs text-gray-400 hover:text-gray-200 border border-gray-800 rounded-xl flex items-center gap-1.5"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          Reset form
        </button>

        {/* Copy CLI command — lets the user reproduce the run from the terminal */}
        <button
          type="button"
          onClick={() => {
            navigator.clipboard.writeText(cliText()).then(() => {
              setCopiedCli(true);
              setTimeout(() => setCopiedCli(false), 2000);
            });
          }}
          className="px-3 py-2.5 text-xs text-gray-400 hover:text-gray-200 border border-gray-800 rounded-xl flex items-center gap-1.5 transition-colors"
          title="Copy equivalent CLI command to clipboard"
        >
          <ClipboardCopy className="w-3.5 h-3.5" />
          {copiedCli ? 'Copied!' : 'Copy CLI'}
        </button>

        {running && launchedAtIso && (
          <span className="text-[11px] text-gray-500 font-mono">
            started {formatDateTime(launchedAtIso)}
          </span>
        )}
      </div>

      {selectedStrategyInfo && (
        <div className="text-xs bg-gray-950/60 p-3 rounded-xl border border-gray-800/80 flex flex-col md:flex-row md:items-center justify-between gap-2 text-gray-400">
          <div>
            <span className="text-gray-300 font-semibold">{selectedStrategyInfo.name}</span>:{' '}
            {selectedStrategyInfo.summary}
            <span className="block text-[10px] text-gray-600 font-mono mt-1">
              min bars {selectedStrategyInfo.minimum_bars} · grid{' '}
              {selectedStrategyInfo.grid_source ?? 'n/a'} · status {selectedStrategyInfo.status}
            </span>
          </div>
          <span
            className={`px-2 py-0.5 rounded text-[11px] font-mono self-start ${
              selectedStrategyInfo.wired_in_backtest
                ? 'bg-emerald-950/80 text-emerald-400 border border-emerald-800/50'
                : 'bg-red-950/80 text-red-400 border border-red-800/50'
            }`}
          >
            {selectedStrategyInfo.wired_in_backtest ? 'Wired to engine' : 'Fail-closed block'}
          </span>
        </div>
      )}
    </>
  );
};
