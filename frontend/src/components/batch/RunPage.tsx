import React, { useEffect, useState } from 'react';
import { AlertTriangle, ArrowLeft } from 'lucide-react';
import { fetchRun, type RunPayload } from '../../services/api';
import { buildBatchHash, rowWarnings, STATUS_CLASS, type RunTab } from '../../lib/batch';
import { TONE_TEXT, formatDateTime, formatPct, toNumber, toneOf } from '../../lib/format';
import { DecisionLogPanel } from '../DecisionLogPanel';
import { RunAnalysisTab } from './RunAnalysisTab';
import { RunTradesTab } from './RunTradesTab';

interface RunPageProps {
  batchId: string;
  cellId: string;
  fold?: number;
  tab?: RunTab;
}

const TABS: { key: RunTab; label: string }[] = [
  { key: 'trades', label: 'Угоди' },
  { key: 'decisions', label: 'Рішення по барах' },
  { key: 'analysis', label: 'Аналіз причин' },
  { key: 'log', label: 'Лог прогону' },
];

/**
 * One run of a batch: the walk-forward's folds, then its trades, decisions and analysis.
 *
 * Fold and tab live in the address (`#/run/<batch>/<cell>?fold=2&tab=analysis`), so a
 * link to "fold 2's blocked entries" can be sent to someone as it is.
 */
