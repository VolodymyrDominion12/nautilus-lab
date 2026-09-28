import React, { useState } from 'react';
import { ChevronDown, ChevronRight, ListTree } from 'lucide-react';
import type { TradeDecisionRow, TradeDetail } from '../../services/api';
import { describeDecision, isPivotalDecision, outcomeLabel } from '../../lib/trades';
import { DecisionSteps } from '../DecisionSteps';

interface TradeDecisionTimelineProps {
  trade: TradeDetail;
  /** Why some sections are thinner than expected (a backtest writes no `steps`). */
  note?: string | null;
}

const rowClass = (row: TradeDecisionRow): string => {
  switch (row.outcome) {
    case 'ENTRY_OPENED':
    case 'REVERSE':
      return 'border-l-2 border-emerald-500/70';
    case 'TAKE_PROFIT':
      return 'border-l-2 border-emerald-400/70';
    case 'STOP_LOSS':
      return 'border-l-2 border-red-500/70';
    case 'MANUAL_CLOSE':
    case 'FLATTEN_REGIME_CHANGE':
    case 'EXIT':
      return 'border-l-2 border-sky-500/70';
    default:
      return 'border-l-2 border-gray-800';
  }
};

/**
 * Every bar the trade lived through, oldest first, with the raw record behind a click.
 *
 * This is the "why" of the trade: the decision log holds one record per closed bar, so the
 * timeline is the whole life of the position — including the bars where the robot looked
 * and did nothing, which is where a reader usually finds out whether the exit was a plan
 * or a reaction.
 */
export const TradeDecisionTimeline: React.FC<TradeDecisionTimelineProps> = ({ trade, note }) => {
  const [expanded, setExpanded] = useState<number | null>(null);
  const rows = trade.decisions ?? [];

  return (
    <section className="border border-gray-800 rounded-xl overflow-hidden">
      <header className="flex items-center gap-2 px-3 py-2 bg-gray-950/70 border-b border-gray-800">
        <ListTree className="w-4 h-4 text-gray-400" />
        <h3 className="text-sm font-semibold text-gray-100">Ланцюжок рішень угоди</h3>
        <span className="ml-auto text-[10px] text-gray-500 font-mono">{rows.length} записів</span>
      </header>

      {note && (
        <p className="px-3 py-2 text-[11px] text-amber-200/90 bg-amber-950/20 border-b border-amber-900/40">
          {note}
        </p>
      )}

      <div className="max-h-96 overflow-auto divide-y divide-gray-800/40">
        {rows.map((row, index) => (
          <div key={`${row.ts}-${index}`} className={`${rowClass(row)} hover:bg-gray-800/20`}>
            <button
              type="button"
              onClick={() => setExpanded(expanded === index ? null : index)}
              className="w-full text-left px-3 py-2 flex items-start gap-2"
            >
              {expanded === index ? (
                <ChevronDown className="w-3.5 h-3.5 mt-0.5 text-gray-500 shrink-0" />
              ) : (
                <ChevronRight className="w-3.5 h-3.5 mt-0.5 text-gray-500 shrink-0" />
              )}
              <span className="font-mono text-[11px] text-gray-400 whitespace-nowrap w-40 shrink-0">
                {row.ts.replace('T', ' ').slice(0, 19)}
              </span>
              <span
                className={`font-mono text-[11px] w-32 shrink-0 ${
                  isPivotalDecision(row) ? 'text-amber-300' : 'text-gray-500'
                }`}
              >
                {outcomeLabel(row.outcome)}
              </span>
              <span className="font-mono text-[11px] text-blue-400 w-24 shrink-0 text-right">
                ${Number(row.close ?? 0).toFixed(2)}
              </span>
              <span className="text-[11px] text-gray-300 flex-1 break-words">
                {describeDecision(row)}
              </span>
            </button>

            {expanded === index && (
              <div className="px-3 pb-3 pl-9 space-y-2 text-[10px] text-gray-400 font-mono">
                {row.kind && <div className="text-gray-500">kind: {row.kind}</div>}
                {row.blocked_by && <div className="text-amber-300">заблоковано: {row.blocked_by}</div>}
                <DecisionSteps steps={row.steps} />
                {row.indicators && Object.keys(row.indicators).length > 0 && (
                  <div>
                    indicators:{' '}
                    {Object.entries(row.indicators)
                      .map(([key, value]) => `${key}=${String(value)}`)
                      .join(', ')}
                  </div>
                )}
                {row.states && Object.keys(row.states).length > 0 && (
                  <div>
                    states:{' '}
                    {Object.entries(row.states)
                      .map(([key, value]) => `${key}=${String(value)}`)
                      .join(', ')}
                  </div>
                )}
                {row.account && Object.keys(row.account).length > 0 && (
                  <div>
                    account:{' '}
                    {Object.entries(row.account)
                      .map(([key, value]) => `${key}=${String(value)}`)
                      .join(', ')}
                  </div>
                )}
                {row.narrative && <div className="text-gray-500">{row.narrative}</div>}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
};
