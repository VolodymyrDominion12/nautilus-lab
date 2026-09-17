import React, { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Brain, Play, RefreshCw, Square, Terminal } from 'lucide-react';
import { cancelMlTrain, fetchMlModels, fetchMlTrainLog, runMlTrain } from '../services/api';
import type { MlModelInfo, MlTrainSummary } from '../services/api';
import { formatDateTime } from '../lib/format';

export const MLPipeline: React.FC<{ selectedCatalogPath?: string }> = ({ selectedCatalogPath }) => {
  const [modelType, setModelType] = useState<'formulaic' | 'meta_label'>('formulaic');
  const [folds, setFolds] = useState(5);
  const [embargo, setEmbargo] = useState(10);
  const [horizon, setHorizon] = useState(5);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState('');
  const [summary, setSummary] = useState<MlTrainSummary | null>(null);
  const [models, setModels] = useState<MlModelInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const sawRunning = useRef(false);

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

  // Poll only while a job is actually running: a permanent 2 s timer on an idle tab is
  // pure battery and log noise.
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(pollLog, 2000);
    return () => clearInterval(timer);
  }, [running]);

  const handleTrain = async () => {
    setError(null);
    try {
      const response = await runMlTrain({
        model_type: modelType,
        folds,
        embargo,
        horizon,
        catalog_path: selectedCatalogPath,
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
      <div>
        <h2 className="text-xl font-bold text-gray-100 flex items-center gap-2">
          <Brain className="w-6 h-6 text-emerald-400" />
          ML Pipeline
        </h2>
        <p className="text-sm text-gray-400 mt-1">
          Trains LightGBM models offline from the Parquet catalog with purged cross-validation.
          Pass an exclusive <span className="font-mono text-gray-300">end</span> so the artifact
          is fit only on in-sample bars; without it the log marks the model as in-sample only.
        </p>
      </div>

      {error && (
        <div className="p-3 rounded-xl bg-red-950/30 border border-red-800/40 text-red-300 text-xs flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {modelType === 'formulaic' && (
        <div className="p-3 rounded-xl bg-gray-900 border border-gray-800 text-[11px] text-gray-400">
          A formulaic model is only useful to the backtest if the robot reading it is wired:{' '}
          <span className="font-mono text-gray-300">FORMULAIC_MODEL_PATH</span> must point at the
          saved file from the Settings tab.
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 space-y-4">
          <h3 className="font-semibold text-gray-100">Training config</h3>
          <label className="block text-xs text-gray-400">Model type</label>
          <select
            value={modelType}
            onChange={(e) => setModelType(e.target.value as 'formulaic' | 'meta_label')}
            className="w-full bg-gray-950 border border-gray-800 rounded-xl px-3 py-2 text-sm"
          >
            <option value="formulaic">Formulaic LGBM</option>
            <option value="meta_label">Meta-label (triple barrier)</option>
          </select>

          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="text-xs text-gray-400">Folds</label>
              <input
                type="number"
                value={folds}
                onChange={(e) => setFolds(Number(e.target.value))}
                className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1.5 text-sm font-mono"
              />
            </div>
            <div>
              <label className="text-xs text-gray-400">Embargo</label>
              <input
                type="number"
                value={embargo}
                onChange={(e) => setEmbargo(Number(e.target.value))}
                className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1.5 text-sm font-mono"
              />
            </div>
            <div>
              <label className="text-xs text-gray-400">Horizon</label>
              <input
                type="number"
                value={horizon}
                onChange={(e) => setHorizon(Number(e.target.value))}
                className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1.5 text-sm font-mono"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs text-gray-400">Start (inclusive)</label>
              <input
                type="date"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1.5 text-sm font-mono"
              />
            </div>
            <div>
              <label className="text-xs text-gray-400">End (exclusive)</label>
              <input
                type="date"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
                className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1.5 text-sm font-mono"
              />
            </div>
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleTrain}
              disabled={running}
              className="flex-1 flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-xl py-2.5 text-sm font-medium"
            >
              <Play className="w-4 h-4" /> {running ? 'Training…' : 'Train'}
            </button>
            {running && (
              <button
                type="button"
                onClick={handleCancel}
                className="px-4 flex items-center gap-2 bg-red-950/50 border border-red-800/40 text-red-300 rounded-xl text-sm"
              >
                <Square className="w-4 h-4" />
              </button>
            )}
            <button
              type="button"
              onClick={pollLog}
              className="px-3 bg-gray-800 hover:bg-gray-700 rounded-xl text-gray-300"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>

          {summary && (
            <div className="text-xs space-y-1 font-mono text-gray-400 border-t border-gray-800 pt-3">
              {summary.model_type && <div>model_type: {summary.model_type}</div>}
              {summary.model_path && <div className="break-all">model: {summary.model_path}</div>}
              {summary.accuracy && (
                <div>
                  purged CV accuracy: <span className="text-gray-200">{summary.accuracy}</span>
                </div>
              )}
              {summary.take_profit_rate && (
                <div>
                  take-profit rate: <span className="text-gray-200">{summary.take_profit_rate}</span>
                </div>
              )}
              {summary.oof_precision && (
                <div>
                  OOF precision: <span className="text-gray-200">{summary.oof_precision}</span>
                </div>
              )}
              {summary.beats_always_take && (
                <div>
                  beats always-take:{' '}
                  <span className="text-gray-200">{summary.beats_always_take}</span>
                </div>
              )}
              {summary.majority_rate && (
                <div>
                  majority rate: <span className="text-gray-200">{summary.majority_rate}</span>
                </div>
              )}
              {summary.beats_majority && (
                <div>
                  beats majority: <span className="text-gray-200">{summary.beats_majority}</span>
                </div>
              )}
              {summary.train_window && (
                <div className="break-all">
                  train window: <span className="text-gray-200">{summary.train_window}</span>
                </div>
              )}
              {summary.rows != null && <div>rows: {summary.rows}</div>}
              {summary.created_at && <div>created: {formatDateTime(summary.created_at)}</div>}
              {summary.error_message && <div className="text-red-400">{summary.error_message}</div>}
            </div>
          )}
        </div>

        <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <Terminal className="w-5 h-5 text-gray-400" />
            <h3 className="font-semibold text-gray-100">Training log</h3>
            {running && <span className="text-xs text-amber-400 animate-pulse">running…</span>}
          </div>
          <pre className="flex-1 min-h-[240px] bg-gray-950 border border-gray-800 rounded-xl p-4 text-xs font-mono text-gray-300 overflow-auto whitespace-pre-wrap">
            {log || 'No training log yet.'}
          </pre>
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-gray-100">Saved models</h3>
          <button
            type="button"
            onClick={refreshModels}
            className="text-xs text-blue-400 hover:text-blue-300"
          >
            refresh
          </button>
        </div>
        {models.length === 0 ? (
          <p className="text-sm text-gray-500">No .txt models in models/</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {models.map((model) => (
              <div
                key={model.path}
                className="flex justify-between gap-3 p-3 rounded-xl bg-gray-950 border border-gray-800 text-sm font-mono"
              >
                <span className="text-gray-200 truncate" title={model.path}>
                  {model.filename}
                </span>
                <span className="text-gray-500 shrink-0">{model.size_kb} KB</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