export const RunPage: React.FC<RunPageProps> = ({ batchId, cellId, fold, tab = 'trades' }) => {
  const [run, setRun] = useState<RunPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchRun(batchId, cellId)
      .then((data) => alive && setRun(data.run))
      .catch((err: unknown) => alive && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      alive = false;
    };
  }, [batchId, cellId]);

  const go = (next: { fold?: number; tab?: RunTab }) => {
    window.location.hash = buildBatchHash({
      page: 'run',
      batchId,
      cellId,
      fold: 'fold' in next ? next.fold : fold,
      tab: next.tab ?? tab,
    });
  };

  if (error) return <div className="text-sm text-red-400">{error}</div>;
  if (!run) return <div className="text-sm text-gray-500">Завантаження прогону…</div>;

  const cell = run.cell;
  const summary = run.summary;
  const numbers = summary?.numbers;
  const folds = run.folds;
  // Decisions need one fold's session; default to the last (most recent) fold.
  const decisionFold = folds.find((f) => f.index === fold) ?? folds[folds.length - 1];
  const warnings = summary ? rowWarnings(summary) : [];

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-center gap-3 border-b border-gray-800 pb-3">
        <a
          href={buildBatchHash({ page: 'batch', batchId })}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-gray-900 hover:bg-gray-800 text-gray-300 rounded-lg border border-gray-700"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> {run.batch_label || batchId}
        </a>
        <h2 className="text-lg font-bold text-gray-100 font-mono">{cellId}</h2>
        <span className="text-xs text-gray-400 font-mono">
          {cell.instrument_id} · {cell.interval} · {cell.catalog}
        </span>
        <span className={`text-xs font-mono ${STATUS_CLASS[cell.status] ?? ''}`}>{cell.status}</span>
      </header>

      {cell.error && <div className="text-xs text-red-400">{cell.error}</div>}
      {warnings.map((warning) => (
        <div key={warning} className="flex items-center gap-1.5 text-xs text-amber-400">
          <AlertTriangle className="w-3.5 h-3.5" /> {warning}
        </div>
      ))}

      {numbers && (
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3 text-xs">
          {[
            ['Mean OOS', numbers.mean_oos],
            ['Worst фолд', numbers.worst_oos],
            ['Buy&hold', numbers.buy_and_hold_mean],
            ['Над buy&hold', numbers.mean_excess],
          ].map(([label, value]) => (
            <div key={label as string} className="p-3 rounded-xl bg-gray-900/60 border border-gray-800">
              <div className="text-[10px] uppercase text-gray-500">{label}</div>
              <div className={`mt-1 font-mono text-sm ${TONE_TEXT[toneOf(value as number | null)]}`}>
                {formatPct(value as number | null)}
              </div>
            </div>
          ))}
          <div className="p-3 rounded-xl bg-gray-900/60 border border-gray-800">
            <div className="text-[10px] uppercase text-gray-500">Угоди / win</div>
            <div className="mt-1 font-mono text-sm text-gray-100">
              {summary?.trades?.closed ?? '—'} /{' '}
              {summary?.trades?.win_rate == null ? '—' : `${Math.round(summary.trades.win_rate * 100)}%`}
            </div>
          </div>
          <div className="p-3 rounded-xl bg-gray-900/60 border border-gray-800">
            <div className="text-[10px] uppercase text-gray-500">У позиції</div>
            <div className="mt-1 font-mono text-sm text-gray-100">
              {summary?.decisions?.in_position_pct == null ? '—' : `${summary.decisions.in_position_pct}%`}
            </div>
          </div>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-gray-500 text-[10px] uppercase">
            <tr>
              <th className="text-left py-1.5 pr-3">Фолд</th>
              <th className="text-left pr-3">OOS-вікно</th>
              <th className="text-left pr-3">Доходність</th>
              <th className="text-left pr-3">Buy&hold</th>
              <th className="text-left pr-3">Fills</th>
              <th className="text-left">Параметри (обрані на IS)</th>
            </tr>
          </thead>
          <tbody>
            <tr
              className={`border-t border-gray-800 cursor-pointer ${fold == null ? 'bg-blue-600/10' : ''}`}
              onClick={() => go({ fold: undefined })}
            >
              <td className="py-1.5 pr-3 font-mono text-gray-300" colSpan={6}>
                усі фолди
              </td>
            </tr>
            {folds.map((item) => {
              const ret = toNumber(item.oos_return_raw ?? null);
              return (
                <tr
                  key={item.session_id}
                  className={`border-t border-gray-800 cursor-pointer hover:bg-gray-800/30 ${
                    fold === item.index ? 'bg-blue-600/10' : ''
                  }`}
                  onClick={() => go({ fold: item.index })}
                >
                  <td className="py-1.5 pr-3 font-mono text-gray-300">{item.index}</td>
                  <td className="pr-3 font-mono text-gray-400">
                    {formatDateTime(item.window.out_of_sample_start)} →{' '}
                    {formatDateTime(item.window.out_of_sample_end)}
                  </td>
                  <td className={`pr-3 font-mono ${TONE_TEXT[toneOf(ret)]}`}>{formatPct(ret)}</td>
                  <td className="pr-3 font-mono text-gray-400">
                    {formatPct(toNumber(item.buy_and_hold_return_raw ?? null))}
                  </td>
                  <td className="pr-3 font-mono text-gray-400">{item.fills ?? '—'}</td>
                  <td className="font-mono text-[10px] text-gray-500">{item.selected ?? '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex gap-1 bg-[#0d131f] border border-gray-800 p-1 rounded-xl self-start">
        {TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => go({ tab: item.key })}
            className={`px-3 py-1 rounded-lg text-[11px] font-semibold ${
              tab === item.key
                ? 'bg-blue-600/20 text-blue-300 border border-blue-500/30'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === 'trades' && (
        <RunTradesTab
          batchId={batchId}
          cellId={cellId}
          fold={fold}
          instrumentId={cell.instrument_id}
          interval={cell.interval}
          catalog={cell.catalog}
          title={cellId}
        />
      )}
      {tab === 'decisions' &&
        (decisionFold ? (
          <div className="flex flex-col gap-2">
            <span className="text-[11px] text-gray-500">
              Фолд {decisionFold.index} (сесія {decisionFold.session_id}) — оберіть інший у таблиці
              фолдів.
            </span>
            <DecisionLogPanel
              key={decisionFold.session_id}
              sessionId={decisionFold.session_id}
              catalogPath={cell.catalog}
              barInterval={cell.interval}
              instrumentId={cell.instrument_id}
            />
          </div>
        ) : (
          <div className="text-xs text-gray-500">Журналу рішень у цього прогону немає.</div>
        ))}
      {tab === 'analysis' && <RunAnalysisTab batchId={batchId} cellId={cellId} fold={fold} />}
      {tab === 'log' && (
        <pre className="text-[11px] font-mono text-gray-400 bg-gray-950 border border-gray-800 rounded-xl p-3 overflow-x-auto max-h-[32rem]">
          {run.log_tail || 'Лог порожній.'}
        </pre>
      )}
    </div>
  );
};
