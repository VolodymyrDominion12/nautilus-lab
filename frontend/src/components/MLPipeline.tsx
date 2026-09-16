import React, { useEffect, useState } from 'react';
import { Brain, Play, RefreshCw, Square, Terminal } from 'lucide-react';
import {
  cancelMlTrain,
  fetchMlModels,
  fetchMlTrainLog,
  runMlTrain,
} from '../services/api';
import type { MlModelInfo, MlTrainSummary } from '../services/api';

export const MLPipeline: React.FC<{ selectedCatalogPath?: string }> = ({ selectedCatalogPath }) => {
  const [modelType, setModelType] = useState<'formulaic' | 'meta_label'>('formulaic');
  const [folds, setFolds] = useState(5);
  const [embargo, setEmbargo] = useState(10);
  const [horizon, setHorizon] = useState(5);
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState('');
  const [summary, setSummary] = useState<MlTrainSummary | null>(null);
  const [models, setModels] = useState<MlModelInfo[]>([]);

  const refreshModels = () => {
    fetchMlModels()
      .then((data) => setModels(data.models))
      .catch(console.error);
  };

  const pollLog = async () => {
    try {
      const data = await fetchMlTrainLog();
      setLog(data.log);
      setSummary(data.summary);
      setRunning(data.is_running);
      if (!data.is_running) refreshModels();
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    refreshModels();
    pollLog();
    const timer = setInterval(pollLog, 2000);
    return () => clearInterval(timer);
  }, []);

  const handleTrain = async () => {
    try {
      await runMlTrain({
        model_type: modelType,
        folds,
        embargo,
        horizon,
        catalog_path: selectedCatalogPath,
      });
      setRunning(true);
      setLog('');
      setSummary(null);
      pollLog();
    } catch (err) {
      console.error(err);
    }
  };

  const handleCancel = async () => {
    try {
      await cancelMlTrain();
      pollLog();
    } catch (err) {
      console.error(err);
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
          Train LightGBM models offline from the Parquet catalog. Purged CV on in-sample only.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 space-y-4">
          <h3 className="font-semibold text-gray-100">Training Config</h3>
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

          <div className="flex gap-2">
            <button
              onClick={handleTrain}
              disabled={running}
              className="flex-1 flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-xl py-2.5 text-sm font-medium"
            >
              <Play className="w-4 h-4" /> Train
            </button>
            {running && (
              <button
                onClick={handleCancel}
                className="px-4 flex items-center gap-2 bg-red-950/50 border border-red-800/40 text-red-300 rounded-xl text-sm"
              >
                <Square className="w-4 h-4" />
              </button>
            )}
            <button
              onClick={pollLog}
              className="px-3 bg-gray-800 hover:bg-gray-700 rounded-xl text-gray-300"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>

          {summary && (
            <div className="text-xs space-y-1 font-mono text-gray-400 border-t border-gray-800 pt-3">
              {summary.model_path && <div>model: {summary.model_path}</div>}
              {summary.accuracy && <div>accuracy: {summary.accuracy}</div>}
              {summary.rows != null && <div>rows: {summary.rows}</div>}
              {summary.error_message && <div className="text-red-400">{summary.error_message}</div>}
            </div>
          )}
        </div>

        <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <Terminal className="w-5 h-5 text-gray-400" />
            <h3 className="font-semibold text-gray-100">Training Log</h3>
            {running && <span className="text-xs text-amber-400 animate-pulse">running…</span>}
          </div>
          <pre className="flex-1 min-h-[240px] bg-gray-950 border border-gray-800 rounded-xl p-4 text-xs font-mono text-gray-300 overflow-auto whitespace-pre-wrap">
            {log || 'No training log yet.'}
          </pre>
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
        <h3 className="font-semibold text-gray-100 mb-3">Saved Models</h3>
        {models.length === 0 ? (
          <p className="text-sm text-gray-500">No .txt models in models/</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {models.map((model) => (
              <div
                key={model.path}
                className="flex justify-between p-3 rounded-xl bg-gray-950 border border-gray-800 text-sm font-mono"
              >
                <span className="text-gray-200">{model.filename}</span>
                <span className="text-gray-500">{model.size_kb} KB</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
