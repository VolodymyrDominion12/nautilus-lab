import React, { useEffect, useState } from 'react';
import { RefreshCw, Brain } from 'lucide-react';
import { fetchDecisionLogs, analyzeDecisions } from '../services/api';

interface DecisionLogPanelProps {
  sessionId: string;
}

export const DecisionLogPanel: React.FC<DecisionLogPanelProps> = ({ sessionId }) => {
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<string | null>(null);

  const loadLogs = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchDecisionLogs(sessionId);
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
  }, [sessionId]);

  const handleAnalyze = async () => {
    if (logs.length === 0) return;
    setAnalyzing(true);
    setError(null);
    try {
      const res = await analyzeDecisions(logs, "Can you provide insights on these recent decisions?");
      if (res.status === 'ok') {
        setAnalysisResult(res.analysis);
      } else {
        setError(res.message || 'Failed to analyze logs');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error analyzing logs');
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between text-xs text-gray-400">
        <div>
          Decision calculations recorded at bar closes. Logs: <span className="font-mono text-gray-200">{logs.length}</span>
        </div>
        <div className="flex gap-2">
          <button
            onClick={loadLogs}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-900 hover:bg-gray-800 text-gray-300 rounded-lg transition-colors border border-gray-700"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <button
            onClick={handleAnalyze}
            disabled={analyzing || logs.length === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-900/40 hover:bg-purple-800/60 text-purple-300 rounded-lg transition-colors border border-purple-700/50"
          >
            <Brain className={`w-3 h-3 ${analyzing ? 'animate-pulse' : ''}`} />
            {analyzing ? 'Analyzing...' : 'Analyze with LLM'}
          </button>
        </div>
      </div>
      
      {analysisResult && (
        <div className="p-4 bg-purple-950/20 border border-purple-900/40 rounded-lg text-xs text-purple-200/90 whitespace-pre-wrap">
          <div className="font-bold mb-2 flex items-center gap-2 text-purple-300">
            <Brain className="w-4 h-4" /> LLM Insights
            <button 
              onClick={() => setAnalysisResult(null)}
              className="ml-auto text-purple-400 hover:text-purple-300"
            >
              Close
            </button>
          </div>
          {analysisResult}
        </div>
      )}
      
      {error && (
        <div className="p-3 bg-red-950/30 border border-red-900/50 rounded-lg text-xs text-red-400">
          {error}
        </div>
      )}

      {logs.length > 0 ? (
        <div className="overflow-x-auto max-h-96">
          <table className="w-full text-left text-[11px] font-mono">
            <thead className="text-gray-500 border-b border-gray-800 sticky top-0 bg-[#0d131f]">
              <tr>
                <th className="pb-2 font-medium">Time (UTC)</th>
                <th className="pb-2 font-medium">Close</th>
                <th className="pb-2 font-medium">Regime</th>
                <th className="pb-2 font-medium">Signal</th>
                <th className="pb-2 font-medium w-1/2">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/40 text-gray-300">
              {logs.map((log, idx) => (
                <tr key={idx} className="hover:bg-gray-800/20">
                  <td className="py-2 pr-2 text-gray-400 whitespace-nowrap">
                    {log.ts ? new Date(log.ts).toLocaleString('en-GB', { timeZone: 'UTC' }) : '—'}
                  </td>
                  <td className="py-2 pr-2 text-blue-400">
                    {log.close ? `$${parseFloat(log.close).toFixed(2)}` : '—'}
                  </td>
                  <td className="py-2 pr-2">
                    {log.regime || '—'}
                  </td>
                  <td className={`py-2 pr-2 font-bold ${
                    // The API writes SignalSide values ("buy"/"sell"), not LONG/SHORT:
                    // testing for the latter left every signal grey.
                    log.signal === 'buy' ? 'text-emerald-400' :
                    log.signal === 'sell' ? 'text-red-400' : 'text-gray-500'
                  }`}>
                    {log.signal || 'NONE'}
                  </td>
                  <td className="py-2">
                    <div className="text-gray-400 text-[10px] break-words">
                      {log.signal_reason && <div className="text-amber-200/80 mb-1">{log.signal_reason}</div>}
                      {log.indicators && Object.keys(log.indicators).length > 0 && (
                        <div className="opacity-80">
                          {Object.entries(log.indicators).map(([k, v]) => `${k}: ${v}`).join(', ')}
                        </div>
                      )}
                      {log.states && Object.keys(log.states).length > 0 && (
                        <div className="text-purple-300/60 mt-0.5">
                          {Object.entries(log.states).map(([k, v]) => `${k}: ${v}`).join(', ')}
                        </div>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        !loading && !error && (
          <div className="py-8 text-center text-xs text-gray-500">
            No decision logs found. Make sure the robot has run and decision logging is enabled.
          </div>
        )
      )}
    </div>
  );
};
