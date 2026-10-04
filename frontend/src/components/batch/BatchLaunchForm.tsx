import React, { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Eye, Play } from 'lucide-react';
import { launchBatch, type BatchLaunchParams } from '../../services/api';
import { catalogQuery, catalogsQuery, statusQuery } from '../../services/queries';
import { parseVariants, type PlannedCell } from '../../lib/batch';
import { loadStoredBatchForm, saveStoredBatchForm, type StoredBatchForm } from '../../lib/batchForm';
import { BatchPlanPreview } from './BatchPlanPreview';

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
const DEFAULT_SYMBOLS = ['BTCUSDT', 'ETHUSDT'];

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
  const initial = useMemo(() => loadStoredBatchForm(), []);

  const [robots, setRobots] = useState<string[]>(
    initial?.robots ?? ROBOTS.filter((r) => r !== 'ml_obi'),
  );
  const [symbols, setSymbols] = useState<string[]>(initial?.symbols ?? DEFAULT_SYMBOLS);
  const [extraSymbols, setExtraSymbols] = useState(initial?.extraSymbols ?? '');
  const [barInterval, setBarInterval] = useState(initial?.barInterval ?? '1h');
  const [catalog, setCatalog] = useState(initial?.catalog ?? 'catalog');
  const [days, setDays] = useState<number | ''>(initial?.days ?? '');
  const [folds, setFolds] = useState(initial?.folds ?? 4);
  const [isFraction, setIsFraction] = useState(initial?.isFraction ?? 0.7);
  const [embargoBars, setEmbargoBars] = useState(initial?.embargoBars ?? 10);
  const [parallel, setParallel] = useState(initial?.parallel ?? 2);
  const [label, setLabel] = useState(initial?.label ?? '');
  const [envText, setEnvText] = useState(initial?.envText ?? '');
  const [variantsText, setVariantsText] = useState(initial?.variantsText ?? '');
  const [costProfile, setCostProfile] = useState(initial?.costProfile ?? '');

  // Catalogs available in the workspace
  const catalogs = useQuery(catalogsQuery()).data?.catalogs ?? [];

  // Instruments present in the selected catalog
  const catalogInstruments = useQuery(catalogQuery(catalog)).data?.instruments ?? [];
  const availableSymbols = useMemo(() => {
    if (!catalogInstruments.length) return DEFAULT_SYMBOLS;
    const raw = catalogInstruments.map((i) => i.raw_symbol).filter(Boolean);
    return [...new Set([...DEFAULT_SYMBOLS, ...raw])];
  }, [catalogInstruments]);

  // Persist form to localStorage
  useEffect(() => {
    try {
      const state: StoredBatchForm = {
        robots,
        symbols,
        extraSymbols,
        barInterval,
        catalog,
        days,
        folds,
        isFraction,
        embargoBars,
        parallel,
        label,
        envText,
        variantsText,
        costProfile,
      };
      saveStoredBatchForm(state);
    } catch {
      // ignore localStorage errors
    }
  }, [
    robots,
    symbols,
    extraSymbols,
    barInterval,
    catalog,
    days,
    folds,
    isFraction,
    embargoBars,
    parallel,
    label,
    envText,
    variantsText,
    costProfile,
  ]);

  // The scenario names come from the backend (`domain/fees.py`), so the form cannot drift
  // from what the engine would actually charge.
  const costProfiles = useQuery(statusQuery(catalog)).data?.cost_profiles ?? [];
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
      is_fraction: String(isFraction),
      embargo_bars: embargoBars,
      parallel,
      label,
      env,
      variants: parsed.variants,
      cost_profile: costProfile || undefined,
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
          <div className="flex flex-wrap gap-1.5 items-center">
            {availableSymbols.map((symbol) => (
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
          {catalogs.length > 0 ? (
            <select
              className={input}
              value={catalog}
              onChange={(e) => setCatalog(e.target.value)}
            >
              {catalogs.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
              {!catalogs.some((c) => c.name === catalog) && (
                <option value={catalog}>{catalog} (власний)</option>
              )}
            </select>
          ) : (
            <input className={`${input} w-32`} value={catalog} onChange={(e) => setCatalog(e.target.value)} />
          )}
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
          IS fraction
          <input
            type="number"
            step="0.05"
            min="0.1"
            max="0.9"
            className={`${input} w-20`}
            value={isFraction}
            onChange={(e) => setIsFraction(Number(e.target.value))}
          />
        </label>
        <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-gray-500">
          Embargo
          <input
            type="number"
            min={0}
            className={`${input} w-16`}
            value={embargoBars}
            onChange={(e) => setEmbargoBars(Number(e.target.value))}
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

      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-gray-500">
          Сценарій витрат
          <select
            className={input}
            value={costProfile}
            onChange={(e) => setCostProfile(e.target.value)}
            title="Комісії, за якими рахується прогін. Назва потрапляє в манифест кожного прогону, тож артефакт каже, за яким тарифом його виміряли"
          >
            <option value="">як у налаштуваннях машини</option>
            {costProfiles.map((profile) => (
              <option key={profile.name} value={profile.name}>
                {profile.name} — спот {profile.spot_taker_bps.toFixed(2)} bps
                {profile.is_default ? ' (типовий)' : ''}
              </option>
            ))}
          </select>
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
      </div>
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

      {plan && <BatchPlanPreview plan={plan} />}
    </div>
  );
};
