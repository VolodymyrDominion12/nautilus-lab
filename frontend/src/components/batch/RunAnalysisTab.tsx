import React, { useEffect, useState } from 'react';
import { Copy } from 'lucide-react';
import { fetchRunDigest, type DecisionDigest } from '../../services/api';
import { outcomeLabel } from '../../lib/trades';
import { RunMarginsPanel } from './RunMarginsPanel';

interface RunAnalysisTabProps {
  batchId: string;
  cellId: string;
  fold?: number;
}

/** Stages of a bar from "closed" to "traded": where the signals are lost, in order. */
const FUNNEL: { label: string; outcomes: string[] | null }[] = [
  { label: 'Бари поза прогрівом', outcomes: null },
  { label: 'Сигнал є (не NO_SIGNAL)', outcomes: ['NO_SIGNAL', 'WARMUP'] },
  { label: 'Не відхилено фільтром робота', outcomes: ['SIGNAL_VETOED'] },
  { label: 'Позиція не та сама (не HOLD)', outcomes: ['HOLD_NOOP', 'PENDING_FILL'] },
  {
    label: 'Ризик пропустив',
    outcomes: ['ENTRY_BLOCKED_RISK', 'ENTRY_SKIPPED_SIZE', 'ENTRY_SKIPPED_PAUSED'],
  },
];

const count = (outcomes: Record<string, number>, keys: string[]): number =>
  keys.reduce((sum, key) => sum + (outcomes[key] ?? 0), 0);

/**
 * Why the run traded the way it did: the bar funnel, what blocked entries, the forward
 * return of executed vs blocked vs vetoed signals, and the near-misses.
 *
 * The forward comparison is the test of a filter: if blocked or vetoed signals would have
 * done as well as executed ones, the filter costs money instead of saving it.
 */
export const RunAnalysisTab: React.FC<RunAnalysisTabProps> = ({ batchId, cellId, fold }) => {
  const [digest, setDigest] = useState<DecisionDigest | null>(null);
  const [markdown, setMarkdown] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setDigest(null);
    fetchRunDigest(batchId, cellId, fold)
      .then((data) => {
        if (!alive) return;
        setDigest(data.digest);
        setMarkdown(data.markdown);
      })
      .catch((err: unknown) => alive && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      alive = false;
    };
  }, [batchId, cellId, fold]);

  if (error) return <div className="text-xs text-red-400">{error}</div>;
  if (!digest) return <div className="text-xs text-gray-500">Рахую дайджест…</div>;

  const outcomes = digest.outcomes;
  const warm = outcomes.WARMUP ?? 0;
  let remaining = digest.bars - warm;
  const funnel = FUNNEL.map((stage) => {
    if (stage.outcomes) remaining -= count(outcomes, stage.outcomes.filter((o) => o !== 'WARMUP'));
    return { label: stage.label, value: Math.max(remaining, 0) };
  });
  const top = funnel[0]?.value || 1;

  const forwardRows = Object.entries(digest.forward ?? {}).filter(([, byH]) =>
    Object.values(byH).some((item) => item.n > 0),
  );
  const horizons = forwardRows.length ? Object.keys(forwardRows[0]?.[1] ?? {}) : [];
  const groupLabel: Record<string, string> = {
    executed: 'виконані',
    blocked: 'заблоковані ризиком',
    vetoed: 'відхилені фільтром',
  };

  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
      <section className="flex flex-col gap-2">
        <h4 className="text-xs font-bold text-gray-300">Воронка барів</h4>
        {funnel.map((stage) => (
          <div key={stage.label} className="flex items-center gap-2 text-[11px]">
            <span className="w-56 text-gray-400">{stage.label}</span>
            <div className="flex-1 h-3 bg-gray-900 rounded">
              <div
                className="h-3 bg-blue-600/70 rounded"
                style={{ width: `${Math.max((stage.value / top) * 100, 0.5)}%` }}
              />
            </div>
            <span className="w-14 text-right font-mono text-gray-300">{stage.value}</span>
          </div>
        ))}
        <p className="text-[10px] text-gray-500">
          Останній рядок — бари, де рішення дійшло до ордера (входи й розвороти) або до виходу.
        </p>
      </section>

      <section className="flex flex-col gap-2">
        <h4 className="text-xs font-bold text-gray-300">Результати барів і блоки</h4>
        <table className="text-[11px] font-mono">
          <tbody>
            {Object.entries(outcomes).map(([outcome, n]) => (
              <tr key={outcome} className="border-t border-gray-800">
                <td className="py-0.5 pr-3 text-gray-400">{outcomeLabel(outcome)}</td>
                <td className="text-gray-500 pr-3">{outcome}</td>
                <td className="text-right text-gray-200">{n}</td>
              </tr>
            ))}
            {Object.entries(digest.blocked_by).map(([code, n]) => (
              <tr key={code} className="border-t border-gray-800">
                <td className="py-0.5 pr-3 text-amber-400">блок</td>
                <td className="text-gray-500 pr-3">{code}</td>
                <td className="text-right text-gray-200">{n}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="flex flex-col gap-2 xl:col-span-2">
        <h4 className="text-xs font-bold text-gray-300">
          Доходність після сигналу (% ціни, зі знаком напрямку)
        </h4>
        {forwardRows.length === 0 ? (
          <p className="text-[11px] text-gray-500">Недостатньо сигналів для порівняння.</p>
        ) : (
          <table className="text-[11px] font-mono">
            <thead className="text-gray-500">
              <tr>
                <th className="text-left pr-3">Група</th>
                {horizons.map((h) => (
                  <th key={h} className="text-right pr-3">
                    {h} бар
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {forwardRows.map(([group, byH]) => (
                <tr key={group} className="border-t border-gray-800">
                  <td className="py-0.5 pr-3 text-gray-300">{groupLabel[group] ?? group}</td>
                  {horizons.map((h) => {
                    const item = byH[h];
                    return (
                      <td key={h} className="text-right pr-3 text-gray-200">
                        {!item || item.n === 0 || item.mean_pct == null
                          ? '—'
                          : `${item.mean_pct >= 0 ? '+' : ''}${item.mean_pct.toFixed(3)}% (n=${item.n}, hit ${Math.round((item.hit_rate ?? 0) * 100)}%)`}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <div className="xl:col-span-2">
        <RunMarginsPanel batchId={batchId} cellId={cellId} fold={fold} />
      </div>

      <section className="flex flex-col gap-2">
        <h4 className="text-xs font-bold text-gray-300">Майже-сигнали: {digest.near_misses}</h4>
        <ul className="text-[11px] font-mono text-gray-400 list-disc pl-4">
          {(digest.near_miss_examples ?? []).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </section>

      <section className="flex flex-col gap-2">
        <h4 className="text-xs font-bold text-gray-300">Режими</h4>
        <div className="text-[11px] font-mono text-gray-400">
          {Object.entries(digest.regime_share_pct)
            .map(([regime, share]) => `${regime || '—'} ${share}%`)
            .join(' · ') || '—'}
        </div>
        <button
          type="button"
          onClick={() => void navigator.clipboard.writeText(markdown)}
          className="self-start flex items-center gap-1.5 px-3 py-1.5 text-xs bg-gray-900 border border-gray-700 rounded-lg text-gray-300"
        >
          <Copy className="w-3.5 h-3.5" /> Копіювати дайджест (для LLM)
        </button>
      </section>
    </div>
  );
};
