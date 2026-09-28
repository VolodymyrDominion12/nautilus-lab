import React, { useState } from 'react';
import { X, ListOrdered, ScrollText } from 'lucide-react';
import { DecisionLogPanel } from './DecisionLogPanel';
import { TradesTable } from './trades/TradesTable';
import { useSessionTrades } from './trades/useSessionTrades';

import type { HistoryEntry } from '../services/api';

interface BacktestDetailsModalProps {
  entry: HistoryEntry;
  onClose: () => void;
}

/**
 * What one research run actually did, bar by bar and trade by trade.
 *
 * Two views of the same decision log: the **trade list** (reconstructed entry/exit pairs,
 * each linking to its own page) and the **raw decisions** (the panel that was here before,
 * for reading the bars a trade did *not* happen on). Both read the run's log by
 * `single_backtest.session_id`, the same key a live paper session uses — which is why the
 * trade page behind a link is identical for a backtest and for paper trading.
 */
export const BacktestDetailsModal: React.FC<BacktestDetailsModalProps> = ({ entry, onClose }) => {
  const sessionId = entry.single_backtest?.session_id || '';
  const catalogPath = entry.config?.catalog_path || undefined;
  const barInterval = entry.config?.bar_interval || undefined;
  const instrumentId = entry.config?.instrument_id || undefined;
  const [view, setView] = useState<'trades' | 'decisions'>('trades');
  const { data, loading, error, reload } = useSessionTrades(sessionId || null);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="bg-gray-950 border border-gray-800 rounded-2xl w-full max-w-7xl h-[85vh] flex flex-col shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between p-4 border-b border-gray-800/80 bg-gray-900/50">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-bold text-gray-100">Backtest Details</h2>
            <span className="text-xs font-mono text-gray-500 bg-gray-800/40 px-2 py-1 rounded">
              {sessionId}
            </span>
            <div className="flex items-center gap-1 bg-[#0d131f] border border-gray-800 p-1 rounded-xl">
              <button
                type="button"
                onClick={() => setView('trades')}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-all ${
                  view === 'trades'
                    ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                <ListOrdered className="w-3 h-3" /> Угоди ({data?.trades.length ?? 0})
              </button>
              <button
                type="button"
                onClick={() => setView('decisions')}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-all ${
                  view === 'decisions'
                    ? 'bg-purple-600/20 text-purple-300 border border-purple-500/30'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                <ScrollText className="w-3 h-3" /> Рішення по барах
              </button>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          {view === 'trades' ? (
            <TradesTable
              trades={data?.trades ?? []}
              loading={loading}
              error={error}
              onReload={reload}
              truncated={data?.truncated}
              recordsScanned={data?.records}
              windows={data?.windows}
              linkContext={{
                session: sessionId,
                instrument: instrumentId,
                interval: barInterval,
                catalog: catalogPath,
                title: entry.robot ?? undefined,
                origin: 'backtest',
              }}
              emptyHint="У цьому прогоні немає відкритих позицій: журнал містить лише заблоковані входи або бари без сигналу. Перегляньте вкладку «Рішення по барах»."
            />
          ) : (
            <DecisionLogPanel
              sessionId={sessionId}
              catalogPath={catalogPath}
              barInterval={barInterval}
              instrumentId={instrumentId}
            />
          )}
        </div>
      </div>
    </div>
  );
};
