import React from 'react';
import type { LivePosition } from '../../services/api';

interface ActivePositionCardProps {
  position?: LivePosition | null;
  editSl: string;
  setEditSl: (val: string) => void;
  editTp: string;
  setEditTp: (val: string) => void;
  onUpdateStops: () => void;
  onClosePosition: () => void;
}

export const ActivePositionCard: React.FC<ActivePositionCardProps> = ({
  position,
  editSl,
  setEditSl,
  editTp,
  setEditTp,
  onUpdateStops,
  onClosePosition,
}) => {
  return (
    <div className="bg-[#0d131f] border border-gray-800 p-4 rounded-2xl space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-gray-300">Active Position</span>
        {position ? (
          <span
            className={`px-2 py-0.5 text-[10px] font-bold font-mono rounded ${
              position.side === 'LONG'
                ? 'bg-emerald-950/60 text-emerald-300 border border-emerald-800/50'
                : 'bg-red-950/60 text-red-300 border border-red-800/50'
            }`}
          >
            {position.side} {position.qty}
          </span>
        ) : (
          <span className="text-[10px] text-gray-500 font-mono">FLAT</span>
        )}
      </div>

      {position ? (
        <div className="space-y-2.5 pt-1 text-xs font-mono">
          <div className="flex justify-between">
            <span className="text-gray-400">Entry Price:</span>
            <span className="text-gray-200">${position.entry_price}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Mark Price:</span>
            <span className="text-blue-400">${position.mark_price}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Unrealized PnL:</span>
            <span
              className={
                parseFloat(position.unrealized_pnl) >= 0
                  ? 'text-emerald-400 font-bold'
                  : 'text-red-400 font-bold'
              }
            >
              ${position.unrealized_pnl} ({position.unrealized_pnl_pct})
            </span>
          </div>

          {/* Adjust SL/TP Inputs */}
          <div className="pt-2 border-t border-gray-800 space-y-2">
            <div>
              <label className="text-[10px] text-gray-400 block mb-0.5">Stop Loss ($)</label>
              <input
                type="number"
                value={editSl}
                onChange={(e) => setEditSl(e.target.value)}
                placeholder="SL price"
                className="w-full bg-gray-950 border border-gray-800 rounded-lg px-2.5 py-1.5 text-xs font-mono text-red-300 focus:outline-none focus:border-red-500/50"
              />
            </div>
            <div>
              <label className="text-[10px] text-gray-400 block mb-0.5">Take Profit ($)</label>
              <input
                type="number"
                value={editTp}
                onChange={(e) => setEditTp(e.target.value)}
                placeholder="TP price"
                className="w-full bg-gray-950 border border-gray-800 rounded-lg px-2.5 py-1.5 text-xs font-mono text-emerald-300 focus:outline-none focus:border-emerald-500/50"
              />
            </div>
            <button
              type="button"
              onClick={onUpdateStops}
              className="w-full py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-200 rounded-lg text-xs font-medium transition-colors"
            >
              Update Stops
            </button>
          </div>

          {/* Market Close Button */}
          <button
            type="button"
            onClick={onClosePosition}
            className="w-full py-2 bg-red-950/60 hover:bg-red-900/60 border border-red-800/50 text-red-200 rounded-xl text-xs font-semibold transition-colors mt-2"
          >
            Close Position (Market)
          </button>
        </div>
      ) : (
        <div className="py-6 text-center text-xs text-gray-500 border border-dashed border-gray-800/80 rounded-xl">
          No open position. Waiting for robot signal...
        </div>
      )}
    </div>
  );
};
