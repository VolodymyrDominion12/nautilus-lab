import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  ClipboardCopy,
  ExternalLink,
  FileText,
  Layers,
  Play,
  RefreshCw,
  RotateCcw,
  Settings2,
  Square,
} from 'lucide-react';
import { staticReportUrl } from '../config';
import {
  cancelResearch,
  fetchCatalog,
  fetchResearchLog,
  fetchReports,
  runResearch,
} from '../services/api';
import type {
  CatalogResponse,
  HistoryEntry,
  ReportItem,
  ResearchRunConfig,
  ResearchSummary,
  StrategySpec,
} from '../services/api';
import { WalkForwardBuilder } from './WalkForwardBuilder';
import { ExperimentHistory } from './ExperimentHistory';
import { RunsCompare } from './RunsCompare';
import { VerdictPanel } from './VerdictPanel';
import { FoldBreakdown } from './FoldBreakdown';
import { PboPanel } from './PboPanel';
import { LogPanel } from './LogPanel';
import { formatDateTime } from '../lib/format';
import { preflight, preflightBlocking } from '../lib/research';
import type { PreflightIssue } from '../lib/research';

interface ResearchLabProps {
  strategies: StrategySpec[];
  initialRobot?: string;
  selectedCatalogPath?: string;
}

interface PersistedForm {
  robot?: string;
  source?: 'catalog' | 'synthetic';
  bars?: number;
  folds?: number;
  isFraction?: number;
  embargoBars?: number;
  useOptuna?: boolean;
  optunaTrials?: number;
  usePbo?: boolean;
  pboBlocks?: number;
  barVpin?: boolean;
  stressSlice?: string;
  generateTearsheet?: boolean;
  journal?: boolean;
  notify?: boolean;
  fullSample?: boolean;
  windowMode?: 'fraction' | 'custom';
  isStart?: string;
  isEnd?: string;
  oosStart?: string;
  oosEnd?: string;
  overrideParams?: boolean;
  paramOverrides?: Record<string, string>;
  instrumentId?: string;
}

const FORM_STORAGE_KEY = 'nautilus-lab:research-form:v2';

const loadPersistedForm = (): PersistedForm => {
  try {
    const raw = window.localStorage.getItem(FORM_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as PersistedForm) : {};
  } catch {
    return {};
  }
};

