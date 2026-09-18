import React, { useEffect, useRef } from 'react';
import { Terminal } from 'lucide-react';

interface LogPanelProps {
  log: string;
  running: boolean;
  placeholder?: string;
  /** Height class, e.g. 'h-[460px]'. Default: 'h-[400px]' */
  heightClass?: string;
}

/**
 * Syntax-highlighted terminal log panel.
 *
 * Colours are applied per-line by keyword matching — no regex over the whole
 * text so long logs remain cheap. Auto-scrolls to the bottom while running.
 */
const classifyLine = (line: string): string => {
  if (line.includes('out-of-sample (report this)')) return 'text-emerald-400 font-semibold';
  if (line.includes('in-sample (selection only)')) return 'text-amber-400';
  if (/fills=0\b/.test(line)) return 'text-red-400';
  if (line.includes('walk-forward') || line.includes('Walk-forward')) return 'text-blue-400';
  if (line.includes('ERROR') || line.includes('Error') || line.includes('error')) return 'text-red-400';
  if (line.includes('WARNING') || line.includes('warning')) return 'text-amber-300';
  if (line.includes('buy&hold') || line.includes('buy_hold')) return 'text-cyan-400';
  if (line.includes('selected=') || line.includes('tried=')) return 'text-purple-300';
  if (line.includes('tearsheet_saved=')) return 'text-emerald-300';
  if (line.includes('journal_row_appended=')) return 'text-emerald-300';
  if (line.startsWith('Starting ') || line.startsWith('Launching')) return 'text-gray-300';
  if (line.trim() === '') return 'text-transparent select-none';
  return 'text-emerald-400/80';
};

export const LogPanel: React.FC<LogPanelProps> = ({
  log,
  running,
  placeholder = 'Press \u00abRun research\u00bb to start a backtest.',
  heightClass = 'h-[400px]',
}) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll while running; stop scrolling when the run finishes so the
  // user can read the results without being dragged back down.
  useEffect(() => {
    if (running) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [log, running]);

  const lines = log ? log.split('\n') : [];

  return (
    <div className={`bg-[#0a0f18] border border-gray-800 rounded-2xl flex flex-col overflow-hidden ${heightClass}`}>
      <div className="bg-gray-900/80 px-4 py-2.5 border-b border-gray-800 flex justify-between items-center shrink-0">
        <span className="text-xs font-mono text-gray-400 flex items-center gap-2">
          <Terminal className="w-3.5 h-3.5 text-gray-400" />
          Live console output
        </span>
        <span className="text-[11px] font-mono text-gray-500">
          {running ? (
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
              streaming\u2026
            </span>
          ) : (
            'idle'
          )}
        </span>
      </div>

      <div className="p-4 flex-1 overflow-y-auto font-mono text-xs leading-relaxed">
        {lines.length === 0 ? (
          <span className="text-gray-600">{placeholder}</span>
        ) : (
          lines.map((line, index) => (
            <div key={index} className={classifyLine(line)}>
              {line || '\u00a0'}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};
