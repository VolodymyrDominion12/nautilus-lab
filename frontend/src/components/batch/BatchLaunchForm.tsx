import React, { useState } from 'react';
import { Eye, Play } from 'lucide-react';
import { launchBatch, type BatchLaunchParams } from '../../services/api';
import { parseVariants, type PlannedCell } from '../../lib/batch';

const ROBOTS = [
  'regime',
  'ema',
  'adaptive_ema',
  'vpin_momentum',
  'formulaic_lgbm',
  'meta_label',
  'pairs',
  'funding',
  'ml_obi',
];
const SYMBOLS = ['BTCUSDT', 'ETHUSDT'];

interface BatchLaunchFormProps {
  onStarted: (batchId: string) => void;
}

/**
 * The matrix to run: robots x instruments, walk-forward settings, parallelism.
 *
 * "Preview" asks the API for the plan first (`dry_run`): which cells will run and which
 * cannot, and why (a missing model, a missing perp catalog), before anything starts.
 */
export const BatchLaunchForm: React.FC<BatchLaunchFormProps> = ({ onStarted }) => {
  const [robots, setRobots] = useState<string[]>(ROBOTS.filter((r) => r !== 'ml_obi'));
  const [symbols, setSymbols] = useState<string[]>(SYMBOLS);
  const [extraSymbols, setExtraSymbols] = useState('');
  const [barInterval, setBarInterval] = useState('1h');
  const [catalog, setCatalog] = useState('catalog');
  const [days, setDays] = useState<number | ''>('');
  const [folds, setFolds] = useState(4);
  const [parallel, setParallel] = useState(2);
  const [label, setLabel] = useState('');
  const [envText, setEnvText] = useState('');
  const [variantsText, setVariantsText] = useState('');
  const [plan, setPlan] = useState<PlannedCell[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = (list: string[], item: string, set: (next: string[]) => void) =>
    set(list.includes(item) ? list.filter((x) => x !== item) : [...list, item]);

  const params = (dryRun: boolean): BatchLaunchParams => {
    const extra = extraSymbols
      .split(/[\s,]+/)
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);
    const env: Record<string, string> = {};
    for (const line of envText.split('\n')) {
      const [key, ...rest] = line.split('=');
      if (key && rest.length) env[key.trim()] = rest.join('=').trim();
    }
    const parsed = parseVariants(variantsText);
    return {
      robots,
      symbols: [...new Set([...symbols, ...extra])],
      interval: barInterval,
      catalog,
      days: typeof days === 'number' && days > 0 ? days : undefined,
      folds,
      parallel,
      label,
      env,
      variants: parsed.variants,
      dry_run: dryRun,
    };
  };

  /** The variant box is validated here, not by the API: a typo would run the wrong matrix. */
  const variantError = parseVariants(variantsText).error;

  const submit = async (dryRun: boolean) => {
    if (variantError) {
      setError(variantError);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await launchBatch(params(dryRun));
      setPlan(result.cells);
      if (!dryRun && result.batch_id) onStarted(result.batch_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const chip = (active: boolean) =>
    `px-2.5 py-1 rounded-lg text-[11px] font-mono border transition-colors ${
      active
        ? 'bg-blue-600/20 text-blue-300 border-blue-500/40'
        : 'bg-gray-950 text-gray-500 border-gray-800 hover:text-gray-300'
    }`;
  const input =
    'bg-gray-950 border border-gray-800 rounded-lg px-2 py-1 text-xs font-mono text-gray-200';
  const runnableCount = (plan ?? []).filter((cell) => cell.runnable).length;

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-4">
      <h3 className="text-sm font-bold text-gray-100">Новий пакетний бектест</h3>

      <div className="flex flex-col gap-2">
        <span className="text-[10px] uppercase tracking-wide text-gray-500">Роботи</span>
        <div className="flex flex-wrap gap-1.5">
          {ROBOTS.map((robot) => (
            <button
              key={robot}
              type="button"
              className={chip(robots.includes(robot))}
              onClick={() => toggle(robots, robot, setRobots)}
            >
              {robot}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-2">
          <span className="text-[10px] uppercase tracking-wide text-gray-500">Інструменти</span>
          <div className="flex gap-1.5">
            {SYMBOLS.map((symbol) => (
              <button
                key={symbol}
                type="button"
                className={chip(symbols.includes(symbol))}
                onClick={() => toggle(symbols, symbol, setSymbols)}
              >
                {symbol}
              </button>
            ))}
            <input
              className={`${input} w-40`}
              placeholder="ще: SOLUSDT…"
              value={extraSymbols}
              onChange={(e) => setExtraSymbols(e.target.value)}
            />
          </div>
        </div>
        <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-gray-500">
          Таймфрейм
          <select className={input} value={barInterval} onChange={(e) => setBarInterval(e.target.value)}>
            <option value="1h">1h</option>
            <option value="4h">4h</option>
            <option value="1d">1d</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-gray-500">
          Каталог
          <input className={`${input} w-32`} value={catalog} onChange={(e) => setCatalog(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-gray-500">
          Днів
          <input
            type="number"
            min={1}
            placeholder="всі"
            title="Кількість останніх днів каталогу для бектесту (залиште порожнім для всієї історії)"
            className={`${input} w-20`}
            value={days}
            onChange={(e) => setDays(e.target.value === '' ? '' : Math.max(1, Number(e.target.value)))}
          />
        </label>
        <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-gray-500">
          Фолди
          <input
            type="number"
            min={2}
            max={12}
            className={`${input} w-16`}
            value={folds}
            onChange={(e) => setFolds(Number(e.target.value))}
          />
        </label>
        <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-gray-500">
          Паралельно
          <input
            type="number"
            min={1}
            max={8}
            className={`${input} w-16`}
            value={parallel}
            onChange={(e) => setParallel(Number(e.target.value))}
          />
        </label>
        <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-gray-500">
          Мітка
          <input className={`${input} w-44`} value={label} onChange={(e) => setLabel(e.target.value)} />
        </label>
      </div>

      <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-gray-500">
        Налаштування для всіх прогонів (KEY=value, по рядку)
        <textarea
          className={`${input} h-16`}
          placeholder={'BACKTEST_DAYS=30\nDRAWDOWN_COOLDOWN_DAYS=7\nRISK_PER_TRADE=0.01'}
          value={envText}
          onChange={(e) => setEnvText(e.target.value)}
        />
      </label>

      <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-gray-500">
        Варіанти (гіпотези): [НАЗВА] і KEY=value під нею — кожен прогін виконається для кожного
        варіанта
        <textarea
          className={`${input} h-24 ${variantError ? 'border-red-800' : ''}`}
          placeholder={'[H0]\nREGIME_LEGS=uptrend,downtrend\n\n[H1]\nREGIME_LEGS=uptrend,downtrend\nENTRY_FILTER_HTF_TREND=true'}
          value={variantsText}
          onChange={(e) => setVariantsText(e.target.value)}
        />
      </label>
      {variantError ? (
        <div className="text-xs text-red-400">{variantError}</div>
      ) : (
        parseVariants(variantsText).variants.length > 0 && (
          <p className="text-[11px] text-gray-500">
            Варіантів: {parseVariants(variantsText).variants.length} · прогін{' '}
            {robots.length} × {symbols.length + extraSymbols.split(/[\s,]+/).filter(Boolean).length}{' '}
            інструментів стане в стільки разів більше. Клітинки матимуть ідентифікатори на кшталт{' '}
            <span className="font-mono">
              {robots[0] ?? 'robot'}_{(symbols[0] ?? 'BTCUSDT').replace('USDT', '')}__
              {parseVariants(variantsText).variants[0].name}
            </span>
            .
          </p>
        )
      )}

      <div className="flex gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => void submit(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-gray-950 border border-gray-700 rounded-lg text-gray-300 hover:bg-gray-800"
        >
          <Eye className="w-3.5 h-3.5" /> Попередній план
        </button>
        <button
          type="button"
          disabled={busy || robots.length === 0}
          onClick={() => void submit(false)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-blue-600 hover:bg-blue-500 rounded-lg text-white"
        >
          <Play className="w-3.5 h-3.5" /> Запустити
        </button>
      </div>

      {error && <div className="text-xs text-red-400">{error}</div>}

      {plan && (
        <div className="flex flex-col gap-2">
          <p className="text-[11px] text-gray-500">
            Прогонів до запуску: <span className="text-emerald-400">{runnableCount}</span>, заблоковано:{' '}
            <span className="text-amber-400">{plan.length - runnableCount}</span>. Заблокований прогін
            не стартує — причина вказана в плані (немає серії барів, перп-ноги, серії фандингу чи
            моделі).
          </p>
          <table className="w-full text-[11px] font-mono">
            <thead className="text-gray-500">
              <tr>
                <th className="text-left py-1">Прогін</th>
                <th className="text-left">Інструмент</th>
                <th className="text-left">TF</th>
                <th className="text-left">Каталог</th>
                <th className="text-left">Стан</th>
              </tr>
            </thead>
            <tbody>
              {plan.map((cell) => (
                <tr key={cell.cell_id} className="border-t border-gray-800">
                  <td className="py-1 text-gray-200">{cell.cell_id}</td>
                  <td className="text-gray-400">{cell.instrument_id ?? cell.symbol}</td>
                  <td className="text-gray-400">{cell.interval}</td>
                  <td className="text-gray-400">{cell.catalog}</td>
                  <td className={cell.runnable ? 'text-emerald-400' : 'text-amber-400'}>
                    {cell.runnable ? 'буде запущено' : cell.blocked}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
