import React from 'react';
import { ArrowDownRight, ArrowUpRight, Percent, TrendingDown } from 'lucide-react';

import type { CurveStats } from '../../lib/equityCurve';
import { formatPct } from '../../lib/format';

/** Total OOS return, buy & hold, max drawdown and fold win rate of the chained path. */
export const EquitySummary: React.FC<{ stats: CurveStats; foldCount: number }> = ({
  stats,
  foldCount,
}) => {
  const { totalOos, totalBh, maxDd, winRate, profitableFolds } = stats;
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <div className="bg-gray-950/80 border border-gray-800/80 rounded-xl p-3">
        <div className="text-[10px] text-gray-400 uppercase tracking-wider">Total OOS Return</div>
        <div
          className={`text-base font-bold font-mono mt-0.5 flex items-center gap-1 ${
            totalOos >= 0 ? 'text-emerald-400' : 'text-red-400'
          }`}
        >
          {totalOos >= 0 ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownRight className="w-4 h-4" />}
          {formatPct(totalOos)}
        </div>
      </div>

      <div className="bg-gray-950/80 border border-gray-800/80 rounded-xl p-3">
        <div className="text-[10px] text-gray-400 uppercase tracking-wider">Buy &amp; Hold Baseline</div>
        <div
          className={`text-base font-bold font-mono mt-0.5 flex items-center gap-1 ${
            totalBh >= 0 ? 'text-gray-300' : 'text-red-400/80'
          }`}
        >
          {formatPct(totalBh)}
        </div>
      </div>

      <div className="bg-gray-950/80 border border-gray-800/80 rounded-xl p-3">
        <div className="text-[10px] text-gray-400 uppercase tracking-wider">Max Drawdown</div>
        <div className="text-base font-bold font-mono mt-0.5 text-amber-400 flex items-center gap-1">
          <TrendingDown className="w-4 h-4 text-amber-400" />
          {formatPct(-maxDd)}
        </div>
      </div>

      <div className="bg-gray-950/80 border border-gray-800/80 rounded-xl p-3">
        <div className="text-[10px] text-gray-400 uppercase tracking-wider">Folds Win Rate</div>
        <div className="text-base font-bold font-mono mt-0.5 text-blue-400 flex items-center gap-1">
          <Percent className="w-4 h-4 text-blue-400" />
          {winRate.toFixed(0)}%
          <span className="text-[10px] text-gray-500 font-normal">
            ({profitableFolds}/{foldCount})
          </span>
        </div>
      </div>
    </div>
  );
};