/** Poll the log only while a run is in flight; a finished run never re-polls. */
export const ResearchLab: React.FC<ResearchLabProps> = ({
  strategies,
  initialRobot = 'regime',
  selectedCatalogPath,
}) => {
  const persisted = useMemo(loadPersistedForm, []);

  const [robot, setRobot] = useState(persisted.robot ?? initialRobot);
  const [source, setSource] = useState<'catalog' | 'synthetic'>(persisted.source ?? 'catalog');
  const [bars, setBars] = useState(persisted.bars ?? 3000);
  const [folds, setFolds] = useState(persisted.folds ?? 2);
  const [isFraction, setIsFraction] = useState(persisted.isFraction ?? 0.7);
  const [embargoBars, setEmbargoBars] = useState(persisted.embargoBars ?? 10);
  const [useOptuna, setUseOptuna] = useState(persisted.useOptuna ?? false);
  const [optunaTrials, setOptunaTrials] = useState(persisted.optunaTrials ?? 20);
  const [usePbo, setUsePbo] = useState(persisted.usePbo ?? false);
  const [pboBlocks, setPboBlocks] = useState(persisted.pboBlocks ?? 8);
  const [barVpin, setBarVpin] = useState(persisted.barVpin ?? false);
  const [stressSlice, setStressSlice] = useState(persisted.stressSlice ?? '');
  const [generateTearsheet, setGenerateTearsheet] = useState(persisted.generateTearsheet ?? true);
  const [journal, setJournal] = useState(persisted.journal ?? false);
  const [notify, setNotify] = useState(persisted.notify ?? false);
  const [fullSample, setFullSample] = useState(persisted.fullSample ?? false);
  const [windowMode, setWindowMode] = useState<'fraction' | 'custom'>(
    persisted.windowMode ?? 'fraction',
  );
  const [isStart, setIsStart] = useState(persisted.isStart ?? '');
  const [isEnd, setIsEnd] = useState(persisted.isEnd ?? '');
  const [oosStart, setOosStart] = useState(persisted.oosStart ?? '');
  const [oosEnd, setOosEnd] = useState(persisted.oosEnd ?? '');
  const [overrideParams, setOverrideParams] = useState(persisted.overrideParams ?? false);
  const [paramOverrides, setParamOverrides] = useState<Record<string, string>>(
    persisted.paramOverrides ?? {},
  );
  const [instrumentId, setInstrumentId] = useState(persisted.instrumentId ?? '');

  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [historyKey, setHistoryKey] = useState(0);

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState('');
  const [summary, setSummary] = useState<ResearchSummary | null>(null);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [launchedAtIso, setLaunchedAtIso] = useState<string | null>(null);
  const [staleNotice, setStaleNotice] = useState<string | null>(null);
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [selectedTearsheetUrl, setSelectedTearsheetUrl] = useState<string | null>(null);
  const [copiedCli, setCopiedCli] = useState(false);

  // Wall-clock marker of the launch, used to tell this run's result from a previous one.
  const launchRef = useRef<{ startedAtMs: number; sawRunning: boolean; polls: number } | null>(null);

  const catalogInstruments = catalog?.instruments ?? [];
  const selectedInstrument =
    catalogInstruments.find((item) => item.instrument_id === instrumentId) ??
    catalogInstruments[0] ??
    null;

  // Persist the form so a reload does not silently reset research conditions.
  useEffect(() => {
    const payload: PersistedForm = {
      robot,
      source,
      bars,
      folds,
      isFraction,
      embargoBars,
      useOptuna,
      optunaTrials,
      usePbo,
      pboBlocks,
      barVpin,
      stressSlice,
      generateTearsheet,
      journal,
      notify,
      fullSample,
      windowMode,
      isStart,
      isEnd,
      oosStart,
      oosEnd,
      overrideParams,
      paramOverrides,
      instrumentId,
    };
    try {
      window.localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(payload));
    } catch {
      // storage disabled: losing form memory is acceptable, losing the run is not
    }
  }, [
    robot,
    source,
    bars,
    folds,
    isFraction,
    embargoBars,
    useOptuna,
    optunaTrials,
    usePbo,
    pboBlocks,
    barVpin,
    stressSlice,
    generateTearsheet,
    journal,
    notify,
    fullSample,
    windowMode,
    isStart,
    isEnd,
    oosStart,
    oosEnd,
    overrideParams,
    paramOverrides,
    instrumentId,
  ]);

  const loadReports = async () => {
    try {
      const data = await fetchReports();
      setReports(data.reports);
      setSelectedTearsheetUrl((current) => current ?? data.reports[0]?.url ?? null);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    loadReports();
  }, []);

  useEffect(() => {
    setRobot(initialRobot);
  }, [initialRobot]);

  useEffect(() => {
    fetchCatalog(selectedCatalogPath)
      .then((data) => {
        setCatalog(data);
        setCatalogError(data.error ?? null);
      })
      .catch((err) =>
        setCatalogError(err instanceof Error ? err.message : 'Failed to load the catalog'),
      );
  }, [selectedCatalogPath]);

  // Keep the instrument selection valid when the catalog changes.
  useEffect(() => {
    if (catalogInstruments.length === 0) return;
    if (!catalogInstruments.some((item) => item.instrument_id === instrumentId)) {
      setInstrumentId(catalogInstruments[0].instrument_id);
    }
  }, [catalogInstruments, instrumentId]);

  const selectedStrategyInfo = strategies.find((s) => s.name === robot);

  // Seed override inputs from the spec defaults the first time the toggle is used.
  useEffect(() => {
    const spec = strategies.find((s) => s.name === robot);
    if (!spec?.params?.length) return;
    setParamOverrides((prev) => {
      if (Object.keys(prev).length > 0) return prev;
      const defaults: Record<string, string> = {};
      for (const param of spec.params) {
        if (param.env && param.default != null && param.default !== '') {
          defaults[param.env] = String(param.default);
        }
      }
      return defaults;
    });
  }, [robot, strategies]);

  const issues: PreflightIssue[] = useMemo(
    () =>
      preflight({
        robot,
        spec: selectedStrategyInfo,
        source,
        totalBars: selectedInstrument?.bars_count ?? null,
        syntheticBars: bars,
        folds,
        isFraction,
        embargoBars,
        fullSample,
        useOptuna,
        pbo: usePbo,
        windowMode,
        isStart,
        isEnd,
        oosStart,
        oosEnd,
        instrument: selectedInstrument,
        catalogInstruments: catalogInstruments.length,
      }),
    [
      robot,
      selectedStrategyInfo,
      source,
      selectedInstrument,
      bars,
      folds,
      isFraction,
      embargoBars,
      fullSample,
      useOptuna,
      usePbo,
      windowMode,
      isStart,
      isEnd,
      oosStart,
      oosEnd,
      catalogInstruments.length,
    ],
  );
  const blocked = preflightBlocking(issues);

  const stopPolling = () => {
    launchRef.current = null;
    setRunning(false);
    loadReports();
    setHistoryKey((value) => value + 1);
  };

  useEffect(() => {
    if (!running) return;
    let cancelled = false;
    const interval = setInterval(async () => {
      try {
        const res = await fetchResearchLog();
        if (cancelled) return;
        setLog(res.log);
        setSummary(res.summary);
        if (res.summary.tearsheet_url) setSelectedTearsheetUrl(res.summary.tearsheet_url);

        const launch = launchRef.current;
        if (launch) {
          launch.polls += 1;
          if (res.is_running) launch.sawRunning = true;
        }

        if (!res.is_running && res.summary.is_finished) {
          const finishedMs = res.summary.finished_at ? Date.parse(res.summary.finished_at) : null;
          const launchMs = launch?.startedAtMs ?? 0;
          if (finishedMs != null && finishedMs >= launchMs - 2000) {
            setStaleNotice(null);
          } else {
            // The job never wrote its own result; what is on screen belongs to an older run.
            setStaleNotice(
              'The numbers below are from a previous run: this job ended without writing a result. Check the log.',
            );
          }
          stopPolling();
          return;
        }

        // The process died before writing last_run.json. Without this the UI would say
        // "Simulating..." forever because polling only stops on a finished result.
        if (launch && !res.is_running && launch.sawRunning && launch.polls > 2) {
          setStaleNotice(
            'The research process stopped without writing a result. The log above has the reason.',
          );
          stopPolling();
        }
      } catch (err) {
        if (!cancelled) console.error(err);
      }
    }, 1000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [running]);

  const handleRun = async () => {
    setLaunchError(null);
    setStaleNotice(null);
    try {
      const response = await runResearch({
        robot,
        source,
        bars: source === 'synthetic' ? bars : undefined,
        folds,
        is_fraction: isFraction,
        embargo_bars: embargoBars,
        use_optuna: useOptuna,
        optuna_trials: useOptuna ? optunaTrials : undefined,
        pbo: usePbo,
        pbo_blocks: usePbo ? pboBlocks : undefined,
        bar_vpin: barVpin,
        stress_slice: stressSlice || undefined,
        generate_tearsheet: generateTearsheet,
        journal,
        notify,
        full_sample: source === 'catalog' ? fullSample : false,
        instrument_id: source === 'catalog' ? selectedInstrument?.instrument_id : undefined,
        is_start: windowMode === 'custom' ? isStart || undefined : undefined,
        is_end: windowMode === 'custom' ? isEnd || undefined : undefined,
        oos_start: windowMode === 'custom' ? oosStart || undefined : undefined,
        oos_end: windowMode === 'custom' ? oosEnd || undefined : undefined,
        param_overrides: overrideParams ? paramOverrides : {},
        catalog_path: selectedCatalogPath || undefined,
      });

      if (response.status !== 'started') {
        // HTTP 200 with status "error" — the old UI ignored this and spun forever.
        setLaunchError(response.message ?? 'The run was refused by the API.');
        setRunning(false);
        return;
      }

      launchRef.current = { startedAtMs: Date.now(), sawRunning: false, polls: 0 };
      setLaunchedAtIso(new Date().toISOString());
      setRunning(true);
      setLog(`Starting research for ${robot} (${source} mode)...\n`);
    } catch (err) {
      setRunning(false);
      setLaunchError(err instanceof Error ? err.message : 'Failed to start research');
    }
  };

  const handleCancel = async () => {
    try {
      const response = await cancelResearch();
      setLog((prev) => `${prev}\nCancellation requested: ${response.message ?? response.status}\n`);
    } catch (err) {
      setLog((prev) => `${prev}\nCancel failed: ${err instanceof Error ? err.message : err}\n`);
    }
  };

  const handleLoadHistory = (entry: HistoryEntry) => {
    const config: ResearchRunConfig | undefined = entry.config;
    if (!config) return;
    if (config.config_version !== 2) {
      setLaunchError(
        'This archived run predates full config capture, so only its basic fields can be restored.',
      );
    } else {
      setLaunchError(null);
    }
    if (config.robot) setRobot(config.robot);
    if (config.source === 'catalog' || config.source === 'synthetic') setSource(config.source);
    if (typeof config.bars === 'number') setBars(config.bars);
    if (typeof config.folds === 'number') setFolds(config.folds);
    if (config.is_fraction) setIsFraction(Number(config.is_fraction));
    if (typeof config.embargo_bars === 'number') setEmbargoBars(config.embargo_bars);
    if (typeof config.use_optuna === 'boolean') setUseOptuna(config.use_optuna);
    if (typeof config.optuna_trials === 'number') setOptunaTrials(config.optuna_trials);
    if (typeof config.pbo === 'boolean') setUsePbo(config.pbo);
    if (typeof config.pbo_blocks === 'number') setPboBlocks(config.pbo_blocks);
    if (typeof config.bar_vpin === 'boolean') setBarVpin(config.bar_vpin);
    if (typeof config.stress_slice === 'string') setStressSlice(config.stress_slice);
    if (typeof config.generate_tearsheet === 'boolean') setGenerateTearsheet(config.generate_tearsheet);
    if (typeof config.journal === 'boolean') setJournal(config.journal);
    if (typeof config.notify === 'boolean') setNotify(config.notify);
    if (typeof config.full_sample === 'boolean') setFullSample(config.full_sample);
    if (config.instrument_id) setInstrumentId(config.instrument_id);
    if (config.is_start) {
      setWindowMode('custom');
      setIsStart(config.is_start);
      setIsEnd(config.is_end ?? '');
      setOosStart(config.oos_start ?? '');
      setOosEnd(config.oos_end ?? '');
    } else {
      setWindowMode('fraction');
    }
    if (config.param_overrides && Object.keys(config.param_overrides).length > 0) {
      setOverrideParams(true);
      setParamOverrides(config.param_overrides);
    } else {
      setOverrideParams(false);
    }
  };

  const handleResetForm = () => {
    try {
      window.localStorage.removeItem(FORM_STORAGE_KEY);
    } catch {
      // ignore: the form still resets in memory
    }
    setFolds(2);
    setIsFraction(0.7);
    setEmbargoBars(10);
    setParamOverrides({});
    setOverrideParams(false);
  };

  const onRunKeyDown = (event: React.KeyboardEvent) => {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && !running && !blocked) {
      event.preventDefault();
      handleRun();
    }
  };

  // The banner must describe the result on screen, not the toggle that is currently set:
  // switching back to "catalog" used to hide the warning while synthetic numbers stayed.
  const displayedSource = summary?.source ?? null;
  const syntheticResultOnScreen = displayedSource === 'synthetic';
  const errors = issues.filter((issue) => issue.level === 'error');
  const warnings = issues.filter((issue) => issue.level === 'warning');

  return (
    <div className="flex flex-col gap-6" onKeyDown={onRunKeyDown}>
      {(syntheticResultOnScreen || source === 'synthetic') && (
        <div className="p-3 bg-amber-950/40 border border-amber-800/60 rounded-xl flex items-center gap-3 text-amber-300 text-xs font-medium">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span>
            {syntheticResultOnScreen
              ? 'The result below came from synthetic bars — a smoke test of the plumbing, never evidence of an edge.'
              : 'Synthetic bars are for smoke tests only and can produce absurd returns. Real research needs the Parquet catalog with walk-forward folds.'}
          </span>
        </div>
      )}

      {source === 'catalog' && fullSample && (
        <div className="p-3 bg-amber-950/40 border border-amber-800/60 rounded-xl flex items-center gap-3 text-amber-300 text-xs font-medium">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span>
            Full-sample runs use the whole series with no split, so the numbers are in-sample only.
            They are not an out-of-sample report.
          </span>
        </div>
      )}

      {catalogError && (
        <div className="p-3 bg-red-950/40 border border-red-800/60 rounded-xl flex items-center gap-3 text-red-300 text-xs">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span>Catalog error: {catalogError}</span>
        </div>
      )}

      {launchError && (
        <div className="p-3 bg-red-950/40 border border-red-800/60 rounded-xl flex items-center justify-between gap-3 text-red-300 text-xs">
          <span className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            {launchError}
          </span>
          <button type="button" onClick={() => setLaunchError(null)} className="text-red-400/70 hover:text-red-300">
            dismiss
          </button>
        </div>
      )}

      {staleNotice && (
        <div className="p-3 bg-amber-950/40 border border-amber-800/60 rounded-xl flex items-center gap-3 text-amber-300 text-xs">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span>{staleNotice}</span>
        </div>
      )}

      {source === 'catalog' && !fullSample && !usePbo && (
        <WalkForwardBuilder
          mode={windowMode}
          onModeChange={setWindowMode}
          isFraction={isFraction}
          embargoBars={embargoBars}
          folds={folds}
          isStart={isStart}
          isEnd={isEnd}
          oosStart={oosStart}
          oosEnd={oosEnd}
          onIsStartChange={setIsStart}
          onIsEndChange={setIsEnd}
          onOosStartChange={setOosStart}
          onOosEndChange={setOosEnd}
          catalogFirstDate={selectedInstrument?.first_date}
          catalogLastDate={selectedInstrument?.last_date}
          catalogBarsCount={selectedInstrument?.bars_count}
          instrumentId={selectedInstrument?.instrument_id}
          catalogPath={selectedCatalogPath}
          barInterval={catalog?.bar_interval}
        />
      )}

      <div className="bg-gray-900 border border-gray-800 p-6 rounded-2xl flex flex-col gap-5">
        <div className="flex flex-col md:flex-row md:items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-bold text-gray-100 flex items-center gap-2">
              <Layers className="w-5 h-5 text-blue-400" />
              Research Lab
            </h2>
            <p className="text-xs text-gray-400 mt-1">
              Parameters are chosen on the in-sample window only; the out-of-sample run is the
              result. Press ⌘/Ctrl + Enter to run.
            </p>
          </div>

          <div className="flex items-center gap-2 bg-gray-950 p-1 border border-gray-800 rounded-xl">
            <button
              type="button"
              onClick={() => setSource('catalog')}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                source === 'catalog' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Parquet Catalog (real)
            </button>
            <button
              type="button"
              onClick={() => setSource('synthetic')}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                source === 'synthetic' ? 'bg-amber-600 text-white' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Synthetic (smoke)
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-4 items-end">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-gray-300">Robot</label>
            <select
              value={robot}
              onChange={(e) => setRobot(e.target.value)}
              className="bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 focus:border-blue-500 focus:outline-none"
            >
              {strategies.map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name} {s.wired_in_backtest ? '✓' : '(fail-closed)'}
                </option>
              ))}
            </select>
          </div>

          {source === 'catalog' ? (
            <div className="flex flex-col gap-1.5 xl:col-span-2">
              <label className="text-xs font-medium text-gray-300">
                Instrument {catalogInstruments.length > 1 && `(${catalogInstruments.length} in catalog)`}
              </label>
              {catalogInstruments.length === 0 ? (
                // A disabled select with a single "no instruments" option is a dead control:
                // it opens nothing and explains nothing. Say what to do instead.
                <div className="bg-amber-950/30 border border-amber-800/50 text-amber-300 text-xs rounded-xl p-2.5 flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                  <span>
                    This catalog has no instruments, so there is nothing to backtest. Open{' '}
                    <span className="font-mono">Parquet Catalog</span> and run an ingest
                    {catalogError ? ` (catalog error: ${catalogError})` : ''}.
                  </span>
                </div>
              ) : (
                <select
                  value={selectedInstrument?.instrument_id ?? ''}
                  onChange={(e) => setInstrumentId(e.target.value)}
                  className="bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 font-mono focus:border-blue-500 focus:outline-none"
                >
                  {catalogInstruments.map((item) => (
                    <option key={item.instrument_id} value={item.instrument_id}>
                      {item.raw_symbol} · {item.bars_count.toLocaleString()} bars ·{' '}
                      {item.first_date?.slice(0, 10) ?? '?'} → {item.last_date?.slice(0, 10) ?? '?'}
                    </option>
                  ))}
                </select>
              )}
            </div>
          ) : (
            <div className="flex flex-col gap-1.5 xl:col-span-2">
              <label className="text-xs font-medium text-gray-300">Synthetic bars</label>
              <input
                type="number"
                value={bars}
                onChange={(e) => setBars(Number(e.target.value))}
                className="bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 focus:border-blue-500 focus:outline-none font-mono"
              />
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-gray-300">Fold{source === 'catalog' && `s`}</label>
            <select
              value={folds}
              onChange={(e) => setFolds(Number(e.target.value))}
              className="bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 focus:border-blue-500 focus:outline-none font-mono"
            >
              <option value={1}>
                {source === 'catalog' ? '1 (single split, no baseline)' : '1 (single backtest)'}
              </option>
              <option value={2}>2 (multi-window, recommended)</option>
              <option value={4}>4 (quarterly windows)</option>
              <option value={8}>8 (deep stress)</option>
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-gray-300">
              IS fraction ({(isFraction * 100).toFixed(0)}% / {((1 - isFraction) * 100).toFixed(0)}%)
            </label>
            <input
              type="number"
              step="0.05"
              min="0.4"
              max="0.9"
              value={isFraction}
              onChange={(e) => setIsFraction(Number(e.target.value))}
              disabled={windowMode === 'custom'}
              className="bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 focus:border-blue-500 focus:outline-none font-mono disabled:text-gray-600"
            />
          </div>
        </div>

        {(errors.length > 0 || warnings.length > 0) && (
          <div className="flex flex-col gap-1.5 border-t border-gray-800/80 pt-4">
            {errors.map((issue) => (
              <div key={issue.message} className="flex items-start gap-2 text-[11px] text-red-400">
                <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                <span>{issue.message}</span>
              </div>
            ))}
            {warnings.map((issue) => (
              <div key={issue.message} className="flex items-start gap-2 text-[11px] text-amber-400/90">
                <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                <span>{issue.message}</span>
              </div>
            ))}
          </div>
        )}

        <div className="flex flex-col md:flex-row gap-3 md:items-center flex-wrap">
          <button
            type="button"
            onClick={handleRun}
            disabled={running || blocked}
            title={blocked ? 'Fix the blocking issues above first' : 'Run research (⌘/Ctrl + Enter)'}
            className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-800 disabled:text-gray-500 text-white font-medium rounded-xl transition-colors flex items-center justify-center gap-2"
          >
            {running ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            {running ? 'Simulating…' : blocked ? 'Run blocked' : 'Run research'}
            {!running && !blocked && (
              <kbd className="ml-1 text-[10px] font-mono bg-blue-800/70 px-1.5 py-0.5 rounded border border-blue-700/60 leading-tight">
                ⌘↵
              </kbd>
            )}
          </button>

          {running && (
            <button
              type="button"
              onClick={handleCancel}
              className="px-4 py-2.5 bg-red-950/60 hover:bg-red-900/60 text-red-300 border border-red-800/60 text-sm font-medium rounded-xl transition-colors flex items-center justify-center gap-2"
            >
              <Square className="w-3.5 h-3.5" />
              Cancel
            </button>
          )}

          <button
            type="button"
            onClick={handleResetForm}
            className="px-3 py-2.5 text-xs text-gray-400 hover:text-gray-200 border border-gray-800 rounded-xl flex items-center gap-1.5"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Reset form
          </button>

          {/* Copy CLI command — lets the user reproduce the run from the terminal */}
          <button
            type="button"
            onClick={() => {
              const parts = ['uv run lab research', `--robot ${robot}`];
              if (source === 'synthetic') {
                parts.push(`--synthetic --bars ${bars}`);
              } else {
                if (instrumentId) parts.push(`--instrument ${instrumentId}`);
              }
              if (folds > 1) parts.push(`--folds ${folds}`);
              if (isFraction !== 0.7) parts.push(`--is-fraction ${isFraction}`);
              if (embargoBars !== 10) parts.push(`--embargo-bars ${embargoBars}`);
              if (useOptuna) parts.push(`--optuna --trials ${optunaTrials}`);
              if (usePbo) parts.push('--pbo');
              if (barVpin) parts.push('--bar-vpin');
              if (stressSlice) parts.push(`--stress-slice ${stressSlice}`);
              if (generateTearsheet) parts.push('--tearsheet reports/tearsheet.html');
              if (journal) parts.push('--journal');
              if (fullSample) parts.push('--full-sample');
              navigator.clipboard.writeText(parts.join(' ')).then(() => {
                setCopiedCli(true);
                setTimeout(() => setCopiedCli(false), 2000);
              });
            }}
            className="px-3 py-2.5 text-xs text-gray-400 hover:text-gray-200 border border-gray-800 rounded-xl flex items-center gap-1.5 transition-colors"
            title="Copy equivalent CLI command to clipboard"
          >
            <ClipboardCopy className="w-3.5 h-3.5" />
            {copiedCli ? 'Copied!' : 'Copy CLI'}
          </button>

          {running && launchedAtIso && (
            <span className="text-[11px] text-gray-500 font-mono">
              started {formatDateTime(launchedAtIso)}
            </span>
          )}
        </div>

        {selectedStrategyInfo && (
          <div className="text-xs bg-gray-950/60 p-3 rounded-xl border border-gray-800/80 flex flex-col md:flex-row md:items-center justify-between gap-2 text-gray-400">
            <div>
              <span className="text-gray-300 font-semibold">{selectedStrategyInfo.name}</span>:{' '}
              {selectedStrategyInfo.summary}
              <span className="block text-[10px] text-gray-600 font-mono mt-1">
                min bars {selectedStrategyInfo.minimum_bars} · grid{' '}
                {selectedStrategyInfo.grid_source ?? 'n/a'} · status {selectedStrategyInfo.status}
              </span>
            </div>
            <span
              className={`px-2 py-0.5 rounded text-[11px] font-mono self-start ${
                selectedStrategyInfo.wired_in_backtest
                  ? 'bg-emerald-950/80 text-emerald-400 border border-emerald-800/50'
                  : 'bg-red-950/80 text-red-400 border border-red-800/50'
              }`}
            >
              {selectedStrategyInfo.wired_in_backtest ? 'Wired to engine' : 'Fail-closed block'}
            </span>
          </div>
        )}

        <div className="border-t border-gray-800/80 pt-4">
          <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
            <input
              type="checkbox"
              checked={overrideParams}
              onChange={(e) => setOverrideParams(e.target.checked)}
              className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
            />
            Override robot parameters for this run
          </label>
          <p className="text-[10px] text-gray-500 mt-1 ml-6">
            {overrideParams
              ? 'These values replace the saved .env settings for this run only.'
              : 'Off: the run uses the values from the Settings tab (.env).'}
          </p>

          {overrideParams && selectedStrategyInfo && selectedStrategyInfo.params?.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
              {selectedStrategyInfo.params
                .filter((param) => param.env)
                .slice(0, 12)
                .map((param) => (
                  <label key={param.env} className="flex flex-col gap-1 text-[11px]">
                    <span className="font-mono text-gray-500">
                      {param.env} <span className="text-gray-600">default {String(param.default)}</span>
                    </span>
                    <input
                      type="text"
                      value={paramOverrides[param.env] ?? ''}
                      onChange={(e) =>
                        setParamOverrides((prev) => ({ ...prev, [param.env]: e.target.value }))
                      }
                      className="bg-gray-950 border border-gray-800 rounded-lg p-2 font-mono text-gray-200"
                    />
                  </label>
                ))}
            </div>
          )}
        </div>

        <div>
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1 font-medium"
          >
            {showAdvanced ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            {showAdvanced ? 'Hide advanced gates' : 'Show advanced gates (Optuna, PBO, embargo, VPIN, journal)'}
          </button>

          {showAdvanced && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-4 mt-2 border-t border-gray-800/80">
              <div className="flex flex-col gap-2">
                <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
                  <input
                    type="checkbox"
                    checked={useOptuna}
                    onChange={(e) => setUseOptuna(e.target.checked)}
                    className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
                  />
                  Bayesian selection (Optuna TPE)
                </label>
                {useOptuna && (
                  <div className="flex items-center gap-2 pl-5">
                    <span className="text-[11px] text-gray-400">Trials:</span>
                    <input
                      type="number"
                      value={optunaTrials}
                      onChange={(e) => setOptunaTrials(Number(e.target.value))}
                      className="w-20 bg-gray-950 border border-gray-800 text-xs rounded p-1 font-mono"
                    />
                  </div>
                )}
                {useOptuna && fullSample && (
                  <span className="text-[10px] text-red-400 pl-5">
                    Cannot be combined with full-sample.
                  </span>
                )}
              </div>

              <div className="flex flex-col gap-2">
                <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
                  <input
                    type="checkbox"
                    checked={usePbo}
                    onChange={(e) => setUsePbo(e.target.checked)}
                    className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
                  />
                  Overfitting audit (PBO / CSCV)
                </label>
                {usePbo && (
                  <div className="flex items-center gap-2 pl-5">
                    <span className="text-[11px] text-gray-400">Blocks:</span>
                    <input
                      type="number"
                      value={pboBlocks}
                      onChange={(e) => setPboBlocks(Number(e.target.value))}
                      className="w-20 bg-gray-950 border border-gray-800 text-xs rounded p-1 font-mono"
                    />
                  </div>
                )}
                {usePbo && (
                  <span className="text-[10px] text-gray-500 pl-5">
                    Simulates blocks × configurations runs; no tearsheet, no single PnL verdict.
                  </span>
                )}
              </div>

              <div className="flex flex-col gap-1">
                <span className="text-[11px] text-gray-400">Purged embargo bars</span>
                <input
                  type="number"
                  value={embargoBars}
                  onChange={(e) => setEmbargoBars(Number(e.target.value))}
                  className="bg-gray-950 border border-gray-800 text-xs text-gray-200 rounded-lg p-1.5 font-mono"
                />
                <span className="text-[10px] text-gray-600">
                  A gap between the legs so overlapping bars cannot leak forward.
                </span>
              </div>

              <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
                <input
                  type="checkbox"
                  checked={barVpin}
                  onChange={(e) => setBarVpin(e.target.checked)}
                  className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
                />
                Bar-level VPIN regime filter
              </label>

              <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
                <input
                  type="checkbox"
                  checked={generateTearsheet}
                  onChange={(e) => setGenerateTearsheet(e.target.checked)}
                  disabled={usePbo}
                  className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0 disabled:opacity-50"
                />
                Generate HTML tearsheet {usePbo && '(not available for PBO)'}
              </label>

              <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
                <input
                  type="checkbox"
                  checked={journal}
                  onChange={(e) => setJournal(e.target.checked)}
                  className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
                />
                Append a row to research/journal.md
              </label>

              <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
                <input
                  type="checkbox"
                  checked={notify}
                  onChange={(e) => setNotify(e.target.checked)}
                  className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
                />
                Notify on completion (Telegram / webhook)
              </label>

              {source === 'catalog' && (
                <label className="flex items-center gap-2 cursor-pointer text-xs text-amber-300">
                  <input
                    type="checkbox"
                    checked={fullSample}
                    onChange={(e) => setFullSample(e.target.checked)}
                    className="rounded bg-gray-950 border-gray-700 text-amber-500 focus:ring-0"
                  />
                  Full-sample (in-sample only, no split)
                </label>
              )}

              <div className="flex flex-col gap-1">
                <span className="text-[11px] text-gray-400">Stress slice</span>
                <select
                  value={stressSlice}
                  onChange={(e) => setStressSlice(e.target.value)}
                  className="bg-gray-950 border border-gray-800 text-xs text-gray-300 rounded-lg p-1.5"
                >
                  <option value="">Full range (no slice)</option>
                  <option value="covid2020">covid2020 (March 2020 crash)</option>
                  <option value="ftx2022">ftx2022 (Nov 2022 liquidity crisis)</option>
                  <option value="etf2024">etf2024 (Jan 2024 ETF launch)</option>
                </select>
                <span className="text-[10px] text-gray-600">
                  Slices only exist inside the catalog&apos;s own date range.
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      {summary?.is_error && summary.error_message && (
        <div className="p-3 bg-red-950/40 border border-red-800/60 rounded-xl text-red-300 text-xs font-mono">
          {summary.error_message}
        </div>
      )}

      <VerdictPanel summary={summary} />

      {summary?.multi_window && (summary.multi_window.folds?.length ?? 0) > 0 && (
        <FoldBreakdown
          folds={summary.multi_window.folds}
          foldCount={summary.multi_window.fold_count ?? summary.multi_window.folds.length}
        />
      )}

      {summary?.pbo && <PboPanel pbo={summary.pbo} />}

      {summary?.is_finished && !summary.is_error && (
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-4 flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <Settings2 className="w-4 h-4 text-gray-400" />
            <h3 className="text-xs font-bold text-gray-100">Conditions of this run</h3>
            <span className="text-[10px] text-gray-500">
              archived in reports/history, restorable from the history panel
            </span>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] font-mono text-gray-400">
            <span>run: {summary.run_type}</span>
            <span>source: {summary.source ?? 'n/a'}</span>
            {summary.config?.folds != null && <span>folds: {summary.config.folds}</span>}
            {summary.config?.is_fraction && <span>is_fraction: {summary.config.is_fraction}</span>}
            {summary.config?.embargo_bars != null && (
              <span>embargo: {summary.config.embargo_bars}</span>
            )}
            <span>optuna: {String(summary.config?.use_optuna ?? false)}</span>
            <span>pbo: {String(summary.config?.pbo ?? false)}</span>
            <span>vpin: {String(summary.config?.bar_vpin ?? false)}</span>
            {summary.config?.stress_slice && <span>slice: {summary.config.stress_slice}</span>}
            {summary.config?.instrument_id && <span>instrument: {summary.config.instrument_id}</span>}
            {summary.starting_equity != null && (
              <span>starting equity: ${summary.starting_equity.toLocaleString()}</span>
            )}
            {summary.config?.param_overrides &&
              Object.keys(summary.config.param_overrides).length > 0 && (
                <span className="text-amber-400/80">
                  overrides: {Object.entries(summary.config.param_overrides)
                    .map(([key, value]) => `${key}=${value}`)
                    .join(' ')}
                </span>
              )}
          </div>
        </div>
      )}

      <ExperimentHistory key={historyKey} onRerun={handleLoadHistory} />

      <RunsCompare refreshKey={historyKey} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <LogPanel log={log} running={running} heightClass="h-[460px]" />

        <div className="bg-gray-900 border border-gray-800 rounded-2xl flex flex-col overflow-hidden h-[460px]">
          <div className="bg-gray-900 px-5 py-3 border-b border-gray-800 flex justify-between items-center">
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4 text-blue-400" />
              <h3 className="text-sm font-bold text-gray-100">Interactive tearsheet</h3>
            </div>
            {selectedTearsheetUrl && (
              <a
                href={staticReportUrl(selectedTearsheetUrl)}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
              >
                Open in new tab <ExternalLink className="w-3.5 h-3.5" />
              </a>
            )}
          </div>

          <div className="flex-1 bg-gray-950 flex flex-col">
            {selectedTearsheetUrl ? (
              <iframe
                src={staticReportUrl(selectedTearsheetUrl)}
                title="Tearsheet view"
                className="w-full h-full border-0 bg-white"
              />
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center p-6 text-center text-gray-500 text-xs">
                <FileText className="w-8 h-8 text-gray-700 mb-2" />
                No tearsheet generated yet.
                <br />
                Run a backtest with &quot;Generate HTML tearsheet&quot; enabled.
              </div>
            )}
          </div>

          {reports.length > 0 && (
            <div className="p-2.5 bg-gray-950 border-t border-gray-800 flex items-center gap-2 overflow-x-auto text-xs">
              <span className="text-gray-500 text-[11px] whitespace-nowrap">Reports:</span>
              {reports.slice(0, 6).map((report) => (
                <button
                  type="button"
                  key={report.filename}
                  onClick={() => setSelectedTearsheetUrl(report.url)}
                  title={`${report.modified} · ${report.size_kb} KB`}
                  className={`px-2.5 py-1 rounded-lg text-xs font-mono transition-colors whitespace-nowrap ${
                    selectedTearsheetUrl === report.url
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-900 text-gray-400 hover:bg-gray-800'
                  }`}
                >
                  {report.filename.replace('.html', '')}
                  <span className="text-[9px] text-gray-500 ml-1">{report.size_kb}KB</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
