import React from 'react';
import { ArrowDownRight, ArrowUpRight } from 'lucide-react';
import type { LivePaperState } from '../../services/api';

interface LiveMetricsRibbonProps {
  state: LivePaperState | null;
  startingEquity: string;
  symbol: string;
}

export const LiveMetricsRibbon: React.FC<LiveMetricsRibbonProps> = ({
  state,
  startingEquity,
  symbol,
}) => {
  const currentEquityNum = parseFloat(state?.current_equity || startingEquity);
  const startingEquityNum = parseFloat(state?.starting_equity || startingEquity);
  const netPnlNum = currentEquityNum - startingEquityNum;
  const netPnlPct = startingEquityNum > 0 ? (netPnlNum / startingEquityNum) * 100 : 0;
  const unrealizedPnlNum = parseFloat(state?.unrealized_pnl || '0');

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      <div className="bg-[#0d131f] border border-gray-800/80 p-3.5 rounded-xl">
        <span className="text-[11px] text-gray-400 block mb-1">Account Equity</span>
        <div className="text-base font-bold font-mono text-gray-100">
          ${currentEquityNum.toLocaleString('en-US', { minimumFractionDigits: 2 })}
        </div>
        <span className="text-[10px] text-gray-500">Initial: ${startingEquityNum}</span>
      </div>

      <div className="bg-[#0d131f] border border-gray-800/80 p-3.5 rounded-xl">
        <span className="text-[11px] text-gray-400 block mb-1">Realized PnL</span>
        <div
          className={`text-base font-bold font-mono flex items-center gap-1 ${
            parseFloat(state?.realized_pnl || '0') >= 0 ? 'text-emerald-400' : 'text-red-400'
          }`}
        >
          {parseFloat(state?.realized_pnl || '0') >= 0 ? (
            <ArrowUpRight className="w-4 h-4" />
          ) : (
            <ArrowDownRight className="w-4 h-4" />
          )}
          ${state?.realized_pnl || '0.00'}
        </div>
        <span className="text-[10px] text-gray-500">Closed trades</span>
      </div>

      <div className="bg-[#0d131f] border border-gray-800/80 p-3.5 rounded-xl">
        <span className="text-[11px] text-gray-400 block mb-1">Floating PnL</span>
        <div
          className={`text-base font-bold font-mono flex items-center gap-1 ${
            unrealizedPnlNum >= 0 ? 'text-emerald-400' : 'text-red-400'
          }`}
        >
          {unrealizedPnlNum >= 0 ? (
            <ArrowUpRight className="w-4 h-4" />
          ) : (
            <ArrowDownRight className="w-4 h-4" />
          )}
          ${unrealizedPnlNum.toFixed(2)}
        </div>
        <span className="text-[10px] text-gray-500">
          {state?.position ? state.position.unrealized_pnl_pct : 'No open position'}
        </span>
      </div>

      <div className="bg-[#0d131f] border border-gray-800/80 p-3.5 rounded-xl">
        <span className="text-[11px] text-gray-400 block mb-1">Current Mark</span>
        <div className="text-base font-bold font-mono text-blue-400">
          {state?.last_price ? `$${parseFloat(state.last_price).toLocaleString()}` : '—'}
        </div>
        <span className="text-[10px] text-gray-500">{symbol} Binance spot</span>
      </div>

      <div className="bg-[#0d131f] border border-gray-800/80 p-3.5 rounded-xl">
        <span className="text-[11px] text-gray-400 block mb-1">Exchange Fees</span>
        <div className="text-base font-bold font-mono text-gray-300">
          ${parseFloat(state?.fees_paid || '0').toFixed(4)}
        </div>
        <span className="text-[10px] text-gray-500">Simulated taker</span>
      </div>

      <div className="bg-[#0d131f] border border-gray-800/80 p-3.5 rounded-xl">
        <span className="text-[11px] text-gray-400 block mb-1">Session Total Return</span>
        <div
          className={`text-base font-bold font-mono ${
            netPnlNum >= 0 ? 'text-emerald-400' : 'text-red-400'
          }`}
        >
          {netPnlPct >= 0 ? '+' : ''}
          {netPnlPct.toFixed(2)}%
        </div>
        <span className="text-[10px] text-gray-500">{state?.fills.length || 0} order fills</span>
      </div>
    </div>
  );
};
