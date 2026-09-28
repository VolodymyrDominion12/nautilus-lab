import React from 'react';
import { X } from 'lucide-react';
import { DecisionLogPanel } from './DecisionLogPanel';

import type { HistoryEntry } from '../services/api';

interface BacktestDetailsModalProps {
  entry: HistoryEntry;
  onClose: () => void;
}

export const BacktestDetailsModal: React.FC<BacktestDetailsModalProps> = ({ entry, onClose }) => {
  const sessionId = entry.single_backtest?.session_id || '';
  const catalogPath = entry.config?.catalog_path || undefined;
  const barInterval = entry.config?.bar_interval || undefined;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="bg-gray-950 border border-gray-800 rounded-2xl w-full max-w-7xl h-[85vh] flex flex-col shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between p-4 border-b border-gray-800/80 bg-gray-900/50">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-bold text-gray-100">Backtest Details</h2>
            <span className="text-xs font-mono text-gray-500 bg-gray-800/40 px-2 py-1 rounded">
              {sessionId}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          <DecisionLogPanel 
            sessionId={sessionId} 
            catalogPath={catalogPath} 
            barInterval={barInterval}
            instrumentId={entry.config?.instrument_id || undefined}
          />
        </div>
      </div>
    </div>
  );
};
