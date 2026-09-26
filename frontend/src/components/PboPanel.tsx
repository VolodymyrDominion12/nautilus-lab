import React from 'react';
import { AlertTriangle, Grid3x3, Percent } from 'lucide-react';
import { MetricCard } from './MetricCard';
import { InfoTooltip } from './InfoTooltip';
import { toNumber } from '../lib/format';
import type { PboSummary } from '../services/api';

interface PboPanelProps {
  pbo: PboSummary;
}

/** Colour for one matrix cell: green for a profitable block, red for a losing one. */
const cellColor = (value: number | null, maxAbs: number): string => {
  if (value == null) return 'rgba(75, 85, 99, 0.25)';
  if (maxAbs <= 0) return 'rgba(107, 114, 128, 0.35)';
  const intensity = Math.min(Math.abs(value) / maxAbs, 1);
  const alpha = 0.18 + intensity * 0.72;
  return value >= 0 ? `rgba(16, 185, 129, ${alpha})` : `rgba(239, 68, 68, ${alpha})`;
};

/**
 * Probability of backtest overfitting, plus the matrix it was computed from.
 *
 * PBO asks a different question from a walk-forward: not "did this strategy earn money"
 * but "does picking the best configuration in-sample survive out of sample". The matrix is
 * what makes the single number checkable — one row per contiguous block, one column per
 * grid configuration — so a low PBO caused by one dominant column is visible as such.
 */
