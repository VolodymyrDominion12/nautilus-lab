import React, { useCallback, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Layers, Zap } from 'lucide-react';

import type { HistoryEntry, StrategySpec, StressSliceInfo } from '../services/api';
import { catalogQuery, dataHealthQuery, queryKeys, reportsQuery } from '../services/queries';
import { cliCommand, preflight, preflightBlocking } from '../lib/research';
import type { PreflightIssue } from '../lib/research';
import { toCliInput, toRunParams } from '../lib/researchForm';
import { WalkForwardBuilder } from './WalkForwardBuilder';
import { ExperimentHistory } from './ExperimentHistory';
import { RunsCompare } from './RunsCompare';
import { VerdictPanel } from './VerdictPanel';
import { FoldBreakdown } from './FoldBreakdown';
import { PboPanel } from './PboPanel';
import { LogPanel } from './LogPanel';
import { ResearchPresets } from './ResearchPresets';
import type { ResearchPresetConfig } from './ResearchPresets';
import { AdvancedGates } from './research/AdvancedGates';
import { BasicControls } from './research/BasicControls';
import { ParamOverrides } from './research/ParamOverrides';
import { ResearchBanners } from './research/ResearchBanners';
import { RunConditions } from './research/RunConditions';
import { RunControls } from './research/RunControls';
import { TearsheetPanel } from './research/TearsheetPanel';
import { useResearchForm } from './research/useResearchForm';
import { useResearchRun } from './research/useResearchRun';

interface ResearchLabProps {
  strategies: StrategySpec[];
  initialRobot?: string;
  selectedCatalogPath?: string;
  /** Which robots can read the tick series, as reported by the backend. */
  tickVpinRobots?: string[];
  hawkesRobots?: string[];
  /** Named stress windows with their real dates, from the backend. */
  stressSlices?: StressSliceInfo[];
  externalConfig?: { robot?: string; formula?: string; notes?: string } | null;
  onClearExternalConfig?: () => void;
}

const NO_ROBOTS: string[] = [];
const NO_SLICES: StressSliceInfo[] = [];

/**
 * The research tab: the form (`research/useResearchForm`), the job
 * (`research/useResearchRun`) and the result panels. Parameters are chosen on the
 * in-sample window only; the out-of-sample run is the result.
 */
