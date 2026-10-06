import React, { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Eye, Play } from 'lucide-react';
import { launchBatch, type BatchLaunchParams } from '../../services/api';
import { catalogQuery, catalogsQuery, statusQuery } from '../../services/queries';
import { parseVariants, type PlannedCell } from '../../lib/batch';
import {
  mergeOverrides,
  parseOverrideText,
  parseParamRows,
  sweepVariantCount,
} from '../../lib/batchSweep';
import {
  ALL_LAB_SYMBOLS,
  loadStoredBatchForm,
  normalizeSymbol,
  ROBOTS,
  saveStoredBatchForm,
  type StoredBatchForm,
} from '../../lib/batchForm';
import { BatchPlanPreview } from './BatchPlanPreview';
import { BatchMatrixSelectors } from './BatchMatrixSelectors';
import { BatchParamPanel } from './BatchParamPanel';

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
    initial?.robots ?? (ROBOTS as readonly string[]).filter((r) => r !== 'ml_obi'),
  );
  const [symbols, setSymbols] = useState<string[]>(
    initial?.symbols ?? [...ALL_LAB_SYMBOLS],
  );
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
  const [paramValues, setParamValues] = useState<Record<string, string>>(
    initial?.paramValues ?? {},
  );

  // Catalogs available in the workspace
  const catalogsResult = useQuery(catalogsQuery());
  const catalogsData = catalogsResult.data;
  const catalogs = catalogsData?.catalogs;
  const allCatalogSymbols = catalogsData?.all_symbols;

  // Instruments present in the selected catalog
  const catalogQueryRes = useQuery(catalogQuery(catalog));
  const catalogInstruments = catalogQueryRes.data?.instruments;

  const selectedCat = useMemo(
    () => catalogs?.find((c) => c.name === catalog || c.path === catalog),
    [catalogs, catalog],
  );

  // Symbols present specifically in the chosen catalog
  const inCatalogSymbols = useMemo(() => {
    const list: string[] = [];
    if (selectedCat?.symbol_counts) {
      list.push(...Object.keys(selectedCat.symbol_counts));
    }
    if (selectedCat?.symbols) {
      list.push(...selectedCat.symbols.map(normalizeSymbol));
    }
    if (catalogInstruments?.length) {
      list.push(...catalogInstruments.map((i) => normalizeSymbol(i.raw_symbol)));
    }
    return [...new Set(list.filter(Boolean))];
  }, [selectedCat, catalogInstruments]);

  // All available symbols across workspace: lab standard universe + catalog symbols
  const availableSymbols = useMemo(() => {
    const combined = [
      ...ALL_LAB_SYMBOLS,
      ...(allCatalogSymbols?.map(normalizeSymbol) ?? []),
      ...inCatalogSymbols,
    ];
    return [...new Set(combined.filter(Boolean))];
  }, [allCatalogSymbols, inCatalogSymbols]);

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
        paramValues,
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
    paramValues,
  ]);

  // The scenario names and the variant cap come from the backend (`domain/fees.py`,
  // `application/batch_plan.py`), so the form cannot drift from what the batch will accept.
  const status = useQuery(statusQuery(catalog)).data;
  const costProfiles = status?.cost_profiles ?? [];
  const maxVariants = status?.max_variants;
  const [plan, setPlan] = useState<PlannedCell[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * What the two parameter sources say together: the panel's rows and the free-text box.
   *
   * A key named by both with different values is refused here (`lib/batchSweep.ts`) instead
   * of being resolved by guessing — and the key checks that need `Settings` are the server's
   * (`application/batch_plan.py`), which is why a typo comes back as a 422 with a reason.
   * Parsing a handful of lines on each render is cheaper than the state it would take to
   * memoize it, and the React compiler flags a `useMemo` it cannot prove.
   */
  const overrides = mergeOverrides(
    parseParamRows(Object.entries(paramValues).map(([key, values]) => ({ key, values }))),
    parseOverrideText(envText),
  );

  /** The variant box and the sweep box are validated here: a typo would run the wrong matrix. */
  const variantError = parseVariants(variantsText).error ?? overrides.error;

  /** How many variants the whole matrix multiplies by: hypotheses plus sweep combinations. */
  const variantsToRun =
    parseVariants(variantsText).variants.length + sweepVariantCount(overrides.sweep);

  const params = (dryRun: boolean): BatchLaunchParams => {
    const extra = extraSymbols
      .split(/[\s,]+/)
      .map(normalizeSymbol)
      .filter(Boolean);
    const parsed = parseVariants(variantsText);
    return {
      robots,
      symbols: [...new Set([...symbols.map(normalizeSymbol), ...extra])].filter(Boolean),
      interval: barInterval,
      catalog,
      days: typeof days === 'number' && days > 0 ? days : undefined,
      folds,
      is_fraction: String(isFraction),
      embargo_bars: embargoBars,
      parallel,
      label,
      env: overrides.env,
      sweep: overrides.sweep,
      variants: parsed.variants,
      cost_profile: costProfile || undefined,
      dry_run: dryRun,
    };
  };

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

  const input =
    'bg-gray-950 border border-gray-800 rounded-lg px-2 py-1 text-xs font-mono text-gray-200';

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-4">
      <h3 className="text-sm font-bold text-gray-100">Новий пакетний бектест</h3>

      <BatchMatrixSelectors
        robots={robots}
        setRobots={setRobots}
        symbols={symbols}
        setSymbols={setSymbols}
        extraSymbols={extraSymbols}
        setExtraSymbols={setExtraSymbols}
        availableSymbols={availableSymbols}
        inCatalogSymbols={inCatalogSymbols}
        catalog={catalog}
      />

      <div className="flex flex-wrap items-end gap-4">
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
          {catalogs && catalogs.length > 0 ? (
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

      <BatchParamPanel
        robots={robots}
        values={paramValues}
        setValues={setParamValues}
        envText={envText}
        setEnvText={setEnvText}
        variantsText={variantsText}
        setVariantsText={setVariantsText}
        variantCount={variantsToRun}
        maxVariants={maxVariants}
      />

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
      </div>
      {variantError ? (
        <div className="text-xs text-red-400">{variantError}</div>
      ) : (
        variantsToRun > 0 && (
          <p className="text-[11px] text-gray-500">
            Матриця помножиться на {variantsToRun}{' '}
            {variantsToRun === 1 ? 'варіант' : 'варіантів'} · прогін {robots.length} ×{' '}
            {symbols.length + extraSymbols.split(/[\s,]+/).filter(Boolean).length} інструментів.
            Клітинки матимуть ідентифікатори на кшталт{' '}
            <span className="font-mono">
              {robots[0] ?? 'robot'}_{(symbols[0] ?? 'BTCUSDT').replace('USDT', '')}__
              {parseVariants(variantsText).variants[0]?.name ?? 'ENTER_TREND_ER_0_30_01'}
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
