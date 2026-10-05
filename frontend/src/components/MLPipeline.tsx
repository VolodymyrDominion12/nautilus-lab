import React, { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Brain, Database, Terminal } from 'lucide-react';
import {
  cancelMlTrain,
  deleteMlModel,
  fetchMlModels,
  fetchMlTrainLog,
  runMlTrain,
} from '../services/api';
import type { MlModelInfo, MlTrainSummary } from '../services/api';
import { catalogQuery } from '../services/queries';
import type { SupportedModel } from './ml/types';
import { MLConfigPanel } from './ml/MLConfigPanel';
import { MLRunsSummary } from './ml/MLRunsSummary';
import { MLSavedModels } from './ml/MLSavedModels';

export const MLPipeline: React.FC<{ selectedCatalogPath?: string }> = ({ selectedCatalogPath }) => {
  const [selectedModels, setSelectedModels] = useState<SupportedModel[]>(['formulaic']);
  const [selectedInstruments, setSelectedInstruments] = useState<string[]>([]);
  const [customInstrument, setCustomInstrument] = useState('');

  const [folds, setFolds] = useState(5);
  const [embargo, setEmbargo] = useState(10);
  const [horizon, setHorizon] = useState(5);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');

  const [profitMultiple, setProfitMultiple] = useState('2.0');
  const [stopMultiple, setStopMultiple] = useState('1.0');
  const [volWindow, setVolWindow] = useState(20);
  const [threshold, setThreshold] = useState('0.55');

  const [running, setRunning] = useState(false);
  const [log, setLog] = useState('');
  const [summary, setSummary] = useState<MlTrainSummary | null>(null);
  const [models, setModels] = useState<MlModelInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const sawRunning = useRef(false);

  const catalogRes = useQuery(catalogQuery(selectedCatalogPath ?? ''));
  const catalog = catalogRes.data;
  const availableInstruments = React.useMemo(
    () => catalog?.instruments ?? [],
    [catalog?.instruments],
  );

  useEffect(() => {
    if (selectedInstruments.length === 0 && availableInstruments.length > 0 && availableInstruments[0]) {
      setSelectedInstruments([availableInstruments[0].instrument_id]);
    }
  }, [availableInstruments, selectedInstruments.length]);

  const refreshModels = () => {
    fetchMlModels()
      .then((data) => setModels(data.models))
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Failed to list trained models'),
      );
  };

  const pollLog = async () => {
    try {
      const data = await fetchMlTrainLog();
      setLog(data.log);
      setSummary(data.summary);
      setRunning(data.is_running);
      if (data.is_running) sawRunning.current = true;
      if (!data.is_running && sawRunning.current) {
        sawRunning.current = false;
        refreshModels();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to read the training log');
    }
  };

  useEffect(() => {
    refreshModels();
    pollLog();
  }, []);

  useEffect(() => {
    if (!running) return;
    const timer = setInterval(pollLog, 2000);
    return () => clearInterval(timer);
  }, [running]);

  const toggleModel = (id: SupportedModel) => {
    setSelectedModels((prev) =>
      prev.includes(id) ? (prev.length > 1 ? prev.filter((m) => m !== id) : prev) : [...prev, id],
    );
  };

  const selectAllModels = () => {
    setSelectedModels(['formulaic', 'meta_label', 'obi']);
  };

  const toggleInstrument = (instId: string) => {
    setSelectedInstruments((prev) =>
      prev.includes(instId) ? prev.filter((i) => i !== instId) : [...prev, instId],
    );
  };

  const selectAllInstruments = () => {
    setSelectedInstruments(availableInstruments.map((i) => i.instrument_id));
  };

  const clearInstruments = () => {
    setSelectedInstruments([]);
  };

  const handleAddCustomInstrument = () => {
    const trimmed = customInstrument.trim();
    if (trimmed && !selectedInstruments.includes(trimmed)) {
      setSelectedInstruments((prev) => [...prev, trimmed]);
      setCustomInstrument('');
    }
  };

  const handleDeleteModel = async (path: string) => {
    if (!window.confirm(`Delete model ${path}?`)) return;
    try {
      const res = await deleteMlModel(path);
      if (res.status === 'ok') {
        refreshModels();
      } else {
        setError(res.message ?? 'Failed to delete model');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error deleting model');
    }
  };

  const totalTasks = selectedModels.length * selectedInstruments.length;

  const handleTrain = async () => {
    setError(null);
    if (selectedModels.length === 0) {
      setError('Please select at least one model type.');
      return;
    }
    if (selectedInstruments.length === 0) {
      setError('Please select at least one instrument / pair.');
      return;
    }

    try {
      const isBatch = totalTasks > 1;
      const response = await runMlTrain({
        model_type: selectedModels[0],
        model_types: isBatch ? selectedModels : undefined,
        folds,
        embargo,
        horizon,
        catalog_path: selectedCatalogPath,
        instrument_id: !isBatch ? selectedInstruments[0] : undefined,
        instruments: isBatch ? selectedInstruments : undefined,
        profit_multiple: profitMultiple,
        stop_multiple: stopMultiple,
        vol_window: volWindow,
        threshold,
        start: start.trim() || undefined,
        end: end.trim() || undefined,
      });

      if (response.status !== 'started') {
        setError(response.message ?? 'Training was refused by the API.');
        return;
      }
      sawRunning.current = true;
      setRunning(true);
      setLog('');
      setSummary(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start training');
    }
  };

  const handleCancel = async () => {
    try {
      const response = await cancelMlTrain();
      if (response.status === 'idle') setError(response.message ?? null);
      pollLog();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel');
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-gray-100 flex items-center gap-2">
            <Brain className="w-6 h-6 text-emerald-400" />
            ML Pipeline & Model Factory
          </h2>
          <p className="text-sm text-gray-400 mt-1">
            Offline LightGBM training with Purged K-Fold Cross-Validation. Train any model across
            individual pairs or run full matrix training over all catalog instruments.
          </p>
        </div>
        {catalog && (
          <div className="flex items-center gap-2 bg-gray-900 border border-gray-800 rounded-xl px-3 py-2 text-xs text-gray-300">
            <Database className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>
              Catalog:{' '}
              <strong className="text-gray-100 font-mono">
                {catalog.name || selectedCatalogPath || 'Default'}
              </strong>{' '}
              ({availableInstruments.length} pairs available)
            </span>
          </div>
        )}
      </div>

      {error && (
        <div className="p-3.5 rounded-xl bg-red-950/40 border border-red-800/60 text-red-200 text-xs flex items-start gap-2.5 shadow-sm">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5 text-red-400" />
          <span className="leading-relaxed">{error}</span>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-5">
          <MLConfigPanel
            selectedModels={selectedModels}
            onToggleModel={toggleModel}
            onSelectAllModels={selectAllModels}
            availableInstruments={availableInstruments}
            selectedInstruments={selectedInstruments}
            onToggleInstrument={toggleInstrument}
            onSelectAllInstruments={selectAllInstruments}
            onClearInstruments={clearInstruments}
            customInstrument={customInstrument}
            setCustomInstrument={setCustomInstrument}
            onAddCustomInstrument={handleAddCustomInstrument}
            folds={folds}
            setFolds={setFolds}
            embargo={embargo}
            setEmbargo={setEmbargo}
            horizon={horizon}
            setHorizon={setHorizon}
            start={start}
            setStart={setStart}
            end={end}
            setEnd={setEnd}
            profitMultiple={profitMultiple}
            setProfitMultiple={setProfitMultiple}
            stopMultiple={stopMultiple}
            setStopMultiple={setStopMultiple}
            volWindow={volWindow}
            setVolWindow={setVolWindow}
            threshold={threshold}
            setThreshold={setThreshold}
            running={running}
            totalTasks={totalTasks}
            onTrain={handleTrain}
            onCancel={handleCancel}
            onPollLog={pollLog}
          />
        </div>

        <div className="lg:col-span-7 flex flex-col gap-4">
          {summary && <MLRunsSummary summary={summary} />}

          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col flex-1 gap-3 min-h-[360px]">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Terminal className="w-5 h-5 text-gray-400" />
                <h3 className="font-semibold text-gray-100 text-sm">Live Execution Log</h3>
              </div>
              {running && (
                <span className="flex items-center gap-1.5 text-xs text-amber-400 font-medium animate-pulse">
                  <span className="w-2 h-2 rounded-full bg-amber-400"></span>
                  Training in progress…
                </span>
              )}
            </div>
            <pre className="flex-1 bg-gray-950 border border-gray-800 rounded-xl p-4 text-xs font-mono text-gray-300 overflow-auto whitespace-pre-wrap leading-relaxed">
              {log || 'No active training job. Select models and pairs on the left, then click Train.'}
            </pre>
          </div>
        </div>
      </div>

      <MLSavedModels
        models={models}
        refreshModels={refreshModels}
        onDeleteModel={handleDeleteModel}
      />
    </div>
  );
};
