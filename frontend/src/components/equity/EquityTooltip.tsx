import React from 'react';
import { Calendar } from 'lucide-react';

import type { EquityPoint } from '../../lib/equityCurve';
import { formatPct } from '../../lib/format';

/** The hovered fold: its window, own return, cumulative return, baseline and drawdown. */
export const EquityTooltip: React.FC<{ activePoint: EquityPoint; left: number }> = ({
  activePoint,
  left,
}) => (
    <div
      className="absolute z-20 top-3 bg-gray-900/95 border border-blue-500/30 backdrop-blur-md rounded-xl p-3 text-xs shadow-xl pointer-events-none transition-all"
      style={{ left }}
    >
      <div className="font-bold text-gray-200 border-b border-gray-800 pb-1.5 mb-1.5 flex items-center justify-between gap-3">
        <span>{activePoint.label}</span>
        <span className="text-[10px] font-mono text-gray-400">
          ${Math.round(activePoint.equityValue).toLocaleString()}
        </span>
      </div>

      {activePoint.startDate && (
        <div className="text-[10px] text-gray-400 font-mono flex items-center gap-1 mb-1">
          <Calendar className="w-3 h-3 text-gray-500" />
          {activePoint.startDate.slice(0, 10)} → {activePoint.endDate.slice(0, 10)}
        </div>
      )}

      <div className="flex flex-col gap-1 text-[11px] font-mono mt-1">
        {activePoint.foldIndex > 0 && (
          <div className="flex justify-between gap-4">
            <span className="text-gray-400">Fold OOS Return:</span>
            <span
              className={
                activePoint.foldOosReturn >= 0 ? 'text-emerald-400 font-bold' : 'text-red-400 font-bold'
              }
            >
              {formatPct(activePoint.foldOosReturn)}
            </span>
          </div>
        )}
        <div className="flex justify-between gap-4">
          <span className="text-gray-400">Cumulative Return:</span>
          <span
            className={
              activePoint.cumulativeOosReturn >= 0 ? 'text-emerald-400' : 'text-red-400'
            }
          >
            {formatPct(activePoint.cumulativeOosReturn)}
          </span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-gray-400">Buy &amp; Hold Cumul:</span>
          <span className="text-gray-300">
            {formatPct(activePoint.cumulativeBhReturn)}
          </span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-gray-400">Peak Drawdown:</span>
          <span className="text-amber-400">
            {formatPct(activePoint.drawdownPct)}
          </span>
        </div>
        {activePoint.fills > 0 && (
          <div className="flex justify-between gap-4 text-gray-500 text-[10px]">
            <span>Fills in fold:</span>
            <span>{activePoint.fills}</span>
          </div>
        )}
      </div>
    </div>
);