export const ResearchLab: React.FC<ResearchLabProps> = ({
  strategies,
  initialRobot = 'regime',
  selectedCatalogPath,
  tickVpinRobots = NO_ROBOTS,
  hawkesRobots = NO_ROBOTS,
  stressSlices = NO_SLICES,
  externalConfig = null,
  onClearExternalConfig,
}) => {
  const queryClient = useQueryClient();
  const catalogResult = useQuery(catalogQuery(selectedCatalogPath ?? ''));
  // Which optional series (ticks, taker flow, funding) sit beside the bars. The engine
  // reads a missing tick series as an empty one, so the tick filters are checked against
  // this before a run is launched rather than discovered in the log afterwards.
  const healthResult = useQuery(dataHealthQuery(selectedCatalogPath ?? ''));
  const reports = useQuery(reportsQuery()).data?.reports ?? [];

  const catalog = catalogResult.data;
  const catalogError =
    catalog?.error ??
    (catalogResult.error ? catalogResult.error.message || 'Failed to load the catalog' : null);
  const catalogInstruments = useMemo(() => catalog?.instruments ?? [], [catalog?.instruments]);

  const { form, update, applyPreset, loadArchived, reset } = useResearchForm({
    initialRobot,
    externalConfig,
    strategies,
    catalogInstruments,
  });
  const { source, fullSample, usePbo, windowMode, isFraction, embargoBars, folds } = form;
  const { isStart, isEnd, oosStart, oosEnd } = form;

  const [activePresetId, setActivePresetId] = useState<string | null>(null);
  const [historyKey, setHistoryKey] = useState(0);
  const [pickedTearsheet, setPickedTearsheet] = useState<string | null>(null);
  const selectedTearsheetUrl = pickedTearsheet ?? reports[0]?.url ?? null;

  const onFinished = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.reports });
    setHistoryKey((value) => value + 1);
  }, [queryClient]);
  const job = useResearchRun({ onFinished, onTearsheet: setPickedTearsheet });
  const summary = job.summary;

  const selectedInstrument =
    catalogInstruments.find((item) => item.instrument_id === form.instrumentId) ??
    catalogInstruments[0] ??
    null;
  const instrumentIdForRun = selectedInstrument?.instrument_id;
  const selectedStrategyInfo = strategies.find((s) => s.name === form.robot);

  const selectedSliceWindow = useMemo(() => {
    const slice = stressSlices.find((item) => item.name === form.stressSlice);
    return slice ? { name: slice.name, start: slice.start, end: slice.end } : null;
  }, [form.stressSlice, stressSlices]);

  // Tick coverage of the instrument this run would use. null means the health endpoint
  // has not answered (yet): unknown is reported as unknown, not as absent.
  const tickDataAvailable = useMemo(() => {
    const health = healthResult.data?.instruments;
    if (health == null) return null;
    const entry = health.find((item) => item.instrument_id === (instrumentIdForRun ?? ''));
    return entry ? entry.ticks.present : null;
  }, [healthResult.data, instrumentIdForRun]);

  const issues: PreflightIssue[] = useMemo(() => {
    if (strategies.length === 0) {
      return [
        {
          level: 'error',
          message:
            'Strategy specifications are not loaded yet. Verify that the API server is running on http://localhost:8000.',
        },
      ];
    }
    return preflight({
      robot: form.robot,
      spec: selectedStrategyInfo,
      source,
      totalBars: selectedInstrument?.bars_count ?? null,
      syntheticBars: form.bars,
      folds,
      isFraction,
      embargoBars,
      fullSample,
      useOptuna: form.useOptuna,
      pbo: usePbo,
      windowMode,
      isStart,
      isEnd,
      oosStart,
      oosEnd,
      instrument: selectedInstrument,
      catalogInstruments: catalogInstruments.length,
      tickVpin: form.tickVpin,
      hawkes: form.hawkes,
      tickVpinRobots,
      hawkesRobots,
      tickDataAvailable,
      stressSliceWindow: selectedSliceWindow,
    });
  }, [
    strategies.length,
    form,
    selectedStrategyInfo,
    source,
    selectedInstrument,
    folds,
    isFraction,
    embargoBars,
    fullSample,
    usePbo,
    windowMode,
    isStart,
    isEnd,
    oosStart,
    oosEnd,
    catalogInstruments.length,
    tickVpinRobots,
    hawkesRobots,
    tickDataAvailable,
    selectedSliceWindow,
  ]);
  const blocked = preflightBlocking(issues);

  const handleRun = () => {
    void job.run(toRunParams(form, instrumentIdForRun, selectedCatalogPath));
  };

  const handleApplyPreset = (preset: ResearchPresetConfig) => {
    setActivePresetId(preset.id);
    applyPreset(preset.config);
  };

  const handleLoadHistory = (entry: HistoryEntry) => {
    if (!entry.config) return;
    job.setLaunchError(loadArchived(entry.config));
  };

  const onRunKeyDown = (event: React.KeyboardEvent) => {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && !job.running && !blocked) {
      event.preventDefault();
      handleRun();
    }
  };

  // The banners describe the result on screen, not the toggle that is currently set:
  // switching back to "catalog" used to hide the warning while synthetic numbers stayed.
  return (
    <div className="flex flex-col gap-6" onKeyDown={onRunKeyDown}>
      <ResearchBanners
        syntheticResultOnScreen={summary?.source === 'synthetic'}
        source={source}
        fullSample={fullSample}
        catalogError={catalogError}
        launchError={job.launchError}
        onDismissLaunchError={() => job.setLaunchError(null)}
        staleNotice={job.staleNotice}
      />

      {source === 'catalog' && !fullSample && !usePbo && (
        <WalkForwardBuilder
          mode={windowMode}
          onModeChange={(value) => update({ windowMode: value })}
          isFraction={isFraction}
          embargoBars={embargoBars}
          folds={folds}
          isStart={isStart}
          isEnd={isEnd}
          oosStart={oosStart}
          oosEnd={oosEnd}
          onIsStartChange={(value) => update({ isStart: value })}
          onIsEndChange={(value) => update({ isEnd: value })}
          onOosStartChange={(value) => update({ oosStart: value })}
          onOosEndChange={(value) => update({ oosEnd: value })}
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
              onClick={() => update({ source: 'catalog' })}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                source === 'catalog' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Parquet Catalog (real)
            </button>
            <button
              type="button"
              onClick={() => update({ source: 'synthetic' })}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                source === 'synthetic' ? 'bg-amber-600 text-white' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Synthetic (smoke)
            </button>
          </div>
        </div>

        {externalConfig && (
          <div className="p-3 bg-purple-950/40 border border-purple-800/60 rounded-xl flex items-center justify-between gap-3 text-xs text-purple-200">
            <div className="flex items-center gap-2">
              <Zap className="w-4 h-4 text-amber-400 shrink-0" />
              <span>
                Loaded from Alpha Hypothesis: <span className="font-mono font-bold text-white">{externalConfig.notes || externalConfig.formula}</span>
              </span>
            </div>
            {onClearExternalConfig && (
              <button
                type="button"
                onClick={onClearExternalConfig}
                className="text-[10px] font-mono text-purple-400 hover:text-purple-200 underline"
              >
                Dismiss
              </button>
            )}
          </div>
        )}

        <ResearchPresets
          onApplyPreset={handleApplyPreset}
          activePresetId={activePresetId}
        />

        <div className="border-t border-gray-800/80" />

        <BasicControls
          form={form}
          update={update}
          strategies={strategies}
          catalogInstruments={catalogInstruments}
          selectedInstrument={selectedInstrument}
          catalogError={catalogError}
        />

        <RunControls
          issues={issues}
          blocked={blocked}
          running={job.running}
          launchedAtIso={job.launchedAtIso}
          onRun={handleRun}
          onCancel={job.cancel}
          onReset={reset}
          cliText={() => cliCommand(toCliInput(form, instrumentIdForRun, selectedCatalogPath))}
          strategy={selectedStrategyInfo}
        />

        <ParamOverrides form={form} update={update} strategy={selectedStrategyInfo} />

        <AdvancedGates
          form={form}
          update={update}
          tickDataAvailable={tickDataAvailable}
          hawkesRobots={hawkesRobots}
          stressSlices={stressSlices}
          selectedInstrument={selectedInstrument}
        />
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

      {summary?.is_finished && !summary.is_error && <RunConditions summary={summary} />}

      <ExperimentHistory key={historyKey} onRerun={handleLoadHistory} />

      <RunsCompare refreshKey={historyKey} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <LogPanel log={job.log} running={job.running} heightClass="h-[460px]" />
        <TearsheetPanel
          reports={reports}
          selectedTearsheetUrl={selectedTearsheetUrl}
          onSelect={setPickedTearsheet}
        />
      </div>
    </div>
  );
};
