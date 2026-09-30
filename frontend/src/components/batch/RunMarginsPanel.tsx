import React, { useEffect, useMemo, useState } from 'react';
import { fetchRunMargins, type MarginBucket } from '../../services/api';
import { extraPasses, histogram } from '../../lib/tradeOverlays';

interface RunMarginsPanelProps {
  batchId: string;
  cellId: string;
  fold?: number;
}

/**
 * "What if this threshold were X% softer?" — per logged condition, from the log alone.
 *
 * Each bar's margin to the threshold is in the decision log, so the count of extra
 * readings a looser threshold would pass is a filter over those numbers, no re-run. It is
 * a pointer to a hypothesis, not a result: whether the extra signals make money is what
 * the next out-of-sample batch (and the trial ledger's DSR) has to show.
 */
export const RunMarginsPanel: React.FC<RunMarginsPanelProps> = ({ batchId, cellId, fold }) => {
  const [margins, setMargins] = useState<Record<string, MarginBucket> | null>(null);
  const [selected, setSelected] = useState<string>('');
  const [softer, setSofter] = useState(5);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setMargins(null);
    fetchRunMargins(batchId, cellId, fold)
      .then((data) => {
        if (!alive) return;
        setMargins(data.margins);
        const first = Object.keys(data.margins)[0];
        setSelected((current) => (current && current in data.margins ? current : (first ?? '')));
      })
      .catch((err: unknown) => alive && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      alive = false;
    };
  }, [batchId, cellId, fold]);

  const bucket = margins && selected ? margins[selected] : undefined;
  const bars = useMemo(() => (bucket ? histogram(bucket.values) : []), [bucket]);
  const peak = Math.max(1, ...bars.map((bar) => bar.count));

  if (error) return <div className="text-xs text-red-400">{error}</div>;
  if (!margins) return <div className="text-xs text-gray-500">Рахую запаси до порогів…</div>;
  if (Object.keys(margins).length === 0) {
    return (
      <div className="text-xs text-gray-500">
        У журналі цього прогону немає запасів до порогів (старий формат логу — перезапустіть
        пакет).
      </div>
    );
  }

  const extra = bucket ? extraPasses(bucket.values, softer) : 0;

  return (
    <section className="flex flex-col gap-3">
      <h4 className="text-xs font-bold text-gray-300">Поріг ±X%: скільки сигналів додалося б</h4>
      <div className="flex flex-wrap items-center gap-3 text-[11px]">
        <select
          className="bg-gray-950 border border-gray-800 rounded-lg px-2 py-1 font-mono text-gray-200"
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
        >
          {Object.entries(margins).map(([name, item]) => (
            <option key={name} value={name}>
              {name} ({item.total})
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-gray-400">
          м’якше на
          <input
            type="range"
            min={0}
            max={50}
            step={1}
            value={softer}
            onChange={(e) => setSofter(Number(e.target.value))}
          />
          <span className="font-mono text-gray-200 w-10">{softer}%</span>
        </label>
      </div>
      {bucket && (
        <>
          <div className="text-[11px] text-gray-300">
            Зараз проходить <span className="font-mono">{bucket.passed}</span> з{' '}
            <span className="font-mono">{bucket.total}</span> оцінок; поріг, м’якший на {softer}%
            ({bucket.unit}), додав би ще{' '}
            <span className="font-mono text-amber-300">{extra}</span>
            {bucket.passed > 0 && (
              <span className="text-gray-500"> (+{Math.round((extra / bucket.passed) * 100)}%)</span>
            )}
            .
          </div>
          <div className="flex items-end gap-px h-24">
            {bars.map((bar) => (
              <div
                key={bar.from}
                title={`${bar.from}…${bar.from + 5}%: ${bar.count}`}
                className={`flex-1 rounded-t ${
                  bar.from >= 0
                    ? 'bg-emerald-600/70'
                    : bar.from >= -softer
                      ? 'bg-amber-500/70'
                      : 'bg-gray-700'
                }`}
                style={{ height: `${Math.max((bar.count / peak) * 100, bar.count ? 3 : 0)}%` }}
              />
            ))}
          </div>
          <div className="flex justify-between text-[10px] font-mono text-gray-500">
            <span>≤ −50%</span>
            <span>0 = поріг</span>
            <span>≥ +50%</span>
          </div>
          <p className="text-[10px] text-gray-500">
            Зелене — оцінки, що пройшли поріг; жовте — ті, що пройшли б при м’якшому порозі.
            Це гіпотеза для наступного OOS-пакета, а не результат: запишіть її в trial ledger
            перед перевіркою.
          </p>
        </>
      )}
    </section>
  );
};
