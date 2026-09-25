import React from 'react';
import type { LivePaperState } from '../services/api';
import { DecisionLogPanel } from './DecisionLogPanel';

interface LiveTradingTabsProps {
  activeTab: 'position' | 'fills' | 'risk' | 'decision_logs';
  onTabChange: (tab: 'position' | 'fills' | 'risk' | 'decision_logs') => void;
  state: LivePaperState | null;
  sessionId: string | null;
}

export const LiveTradingTabs: React.FC<LiveTradingTabsProps> = ({
  activeTab,
  onTabChange,
  state,
  sessionId,
}) => {
  return (
    <div className="bg-[#0d131f] border border-gray-800 rounded-2xl overflow-hidden">
      {/* Tab Headers */}
      <div className="flex border-b border-gray-800 bg-gray-950/60 px-4">
        <button
          type="button"
          onClick={() => onTabChange('position')}
          className={`px-4 py-3 text-xs font-semibold border-b-2 transition-colors ${
            activeTab === 'position'
              ? 'border-blue-500 text-blue-400'
              : 'border-transparent text-gray-400 hover:text-gray-200'
          }`}
        >
          Position Details {state?.position ? '(1)' : '(0)'}
        </button>
        <button
          type="button"
          onClick={() => onTabChange('fills')}
          className={`px-4 py-3 text-xs font-semibold border-b-2 transition-colors ${
            activeTab === 'fills'
              ? 'border-blue-500 text-blue-400'
              : 'border-transparent text-gray-400 hover:text-gray-200'
          }`}
        >
          Order Fills History ({state?.fills.length || 0})
        </button>
        <button
          type="button"
          onClick={() => onTabChange('risk')}
          className={`px-4 py-3 text-xs font-semibold border-b-2 transition-colors ${
            activeTab === 'risk'
              ? 'border-blue-500 text-blue-400'
              : 'border-transparent text-gray-400 hover:text-gray-200'
          }`}
        >
          Equity Trajectory &amp; Risk
        </button>
        <button
          type="button"
          onClick={() => onTabChange('decision_logs')}
          className={`px-4 py-3 text-xs font-semibold border-b-2 transition-colors ${
            activeTab === 'decision_logs'
              ? 'border-purple-500 text-purple-400'
              : 'border-transparent text-gray-400 hover:text-gray-200'
          }`}
        >
          Decision Logs
        </button>
      </div>

      {/* Tab Contents */}
      <div className="p-4">
        {activeTab === 'position' && (
          <div>
            {state?.position ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs font-mono">
                  <thead className="text-[11px] text-gray-500 border-b border-gray-800">
                    <tr>
                      <th className="pb-2">Instrument</th>
                      <th className="pb-2">Side</th>
                      <th className="pb-2">Qty</th>
                      <th className="pb-2">Entry Price</th>
                      <th className="pb-2">Mark Price</th>
                      <th className="pb-2">Stop Loss</th>
                      <th className="pb-2">Take Profit</th>
                      <th className="pb-2">Floating PnL</th>
                      <th className="pb-2">Entry Time</th>
                    </tr>
                  </thead>
                  <tbody className="text-gray-300">
                    <tr className="border-t border-gray-800/40">
                      <td className="py-2.5 font-bold text-white">{state.position.symbol}</td>
                      <td
                        className={`py-2.5 font-bold ${
                          state.position.side === 'LONG' ? 'text-emerald-400' : 'text-red-400'
                        }`}
                      >
                        {state.position.side}
                      </td>
                      <td className="py-2.5">{state.position.qty}</td>
                      <td className="py-2.5">${state.position.entry_price}</td>
                      <td className="py-2.5 text-blue-400">${state.position.mark_price}</td>
                      <td className="py-2.5 text-red-400">
                        {state.position.stop_loss ? `$${state.position.stop_loss}` : '—'}
                      </td>
                      <td className="py-2.5 text-emerald-400">
                        {state.position.take_profit ? `$${state.position.take_profit}` : '—'}
                      </td>
                      <td
                        className={`py-2.5 font-bold ${
                          parseFloat(state.position.unrealized_pnl) >= 0
                            ? 'text-emerald-400'
                            : 'text-red-400'
                        }`}
                      >
                        ${state.position.unrealized_pnl} ({state.position.unrealized_pnl_pct})
                      </td>
                      <td className="py-2.5 text-gray-400">{state.position.entry_time}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-8 text-center text-xs text-gray-500">
                No active position. The session is currently FLAT.
              </div>
            )}
          </div>
        )}

        {activeTab === 'fills' && (
          <div>
            {state?.fills && state.fills.length > 0 ? (
              <div className="overflow-x-auto max-h-60">
                <table className="w-full text-left text-xs font-mono">
                  <thead className="text-[11px] text-gray-500 border-b border-gray-800 sticky top-0 bg-[#0d131f]">
                    <tr>
                      <th className="pb-2">Time (UTC)</th>
                      <th className="pb-2">Symbol</th>
                      <th className="pb-2">Side</th>
                      <th className="pb-2 text-right">Qty</th>
                      <th className="pb-2 text-right">Price</th>
                      <th className="pb-2 text-right">Fee</th>
                      <th className="pb-2 text-right">Realized PnL</th>
                      <th className="pb-2 pl-4">Reason / Trigger</th>
                    </tr>
                  </thead>
                  <tbody className="text-gray-300 divide-y divide-gray-800/40">
                    {state.fills.map((fill) => (
                      <tr key={fill.id} className="hover:bg-gray-800/20">
                        <td className="py-2 text-gray-400 whitespace-nowrap">{fill.ts}</td>
                        <td className="py-2 font-semibold text-gray-200">{fill.symbol}</td>
                        <td
                          className={`py-2 font-bold ${
                            fill.side === 'BUY' ? 'text-emerald-400' : 'text-red-400'
                          }`}
                        >
                          {fill.side}
                        </td>
                        <td className="py-2 text-right">{fill.qty}</td>
                        <td className="py-2 text-right font-medium">${fill.price}</td>
                        <td className="py-2 text-right text-gray-400">${fill.fee}</td>
                        <td
                          className={`py-2 text-right font-bold ${
                            parseFloat(fill.realized_pnl) > 0
                              ? 'text-emerald-400'
                              : parseFloat(fill.realized_pnl) < 0
                                ? 'text-red-400'
                                : 'text-gray-400'
                          }`}
                        >
                          {fill.realized_pnl !== '0.00' ? `$${fill.realized_pnl}` : '—'}
                        </td>
                        <td className="py-2 pl-4 text-gray-400">{fill.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-8 text-center text-xs text-gray-500">
                No orders have been filled in this session yet.
              </div>
            )}
          </div>
        )}

        {activeTab === 'risk' && (
          <div className="space-y-4">
            <div className="text-xs text-gray-400">
              Equity snapshots recorded upon bar closes. Total snapshots:{' '}
              <span className="font-mono text-gray-200">
                {state?.equity_history.length || 0}
              </span>
            </div>
            {state?.equity_history && state.equity_history.length > 0 ? (
              <div className="overflow-x-auto max-h-52">
                <table className="w-full text-left text-xs font-mono">
                  <thead className="text-[11px] text-gray-500 border-b border-gray-800">
                    <tr>
                      <th className="pb-2">Time (Epoch)</th>
                      <th className="pb-2">Equity</th>
                      <th className="pb-2">Realized PnL</th>
                      <th className="pb-2">Unrealized PnL</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800/40 text-gray-300">
                    {state.equity_history.slice(-10).map((pt, idx) => (
                      <tr key={`${pt.time}-${idx}`}>
                        <td className="py-1.5 text-gray-400">
                          {new Date(pt.time * 1000).toLocaleTimeString()}
                        </td>
                        <td className="py-1.5 font-bold text-gray-100">
                          ${pt.equity.toFixed(2)}
                        </td>
                        <td className="py-1.5 text-emerald-400">
                          ${pt.realized_pnl.toFixed(2)}
                        </td>
                        <td className="py-1.5 text-blue-400">
                          ${pt.unrealized_pnl.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-6 text-center text-xs text-gray-500">
                Awaiting the first closed bar to record equity curve snapshots.
              </div>
            )}
          </div>
        )}

        {activeTab === 'decision_logs' &&
          (sessionId ? (
            <DecisionLogPanel sessionId={sessionId} />
          ) : (
            <div className="py-8 text-center text-xs text-gray-500">
              No active session. Start a session to see decision logs.
            </div>
          ))}
      </div>
    </div>
  );
};
