import React from 'react';
import type { FoldRef } from '../../lib/batch';
import { formatDateTime, formatPct } from '../../lib/format';

const MAX_ROWS = 5;

/**
 * The whole "why these parameters" block: a header plus one ranking per fold.
 *
 * Its own component because `RunPage` has a size budget (`componentSize.test.ts`) and this
 * is the part that grew; keeping it here also lets the Research tab reuse it verbatim.
 */
export const SelectionRanking: React.FC<{ folds: FoldRef[]; heading?: string }> = ({
  folds,
  heading = 'Чому ці параметри: відбір на IS',
}) => {
  if (!folds.some((fold) => (fold.candidates?.length ?? 0) > 0)) return null;
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-4 flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h3 className="text-sm font-bold text-gray-100">{heading}</h3>
        <p className="text-[11px] text-gray-500">
          Рейтинг, який побудував підбір параметрів на кожному фолді. Переможець — той, кого потім
          рахували на OOS; решта показує, наскільки вибір був очевидним.
        </p>
      </div>
      {folds.map((fold) => (
        <SelectionCandidates key={fold.session_id ?? fold.index} fold={fold} />
      ))}
    </div>
  );
};

const METRIC_LABEL: Record<string, string> = {
  pnl: 'PnL (баланс мінус знижка за оборот)',
  sharpe: 'Sharpe (по барах)',
  calmar: 'Calmar (доходність / макс. просадка)',
};

/**
 * Why these parameters: the in-sample ranking the search actually produced.
 *
 * The fold stores the winner and the count of trials, which answers "what was chosen" but
 * not "why" — a configuration that won by a mile and one that won by a hair over fourteen
 * others looked identical in the artefact (docs/35 §7, L-2). These are in-sample numbers:
 * they choose parameters and are never a result. The out-of-sample column is the report.
 */
export const SelectionCandidates: React.FC<{ fold: FoldRef }> = ({ fold }) => {
  const candidates = fold.candidates ?? [];
  if (candidates.length === 0) {
    return (
      <div className="text-[11px] text-gray-500">
        Фолд {fold.index}: журнал відбору порожній — або це Optuna (вона не зберігає параметри
        кожної спроби), або прогін старіший за появу цього поля.
      </div>
    );
  }
  const metric = fold.selection_metric ?? '';
  const winner = candidates[0];
  const runnerUp = candidates[1];
  const gap =
    winner.score != null && runnerUp?.score != null ? winner.score - runnerUp.score : null;
  const hidden = candidates.length - MAX_ROWS;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-baseline gap-x-3 text-[11px]">
        <span className="font-mono text-gray-300">Фолд {fold.index}</span>
        <span className="text-gray-500">
          IS-вікно {formatDateTime(fold.window.in_sample_start)} →{' '}
          {formatDateTime(fold.window.in_sample_end)}
        </span>
        <span className="text-gray-500">
          метрика відбору: {METRIC_LABEL[metric] ?? (metric || '—')} · кандидатів:{' '}
          {fold.candidates_tried ?? candidates.length}
        </span>
        {gap != null && (
          <span className={gap === 0 ? 'text-amber-400' : 'text-gray-500'}>
            {gap === 0
              ? 'переможець ділить перше місце з іншим кандидатом'
              : `відрив від другого: ${gap.toPrecision(3)}`}
          </span>
        )}
      </div>
      <table className="w-full text-[11px] font-mono">
        <thead className="text-gray-500">
          <tr>
            <th className="text-left pr-3">#</th>
            <th className="text-left pr-3">Параметри</th>
            <th className="text-right pr-3">IS-оцінка</th>
            <th className="text-right">IS-доходність</th>
          </tr>
        </thead>
        <tbody>
          {candidates.slice(0, MAX_ROWS).map((candidate, index) => (
            <tr
              key={candidate.label}
              className={index === 0 ? 'border-t border-gray-800 bg-blue-950/30' : 'border-t border-gray-800'}
            >
              <td className="py-0.5 pr-3 text-gray-500">
                {index === 0 ? '★' : index + 1}
              </td>
              <td className="pr-3 text-gray-300">{candidate.label}</td>
              <td className="pr-3 text-right text-gray-300">
                {candidate.score == null ? '—' : candidate.score.toPrecision(4)}
              </td>
              <td className="text-right text-gray-400">
                {formatPct(candidate.in_sample_return)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[10px] text-gray-500">
        Це in-sample: параметри обираються тут, результат звітується на OOS. Різниця між оцінками
        показує, наскільки вибір був очевидним, а не наскільки стратегія добра.
        {hidden > 0 && ` Ще ${hidden} кандидатів не показано.`}
      </p>
    </div>
  );
};
