import React, { useState } from 'react';
import { BarChart3, Table2 } from 'lucide-react';
import { formatPct, toNumber } from '../lib/format';
import { InfoTooltip } from './InfoTooltip';
import type { FoldSummary } from '../services/api';

interface FoldBreakdownProps {
  folds: FoldSummary[];
  foldCount: number;
}

const CHART_HEIGHT = 190;
const BAR_GROUP_WIDTH = 54;

/**
 * Per-fold out-of-sample results against the buy&hold baseline.
 *
 * The aggregate alone cannot show whether an edge was stable or one lucky window: a mean
 * of +3% can come from six flat folds and one outlier. Each fold here is a separate
 * forecast, so the bars disagreeing with each other is information.
 */
export const FoldBreakdown: React.FC<FoldBreakdownProps> = ({ folds, foldCount }) => {
  const [showTable, setShowTable] = useState(false);
  if (!folds || folds.length === 0) return null;

  const rows = folds.map((fold) => ({
    fold,
    oos: toNumber(fold.oos_return_raw),
    bh: toNumber(fold.buy_and_hold_return_raw),
    excess: toNumber(fold.excess_return_raw),
  }));

  const magnitudes = rows.flatMap((row) => [Math.abs(row.oos ?? 0), Math.abs(row.bh ?? 0)]);
  const maxMagnitude = Math.max(...magnitudes, 0.0001);
  const scale = (CHART_HEIGHT / 2 - 14) / maxMagnitude;
  const width = Math.max(rows.length * BAR_GROUP_WIDTH + 40, 320);
  const zeroY = CHART_HEIGHT / 2;

  const bar = (value: number | null, centerX: number, offset: number, positiveClass: string) => {
    if (value == null) {
      return (
        <g key={`${centerX}-${offset}`}>
          <rect
            x={centerX + offset - 9}
            y={zeroY - 2}
            width={18}
            height={4}
            rx={2}
            className="fill-gray-700"
          />
        </g>
      );
    }
    const height = Math.abs(value) * scale;
    const y = value >= 0 ? zeroY - height : zeroY;
    return (
      <rect
        x={centerX + offset - 9}
        y={y}
        width={18}
        height={Math.max(height, 2)}
        rx={3}
        className={value >= 0 ? positiveClass : 'fill-red-500/70'}
      />
    );
  };

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-blue-400" />
          <h3 className="text-sm font-bold text-gray-100">Fold-by-fold out-of-sample</h3>
          <InfoTooltip
            title="Повіконний аналіз OOS (Fold-by-fold)"
            subtitle="Перевірка стабільності проти одного випадкового вікна"
            content="Окремі результати на кожному часовому інтервалі. Зелений стовпчик — дохідність робота на OOS, сірий — Buy&Hold пасивного ринку."
            interpretation="Якщо середній прибуток досягнуто лише за рахунок 1 фолду, а решта мінусові — стратегія нестабільна. Справжня перевага має спостерігатись на більшості фолдів."
            size="sm"
          />
          <span className="text-[11px] text-gray-500">
            {foldCount} forecast{foldCount === 1 ? '' : 's'}, each on its own unseen window
          </span>
        </div>
        <div className="flex items-center gap-3 text-[10px] font-mono text-gray-400">
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-sm bg-emerald-500/80 inline-block" /> robot (OOS)
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-sm bg-gray-500/70 inline-block" /> buy&hold
          </span>
          <button
            type="button"
            onClick={() => setShowTable((value) => !value)}
            className="flex items-center gap-1 text-blue-400 hover:text-blue-300"
          >
            <Table2 className="w-3.5 h-3.5" />
            {showTable ? 'Hide detail' : 'Show detail'}
          </button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <svg
          width={width}
          height={CHART_HEIGHT + 26}
          viewBox={`0 0 ${width} ${CHART_HEIGHT + 26}`}
          role="img"
          aria-label="Out-of-sample return per fold compared with buy and hold"
        >
          <line
            x1={20}
            x2={width - 20}
            y1={zeroY}
            y2={zeroY}
            className="stroke-gray-700"
            strokeWidth={1}
          />
          {rows.map((row, index) => {
            const centerX = 40 + index * BAR_GROUP_WIDTH + BAR_GROUP_WIDTH / 2;
            return (
              <g key={row.fold.index}>
                {bar(row.oos, centerX, -11, 'fill-emerald-500/80')}
                {bar(row.bh, centerX, 11, 'fill-gray-500/70')}
                <text
                  x={centerX}
                  y={CHART_HEIGHT + 16}
                  textAnchor="middle"
                  className="fill-gray-500"
                  style={{ fontSize: 10, fontFamily: 'monospace' }}
                >
                  {row.fold.window.out_of_sample_start.slice(0, 10)}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
        {rows.map((row) => (
          <div
            key={row.fold.index}
            className="bg-gray-950/60 border border-gray-800 rounded-xl p-2.5 flex flex-col gap-0.5 font-mono"
          >
            <span className="text-gray-500 font-sans">Fold {row.fold.index + 1}</span>
            <span className={row.excess == null ? 'text-gray-400' : row.excess > 0 ? 'text-emerald-400' : 'text-red-400'}>
              {row.fold.oos_return} <span className="text-gray-500">vs</span> {row.fold.buy_and_hold_return}
            </span>
            <span className="text-gray-500">
              {row.fold.fills} fills · {row.fold.oos_metrics?.max_dd_pct ?? 'n/a'} dd
            </span>
          </div>
        ))}
      </div>

      {showTable && (
        <div className="overflow-x-auto border border-gray-800 rounded-xl">
          <table className="w-full text-[11px] font-mono">
            <thead className="bg-gray-950/80 text-gray-400">
              <tr>
                <th className="text-left p-2">#</th>
                <th className="text-left p-2">OOS window</th>
                <th className="text-right p-2">OOS</th>
                <th className="text-right p-2">Buy&hold</th>
                <th className="text-right p-2">Excess</th>
                <th className="text-right p-2">Fills</th>
                <th className="text-right p-2">Sharpe</th>
                <th className="text-right p-2">Breakeven</th>
                <th className="text-left p-2">Params selected on its in-sample block</th>
              </tr>
            </thead>
            <tbody className="text-gray-300">
              {rows.map((row) => (
                <tr key={row.fold.index} className="border-t border-gray-800/70">
                  <td className="p-2">{row.fold.index + 1}</td>
                  <td className="p-2 whitespace-nowrap">
                    {row.fold.window.out_of_sample_start.slice(0, 10)} →{' '}
                    {row.fold.window.out_of_sample_end.slice(0, 10)}
                  </td>
                  <td className="p-2 text-right">{row.fold.oos_return}</td>
                  <td className="p-2 text-right">{row.fold.buy_and_hold_return}</td>
                  <td
                    className={`p-2 text-right ${
                      row.excess == null ? '' : row.excess > 0 ? 'text-emerald-400' : 'text-red-400'
                    }`}
                  >
                    {row.fold.excess_return}
                  </td>
                  <td className="p-2 text-right">{row.fold.fills}</td>
                  <td className="p-2 text-right">
                    {row.fold.oos_metrics?.sharpe_like != null
                      ? row.fold.oos_metrics.sharpe_like.toFixed(3)
                      : 'n/a'}
                  </td>
                  <td className="p-2 text-right">
                    {row.fold.oos_metrics?.breakeven_cost != null
                      ? `${(row.fold.oos_metrics.breakeven_cost * 10000).toFixed(1)} bps`
                      : 'n/a'}
                  </td>
                  <td className="p-2 text-gray-500 max-w-[320px] truncate" title={row.fold.selected}>
                    {row.fold.selected}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {rows.length > 1 && (
        <p className="text-[11px] text-gray-500">
          Spread between best and worst fold:{' '}
          <span className="font-mono text-gray-300">
            {formatPct(Math.max(...rows.map((r) => r.oos ?? 0)) - Math.min(...rows.map((r) => r.oos ?? 0)))}
          </span>
          . A wide spread means the edge, if any, is not stable.
        </p>
      )}
    </div>
  );
};
