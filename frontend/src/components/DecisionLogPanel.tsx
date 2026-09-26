import React, { useEffect, useState } from 'react';
import { RefreshCw, Brain, Copy } from 'lucide-react';
import { fetchDecisionLogs, analyzeSessionDecisions } from '../services/api';

interface DecisionLogPanelProps {
  sessionId: string;
}

// decision_trace/1 outcome codes (src/nautilus_lab/domain/decision_trace.py).
const FILTERS: { key: string; label: string; outcomes?: string[] }[] = [
  { key: 'all', label: 'Усі' },
  {
    key: 'trades',
    label: 'Угоди',
    outcomes: ['ENTRY_OPENED', 'REVERSE', 'EXIT', 'FLATTEN_REGIME_CHANGE', 'STOP_LOSS', 'TAKE_PROFIT', 'MANUAL_CLOSE'],
  },
  {
    key: 'blocked',
    label: 'Блоки',
    outcomes: ['ENTRY_BLOCKED_RISK', 'ENTRY_SKIPPED_PAUSED', 'ENTRY_SKIPPED_SIZE', 'AUTO_TRADE_OFF', 'SESSION_INACTIVE'],
  },
  { key: 'quiet', label: 'Без сигналу', outcomes: ['NO_SIGNAL', 'HOLD_NOOP'] },
];

const PRESETS: { key: string; label: string }[] = [
  { key: 'why_no_trades', label: 'Чому мало/багато угод' },
  { key: 'blocking_filter', label: 'Що блокує входи' },
  { key: 'regime_quality', label: 'Якість режимів' },
  { key: 'hypotheses', label: 'Гіпотези для бектесту' },
];

function outcomeClass(outcome?: string): string {
  switch (outcome) {
    case 'ENTRY_OPENED':
    case 'REVERSE':
      return 'text-emerald-400';
    case 'EXIT':
    case 'FLATTEN_REGIME_CHANGE':
    case 'TAKE_PROFIT':
    case 'MANUAL_CLOSE':
      return 'text-sky-400';
    case 'STOP_LOSS':
    case 'ENTRY_BLOCKED_RISK':
    case 'ERROR':
      return 'text-red-400';
    case 'ENTRY_SKIPPED_PAUSED':
    case 'ENTRY_SKIPPED_SIZE':
    case 'AUTO_TRADE_OFF':
    case 'SESSION_INACTIVE':
      return 'text-amber-400';
    default:
      return 'text-gray-500';
  }
}

