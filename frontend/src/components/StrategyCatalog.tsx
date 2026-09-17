import React, { useState } from 'react';
import { CheckCircle, ChevronDown, ChevronUp, Cpu, Play, XCircle } from 'lucide-react';
import type { StrategySpec } from '../services/api';

interface StrategyCatalogProps {
  strategies: StrategySpec[];
  onSelectStrategy: (robotName: string) => void;
}

const STATUS_STYLE: Record<string, string> = {
  validated: 'text-emerald-400',
  rejected: 'text-red-400',
  candidate: 'text-amber-400',
};

/**
 * Directory of the machine-validated specs.
 *
 * `grid_source` is shown deliberately: the parameter grid is chosen per robot, and a robot
 * with no branch of its own silently borrows the `regime` grid, which makes an untuned
 * robot look tuned. `wired_in_backtest` is the other half — a spec without a backtest
 * adapter fails closed rather than running something else.
 */
export const StrategyCatalog: React.FC<StrategyCatalogProps> = ({
  strategies,
  onSelectStrategy,
}) => {
  const [expanded, setExpanded] = useState<string | null>(null);

  const wired = strategies.filter((spec) => spec.wired_in_backtest);
  // `default_branch` means "no branch of its own in param_grid.py, so the regime grid is
  // applied". That is correct for `regime` itself and a trap for every other runnable
  // robot: it selects parameters belonging to a different strategy.
  const borrowedGrid = wired.filter(
    (spec) => spec.name !== 'regime' && spec.grid_source !== 'explicit',
  );

  return (
    <div className="flex flex-col gap-6">
      <div className="bg-gray-900 border border-gray-800 p-6 rounded-2xl flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Cpu className="w-6 h-6 text-purple-400" />
          <h2 className="text-xl font-bold text-gray-100">Strategy &amp; robot directory</h2>
        </div>
        <p className="text-sm text-gray-400">
          Read from <code className="text-gray-300">specs/strategies/*.yaml</code> and validated
          against the code. {wired.length} of {strategies.length} robots are wired to the backtest
          engine; the rest fail closed.
        </p>
        {borrowedGrid.length > 0 ? (
          <p className="text-[11px] text-amber-400/90">
            {borrowedGrid.length} wired robot(s) have no parameter grid of their own and would
            borrow the <span className="font-mono">regime</span> grid:{' '}
            <span className="font-mono">{borrowedGrid.map((spec) => spec.name).join(', ')}</span>.
            Their selection is not meaningful until that is fixed.
          </p>
        ) : (
          <p className="text-[11px] text-emerald-400/80">
            Every wired robot except <span className="font-mono">regime</span> has an explicit
            parameter grid of its own, so no robot is silently selecting on another&apos;s grid.
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {strategies.map((strat) => (
          <div
            key={strat.name}
            className="bg-gray-900 border border-gray-800 hover:border-gray-700 rounded-2xl p-5 flex flex-col justify-between transition-colors gap-4"
          >
            <div className="flex flex-col gap-3">
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-lg font-bold text-gray-100 font-mono">{strat.name}</h3>
                <span
                  className={`px-2.5 py-0.5 text-xs font-mono rounded-full border shrink-0 ${
                    strat.wired_in_backtest
                      ? 'bg-emerald-950/60 text-emerald-400 border-emerald-800/50'
                      : 'bg-red-950/60 text-red-400 border-red-800/50'
                  }`}
                >
                  {strat.wired_in_backtest ? 'wired' : 'fail closed'}
                </span>
              </div>

              <p className="text-xs text-gray-400 leading-relaxed">
                {strat.summary || 'No summary in the spec.'}
              </p>

              <div className="bg-gray-950/70 p-3 rounded-xl border border-gray-800/70 text-xs flex flex-col gap-1.5 font-mono">
                <div className="flex justify-between gap-2 text-gray-500">
                  <span>Class:</span>
                  <span className="text-gray-300 truncate">
                    {strat.strategy_class || strat.domain_module}
                  </span>
                </div>
                <div className="flex justify-between text-gray-500">
                  <span>Min bars:</span>
                  <span className="text-gray-300">{strat.minimum_bars}</span>
                </div>
                <div className="flex justify-between gap-2 text-gray-500">
                  <span>Grid:</span>
                  <span
                    title={
                      strat.grid_source === 'explicit'
                        ? 'Has its own branch in application/param_grid.py'
                        : 'No branch of its own: the regime grid applies'
                    }
                    className={`truncate ${
                      strat.grid_source === 'explicit' ? 'text-gray-300' : 'text-amber-400'
                    }`}
                  >
                    {strat.grid_source ?? 'default_branch'}
                  </span>
                </div>
                <div className="flex justify-between text-gray-500">
                  <span>Status:</span>
                  <span className={`font-semibold ${STATUS_STYLE[strat.status] ?? 'text-gray-300'}`}>
                    {strat.status}
                  </span>
                </div>
                {strat.params?.length > 0 && (
                  <div className="flex justify-between text-gray-500">
                    <span>Params:</span>
                    <span className="text-gray-300">{strat.params.length}</span>
                  </div>
                )}
              </div>

              {strat.hypothesis && (
                <div>
                  <button
                    type="button"
                    onClick={() => setExpanded(expanded === strat.name ? null : strat.name)}
                    className="text-[11px] text-blue-400 hover:text-blue-300 flex items-center gap-1"
                  >
                    {expanded === strat.name ? (
                      <ChevronUp className="w-3.5 h-3.5" />
                    ) : (
                      <ChevronDown className="w-3.5 h-3.5" />
                    )}
                    {expanded === strat.name ? 'Hide hypothesis' : 'Show hypothesis'}
                  </button>
                  {expanded === strat.name && (
                    <p className="text-[11px] text-gray-400 leading-snug mt-2 whitespace-pre-line">
                      {strat.hypothesis}
                    </p>
                  )}
                </div>
              )}
            </div>

            <div className="flex items-center justify-between pt-3 border-t border-gray-800/80 gap-2">
              <span className="text-xs text-gray-500 flex items-center gap-1">
                {strat.wired_in_backtest ? (
                  <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                ) : (
                  <XCircle className="w-3.5 h-3.5 text-red-400" />
                )}
                {strat.wired_in_backtest ? 'Engine ready' : 'Domain only'}
              </span>

              {strat.wired_in_backtest ? (
                <button
                  type="button"
                  onClick={() => onSelectStrategy(strat.name)}
                  className="px-3 py-1.5 bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 border border-blue-500/30 rounded-xl text-xs font-medium transition-colors flex items-center gap-1.5"
                >
                  <Play className="w-3 h-3" /> Test in Lab
                </button>
              ) : (
                <span className="text-[10px] text-gray-600 font-mono">
                  require_backtest_support() blocks it
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
