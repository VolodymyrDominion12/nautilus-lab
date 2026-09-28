import React from 'react';
import { Activity } from 'lucide-react';
import type { TradeDetail, TradeDecisionStep } from '../../services/api';
import { indicatorRows } from '../../lib/trades';

interface TradeIndicatorTableProps {
  trade: TradeDetail;
}

const formatValue = (value: unknown): string => {
  if (value == null) return '—';
  if (typeof value === 'boolean') return value ? 'так' : 'ні';
  if (typeof value === 'number') return String(value);
  return String(value);
};

const stepValuePreview = (step: TradeDecisionStep): string => {
  const values = Object.entries(step.values ?? {});
  const shown = values
    .slice(0, 6)
    .map(([key, value]) => `${key}=${formatValue(value)}`)
    .join(', ');
  return values.length > 6 ? `${shown}, …` : shown;
};

/**
 * What the robot saw when it entered and when it left.
 *
 * Indicators and filter readings (`states`) come from the same record the decision was
 * made on, so this is the entry bar's reading next to the exit bar's — the pair a reader
 * needs to ask "was the exit the same setup reversing, or something else?".
 *
 * A backtest writes `steps` as an empty list by design, and an empty section would read as
 * "the robot decided nothing", so the chain of verdicts is only rendered when it exists.
 */
export const TradeIndicatorTable: React.FC<TradeIndicatorTableProps> = ({ trade }) => {
  const rows = indicatorRows(trade.indicators_at_entry, trade.indicators_at_exit);
  const states = indicatorRows(trade.states_at_entry, trade.states_at_exit);
  const steps = trade.steps_at_entry ?? [];

  return (
    <div className="space-y-4">
      <section className="border border-gray-800 rounded-xl overflow-hidden">
        <header className="flex items-center gap-2 px-3 py-2 bg-gray-950/70 border-b border-gray-800">
          <Activity className="w-4 h-4 text-gray-400" />
          <h3 className="text-sm font-semibold text-gray-100">Індикатори: вхід → вихід</h3>
          <span className="ml-auto text-[10px] text-gray-500 font-mono">з журналу рішень</span>
        </header>
        {rows.length === 0 ? (
          <p className="p-4 text-xs text-gray-500">
            У записах цієї угоди немає індикаторів: старі записи (`decision_trace/0`) писалися
            до того, як ланцюжок рішень почав їх зберігати.
          </p>
        ) : (
          <div className="overflow-auto max-h-72">
            <table className="w-full text-left text-[11px] font-mono">
              <thead className="bg-gray-950/80 text-gray-400 sticky top-0">
                <tr>
                  <th className="p-2 font-medium">Показник</th>
                  <th className="p-2 font-medium text-right">На вході</th>
                  <th className="p-2 font-medium text-right">На виході</th>
                  <th className="p-2 font-medium text-right">Зміна</th>
                </tr>
              </thead>
              <tbody className="text-gray-300 divide-y divide-gray-800/40">
                {rows.map((row) => (
                  <tr key={row.name}>
                    <td className="p-2 text-gray-200">{row.name}</td>
                    <td className="p-2 text-right">
                      {row.entry == null ? '—' : row.entry.toFixed(4)}
                    </td>
                    <td className="p-2 text-right">
                      {row.exit == null ? '—' : row.exit.toFixed(4)}
                    </td>
                    <td
                      className={`p-2 text-right ${
                        row.delta == null
                          ? 'text-gray-500'
                          : row.delta > 0
                            ? 'text-emerald-400'
                            : row.delta < 0
                              ? 'text-red-400'
                              : 'text-gray-400'
                      }`}
                    >
                      {row.delta == null ? '—' : `${row.delta > 0 ? '+' : ''}${row.delta.toFixed(4)}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {states.length > 0 && (
        <section className="border border-gray-800 rounded-xl overflow-hidden">
          <header className="px-3 py-2 bg-gray-950/70 border-b border-gray-800">
            <h3 className="text-sm font-semibold text-gray-100">Стан фільтрів (states)</h3>
          </header>
          <div className="overflow-auto max-h-56">
            <table className="w-full text-left text-[11px] font-mono">
              <thead className="bg-gray-950/80 text-gray-400 sticky top-0">
                <tr>
                  <th className="p-2 font-medium">Фільтр</th>
                  <th className="p-2 font-medium text-right">На вході</th>
                  <th className="p-2 font-medium text-right">На виході</th>
                </tr>
              </thead>
              <tbody className="text-gray-300 divide-y divide-gray-800/40">
                {states.map((row) => (
                  <tr key={row.name}>
                    <td className="p-2 text-gray-200">{row.name}</td>
                    <td className="p-2 text-right">{row.entry == null ? '—' : row.entry.toFixed(4)}</td>
                    <td className="p-2 text-right">{row.exit == null ? '—' : row.exit.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {steps.length > 0 && (
        <section className="border border-gray-800 rounded-xl overflow-hidden">
          <header className="px-3 py-2 bg-gray-950/70 border-b border-gray-800">
            <h3 className="text-sm font-semibold text-gray-100">Ланцюжок рішень на вході</h3>
          </header>
          <div className="divide-y divide-gray-800/40">
            {steps.map((step, index) => (
              <div key={index} className="p-3 text-[11px]">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="px-1.5 py-0.5 rounded bg-gray-800/70 text-gray-400 text-[10px] uppercase">
                    {step.stage ?? 'stage'}
                  </span>
                  <span className="text-gray-200 font-mono">{step.component ?? '—'}</span>
                  <span className="text-purple-300 font-mono">{step.verdict ?? ''}</span>
                  {step.result && <span className="text-amber-200/80">→ {step.result}</span>}
                </div>
                {stepValuePreview(step) && (
                  <div className="mt-1 text-gray-400 font-mono break-words">
                    {stepValuePreview(step)}
                  </div>
                )}
                {step.note && <div className="mt-1 text-gray-500">{step.note}</div>}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
};