export const DecisionLogPanel: React.FC<DecisionLogPanelProps> = ({ sessionId }) => {
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('all');
  const [expanded, setExpanded] = useState<number | null>(null);
  const [preset, setPreset] = useState(PRESETS[0]?.key ?? 'why_no_trades');
  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState<{ text: string; note?: string } | null>(null);

  const loadLogs = async () => {
    setLoading(true);
    setError(null);
    try {
      const outcomes = FILTERS.find((f) => f.key === filter)?.outcomes;
      const data = await fetchDecisionLogs(sessionId, 200, outcomes);
      if (data.status === 'ok') {
        setLogs(data.logs);
      } else {
        setError(data.message || 'Failed to load logs');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error fetching decision logs');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLogs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, filter]);

  const handleAnalyze = async () => {
    setAnalyzing(true);
    setError(null);
    try {
      const res = await analyzeSessionDecisions(sessionId, { preset });
      if (res.status === 'ok') {
        setAnalysis({ text: res.analysis, note: res.report ? `Збережено: ${res.report}` : undefined });
      } else if (res.status === 'no_llm') {
        // No model configured: show the real digest, ready to paste into any chat.
        setAnalysis({ text: res.markdown, note: 'LLM_API_KEY не налаштовано — нижче дайджест для будь-якого чату.' });
      } else {
        setError(res.message || res.detail || 'Failed to analyze logs');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error analyzing logs');
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-gray-400">
        <div className="flex items-center gap-2">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`px-2 py-1 rounded border ${
                filter === f.key ? 'border-blue-500 text-blue-300' : 'border-gray-700 text-gray-400'
              }`}
            >
              {f.label}
            </button>
          ))}
          <span className="ml-2">
            Записів: <span className="font-mono text-gray-200">{logs.length}</span>
          </span>
        </div>
        <div className="flex gap-2">
          <button
            onClick={loadLogs}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-900 hover:bg-gray-800 text-gray-300 rounded-lg transition-colors border border-gray-700"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
            Оновити
          </button>
          <select
            value={preset}
            onChange={(e) => setPreset(e.target.value)}
            className="bg-gray-900 border border-gray-700 rounded-lg px-2 text-gray-300"
          >
            {PRESETS.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
          <button
            onClick={handleAnalyze}
            disabled={analyzing}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-900/40 hover:bg-purple-800/60 text-purple-300 rounded-lg transition-colors border border-purple-700/50"
          >
            <Brain className={`w-3 h-3 ${analyzing ? 'animate-pulse' : ''}`} />
            {analyzing ? 'Аналіз…' : 'Аналіз LLM'}
          </button>
        </div>
      </div>

      {analysis && (
        <div className="p-4 bg-purple-950/20 border border-purple-900/40 rounded-lg text-xs text-purple-200/90 whitespace-pre-wrap">
          <div className="font-bold mb-2 flex items-center gap-2 text-purple-300">
            <Brain className="w-4 h-4" /> Аналіз рішень
            <button
              onClick={() => navigator.clipboard?.writeText(analysis.text)}
              className="ml-auto flex items-center gap-1 text-purple-400 hover:text-purple-300"
            >
              <Copy className="w-3 h-3" /> Копіювати
            </button>
            <button onClick={() => setAnalysis(null)} className="text-purple-400 hover:text-purple-300">
              Закрити
            </button>
          </div>
          {analysis.note && <div className="mb-2 text-purple-400/80">{analysis.note}</div>}
          {analysis.text}
        </div>
      )}

      {error && (
        <div className="p-3 bg-red-950/30 border border-red-900/50 rounded-lg text-xs text-red-400">{error}</div>
      )}

      {logs.length > 0 ? (
        <div className="overflow-x-auto max-h-[32rem]">
          <table className="w-full text-left text-[11px] font-mono">
            <thead className="text-gray-500 border-b border-gray-800 sticky top-0 bg-[#0d131f]">
              <tr>
                <th className="pb-2 font-medium">Time (UTC)</th>
                <th className="pb-2 font-medium">Close</th>
                <th className="pb-2 font-medium">Regime</th>
                <th className="pb-2 font-medium">Outcome</th>
                <th className="pb-2 font-medium w-1/2">Міркування</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/40 text-gray-300">
              {logs.map((log, idx) => (
                <tr
                  key={idx}
                  className="hover:bg-gray-800/20 cursor-pointer align-top"
                  onClick={() => setExpanded(expanded === idx ? null : idx)}
                >
                  <td className="py-2 pr-2 text-gray-400 whitespace-nowrap">
                    {log.ts ? new Date(log.ts).toLocaleString('en-GB', { timeZone: 'UTC' }) : '—'}
                    {log.kind === 'intrabar' && <div className="text-[9px] text-gray-500">intrabar</div>}
                  </td>
                  <td className="py-2 pr-2 text-blue-400">
                    {log.close ? `$${parseFloat(log.close).toFixed(2)}` : '—'}
                  </td>
                  <td className="py-2 pr-2">{log.regime || '—'}</td>
                  <td className={`py-2 pr-2 font-bold ${outcomeClass(log.outcome)}`}>
                    {log.outcome || (log.signal ? log.signal.toUpperCase() : '—')}
                    {log.blocked_by && <div className="text-[9px] font-normal text-gray-500">{log.blocked_by}</div>}
                  </td>
                  <td className="py-2">
                    <div className="text-gray-300 text-[10px] break-words font-sans">
                      {log.narrative || log.signal_reason || '—'}
                    </div>
                    {expanded === idx && (
                      <div className="mt-2 space-y-1 text-[10px] text-gray-400">
                        {(log.steps || []).map((s: any, i: number) => (
                          <div key={i}>
                            <span className="text-gray-500">{s.stage}</span>{' '}
                            <span className="text-gray-300">{s.component}</span>{' '}
                            <span className="text-purple-300">{s.verdict}</span>
                            {s.result && <span className="text-amber-200/80"> → {s.result}</span>}
                            {s.values && (
                              <span className="opacity-80">
                                {' '}
                                {Object.entries(s.values)
                                  .map(([k, v]) => `${k}=${v}`)
                                  .join(', ')}
                              </span>
                            )}
                          </div>
                        ))}
                        {!log.steps?.length && log.indicators && (
                          <div className="opacity-80">
                            {Object.entries(log.indicators)
                              .map(([k, v]) => `${k}: ${v}`)
                              .join(', ')}
                          </div>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        !loading &&
        !error && (
          <div className="py-8 text-center text-xs text-gray-500">
            Записів немає. Перевірте, що робот працює і DECISION_LOG_ENABLED=true.
          </div>
        )
      )}
    </div>
  );
};