export const PboPanel: React.FC<PboPanelProps> = ({ pbo }) => {
  const pboValue = toNumber(pbo.pbo);
  const dsr = pbo.deflated_sharpe;
  const dsrProbability = toNumber(dsr.probability);
  const dsrThreshold = toNumber(dsr.threshold_sharpe);
  const dsrSharpe = toNumber(dsr.sharpe);

  const matrix = pbo.block_returns ?? [];
  const labels = pbo.labels ?? [];
  const flat = matrix.flat().filter((value): value is number => value != null);
  const maxAbs = flat.length > 0 ? Math.max(...flat.map(Math.abs)) : 0;

  const verdict =
    pboValue == null
      ? 'PBO undefined for this run'
      : pboValue < 0.5
        ? 'Selection generalises better than chance'
        : 'Selection is no better than a coin flip';

  const columnTotals = labels.map((_, columnIndex) =>
    matrix.reduce((total, row) => total + (row[columnIndex] ?? 0), 0),
  );

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-5">
      <div className="flex items-center gap-2 flex-wrap">
        <Percent className="w-4 h-4 text-purple-400" />
        <h3 className="text-sm font-bold text-gray-100">Overfitting audit (PBO / CSCV)</h3>
        <InfoTooltip term="pbo" size="sm" />
        <span className="text-[11px] font-mono px-2 py-0.5 rounded-full border bg-purple-950/60 text-purple-300 border-purple-800/50">
          measures the selection, not the PnL
        </span>
      </div>

      <p className="text-xs text-gray-400 leading-snug">{pbo.summary_line}</p>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <MetricCard
          label="PBO"
          value={pbo.pbo ?? 'undefined'}
          tone={pboValue == null ? 'neutral' : pboValue < 0.5 ? 'positive' : 'negative'}
          hint={verdict}
        />
        <MetricCard
          label="CSCV splits"
          value={pbo.split_count}
          hint={`${pbo.configuration_count} configurations × ${pbo.blocks} blocks`}
        />
        <MetricCard
          label="Deflated Sharpe"
          value={dsr.probability ?? 'undefined'}
          tone={dsrProbability == null ? 'neutral' : dsrProbability > 0.95 ? 'positive' : 'negative'}
          hint={`Observed ${dsr.sharpe ?? 'n/a'} vs best-of-${dsr.trials_total ?? dsr.trials}-trials threshold ${dsr.threshold_sharpe ?? 'n/a'}${
            (dsr.trials_total ?? dsr.trials) > dsr.trials ? ` (${dsr.trials} in this run)` : ''
          }`}
        />
        <MetricCard
          label="Sharpe over threshold?"
          value={
            dsrSharpe == null || dsrThreshold == null
              ? 'n/a'
              : dsrSharpe > dsrThreshold
                ? 'yes'
                : 'no'
          }
          tone={dsrSharpe != null && dsrThreshold != null && dsrSharpe > dsrThreshold ? 'positive' : 'negative'}
          hint="A Sharpe below the threshold is what N random trials would have produced anyway"
        />
      </div>

      {dsr.probability == null && (
        <div className="flex items-start gap-2 text-[11px] text-amber-300 bg-amber-950/30 border border-amber-800/40 rounded-xl p-3">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span>
            Deflated Sharpe is undefined here: {dsr.note || 'too few observations for the correction'}.
            Raising --pbo-blocks buys a wider sample.
          </span>
        </div>
      )}

      {!pbo.is_meaningful && (
        <div className="flex items-start gap-2 text-[11px] text-amber-300 bg-amber-950/30 border border-amber-800/40 rounded-xl p-3">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span>
            {pbo.configuration_count} configuration(s) × {pbo.blocks} blocks: PBO needs at least two
            configurations and two splits to say anything. Nothing can be concluded from this run.
          </span>
        </div>
      )}

      {matrix.length > 0 && labels.length > 0 && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <Grid3x3 className="w-4 h-4 text-gray-400" />
            <h4 className="text-xs font-semibold text-gray-200">
              Block returns — {matrix.length} blocks × {labels.length} configurations
            </h4>
            <InfoTooltip
              title="Матриця повернень блоків (Block Returns Matrix)"
              subtitle="Візуалізація стійкості конфігурацій"
              content="Кожен рядок — це окремий неперервний часовий блок (block), а кожен стовпчик — протестована конфігурація параметрів сітки (#0, #1...). Зірочкою (★) позначена конфігурація, яка перемогла на In-Sample."
              interpretation="Якщо найкраща колонка має багато червоних клітинок на інших блоках, вона не є універсальною та має високий ризик перенавчання."
              size="xs"
            />
          </div>
          <p className="text-[11px] text-gray-500">
            One row per contiguous block, one column per grid configuration. Grey means the engine
            reported no balance for that run. The highlighted column is the one that looked best
            in-sample.
          </p>
          <div className="overflow-x-auto border border-gray-800 rounded-xl">
            <table className="text-[10px] font-mono">
              <thead>
                <tr className="bg-gray-950/80 text-gray-400">
                  <th className="text-left p-2 sticky left-0 bg-gray-950/95">block</th>
                  {labels.map((label, index) => (
                    <th
                      key={`${label}-${index}`}
                      className={`p-2 text-center whitespace-nowrap ${
                        pbo.best_configuration_index === index ? 'text-blue-300' : ''
                      }`}
                      title={label}
                    >
                      {index === pbo.best_configuration_index ? '★ ' : ''}#{index}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrix.map((row, blockIndex) => (
                  <tr key={blockIndex}>
                    <td className="p-2 text-gray-500 sticky left-0 bg-gray-900/95 whitespace-nowrap">
                      b{blockIndex + 1}
                    </td>
                    {row.map((value, columnIndex) => (
                      <td
                        key={columnIndex}
                        className="p-0"
                        title={`block ${blockIndex + 1}, config #${columnIndex}: ${
                          value == null ? 'no balance reported' : `${(value * 100).toFixed(2)}%`
                        }`}
                      >
                        <div
                          className="w-16 h-6 flex items-center justify-center text-gray-100"
                          style={{ backgroundColor: cellColor(value, maxAbs) }}
                        >
                          {value == null ? '—' : (value * 100).toFixed(1)}
                        </div>
                      </td>
                    ))}
                  </tr>
                ))}
                <tr className="border-t border-gray-700">
                  <td className="p-2 text-gray-400 sticky left-0 bg-gray-900/95">sum</td>
                  {columnTotals.map((total, index) => (
                    <td
                      key={index}
                      className={`p-2 text-center ${
                        total > 0 ? 'text-emerald-400' : total < 0 ? 'text-red-400' : 'text-gray-400'
                      }`}
                    >
                      {(total * 100).toFixed(1)}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
          {pbo.best_configuration_label && (
            <div className="text-[11px] text-gray-400 font-mono break-all">
              In-sample winner: {pbo.best_configuration_label}
            </div>
          )}
        </div>
      )}

      {pbo.notes && <p className="text-[11px] text-gray-500 leading-snug">{pbo.notes}</p>}
    </div>
  );
};
