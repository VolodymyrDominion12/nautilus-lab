import React from 'react';
import { Cpu, CheckCircle, XCircle, Play } from 'lucide-react';
import type { StrategySpec } from '../services/api';

interface StrategyCatalogProps {
  strategies: StrategySpec[];
  onSelectStrategy: (robotName: string) => void;
}

export const StrategyCatalog: React.FC<StrategyCatalogProps> = ({
  strategies,
  onSelectStrategy,
}) => {
  return (
    <div className="flex flex-col gap-6">
      <div className="bg-gray-900 border border-gray-800 p-6 rounded-2xl flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Cpu className="w-6 h-6 text-purple-400" />
            <h2 className="text-xl font-bold text-gray-100">Strategy & Robot Directory</h2>
          </div>
          <p className="text-sm text-gray-400 mt-1">
            Machine-validated specifications from <code className="text-gray-300">specs/strategies/*.yaml</code>.
            Only robots wired to the engine can execute backtests; others fail closed as domain blocks.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {strategies.map((strat) => (
          <div
            key={strat.name}
            className="bg-gray-900 border border-gray-800 hover:border-gray-700 rounded-2xl p-5 flex flex-col justify-between transition-colors gap-4"
          >
            <div>
              <div className="flex items-start justify-between gap-2 mb-2">
                <h3 className="text-lg font-bold text-gray-100 font-mono">{strat.name}</h3>
                <span
                  className={`px-2.5 py-0.5 text-xs font-mono rounded-full border ${
                    strat.wired_in_backtest
                      ? 'bg-emerald-950/60 text-emerald-400 border-emerald-800/50'
                      : 'bg-red-950/60 text-red-400 border-red-800/50'
                  }`}
                >
                  {strat.wired_in_backtest ? 'Wired' : 'Fail Closed'}
                </span>
              </div>

              <p className="text-xs text-gray-400 leading-relaxed mb-4">
                {strat.summary || 'No summary available.'}
              </p>

              <div className="bg-gray-950/70 p-3 rounded-xl border border-gray-800/70 text-xs flex flex-col gap-1.5 font-mono">
                <div className="flex justify-between text-gray-500">
                  <span>Class:</span>
                  <span className="text-gray-300">{strat.strategy_class || strat.domain_module}</span>
                </div>
                <div className="flex justify-between text-gray-500">
                  <span>Min Bars:</span>
                  <span className="text-gray-300">{strat.minimum_bars}</span>
                </div>
                <div className="flex justify-between text-gray-500">
                  <span>Status:</span>
                  <span
                    className={`font-semibold ${
                      strat.status === 'validated'
                        ? 'text-emerald-400'
                        : strat.status === 'rejected'
                        ? 'text-red-400'
                        : 'text-amber-400'
                    }`}
                  >
                    {strat.status}
                  </span>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between pt-3 border-t border-gray-800/80">
              <span className="text-xs text-gray-500 flex items-center gap-1">
                {strat.wired_in_backtest ? (
                  <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                ) : (
                  <XCircle className="w-3.5 h-3.5 text-red-400" />
                )}
                {strat.wired_in_backtest ? 'Engine ready' : 'Domain only'}
              </span>

              {strat.wired_in_backtest && (
                <button
                  onClick={() => onSelectStrategy(strat.name)}
                  className="px-3 py-1.5 bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 border border-blue-500/30 rounded-xl text-xs font-medium transition-colors flex items-center gap-1.5"
                >
                  <Play className="w-3 h-3" /> Test in Lab
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
