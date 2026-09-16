import React, { useEffect, useState } from 'react';
import {
  Activity,
  BookOpen,
  Brain,
  Database,
  FlaskConical,
  ShieldCheck,
  Terminal,
} from 'lucide-react';
import { fetchCommandCenter } from '../services/api';
import type { CommandCenterResponse } from '../services/api';

export const CommandCenter: React.FC = () => {
  const [data, setData] = useState<CommandCenterResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    fetchCommandCenter()
      .then((payload) => {
        setData(payload);
        setError(null);
      })
      .catch((err) => setError(String(err)));
  };

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, []);

  const jobs = data?.jobs ?? {};
  const journal = data?.journal ?? {};

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-100 flex items-center gap-2">
            <Activity className="w-6 h-6 text-blue-400" />
            Command Center
          </h2>
          <p className="text-sm text-gray-400 mt-1">
            Unified view of research jobs, catalog, models, and experiment journal.
          </p>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-emerald-950/40 border border-emerald-800/40 text-emerald-400 text-xs">
          <ShieldCheck className="w-4 h-4" />
          {data?.safety?.mode ?? 'FAIL_CLOSED'}
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-950/30 border border-red-800/40 text-red-300 text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {Object.entries(jobs).map(([key, job]) => (
          <div key={key} className="bg-gray-900 border border-gray-800 rounded-2xl p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-gray-400 uppercase tracking-wide">{key.replace('_', ' ')}</span>
              <span
                className={`text-[10px] px-2 py-0.5 rounded-full font-mono ${
                  job.running
                    ? 'bg-amber-950/50 text-amber-300 border border-amber-800/40'
                    : 'bg-gray-950 text-gray-500 border border-gray-800'
                }`}
              >
                {job.running ? 'RUNNING' : 'IDLE'}
              </span>
            </div>
            <p className="text-sm text-gray-200">{job.label}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 lg:col-span-2">
          <div className="flex items-center gap-2 mb-4">
            <FlaskConical className="w-5 h-5 text-blue-400" />
            <h3 className="font-semibold text-gray-100">Recent Experiments</h3>
          </div>
          {(data?.recent_experiments?.length ?? 0) === 0 ? (
            <p className="text-sm text-gray-500">No archived experiments yet.</p>
          ) : (
            <div className="space-y-2">
              {data?.recent_experiments?.map((item) => (
                <div
                  key={item.history_id}
                  className="flex items-center justify-between p-3 rounded-xl bg-gray-950/60 border border-gray-800/80 text-sm"
                >
                  <div>
                    <span className="font-mono text-blue-300">{item.robot}</span>
                    <span className="text-gray-500 mx-2">·</span>
                    <span className="text-gray-400">{item.run_type}</span>
                  </div>
                  <span className="text-xs text-gray-500">{item.finished_at ?? '—'}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <BookOpen className="w-5 h-5 text-purple-400" />
            <h3 className="font-semibold text-gray-100">Journal</h3>
          </div>
          <div className="grid grid-cols-2 gap-2 text-sm">
            {Object.entries(journal).map(([decision, count]) => (
              <div key={decision} className="p-2 rounded-lg bg-gray-950 border border-gray-800">
                <div className="text-[10px] uppercase text-gray-500">{decision}</div>
                <div className="text-lg font-mono text-gray-100">{count}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Brain className="w-5 h-5 text-emerald-400" />
            <h3 className="font-semibold text-gray-100">ML Models</h3>
          </div>
          {(data?.models?.length ?? 0) === 0 ? (
            <p className="text-sm text-gray-500">No trained models in models/</p>
          ) : (
            <div className="space-y-2">
              {data?.models?.map((model) => (
                <div
                  key={model.path}
                  className="flex justify-between text-sm p-2 rounded-lg bg-gray-950 border border-gray-800 font-mono"
                >
                  <span className="text-gray-200">{model.filename}</span>
                  <span className="text-gray-500">{model.size_kb} KB</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Database className="w-5 h-5 text-cyan-400" />
            <h3 className="font-semibold text-gray-100">System</h3>
          </div>
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-gray-500">Catalog</dt>
              <dd className="text-gray-300 font-mono truncate max-w-[60%]">{data?.catalog_path ?? '—'}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500">Robots wired</dt>
              <dd className="text-gray-300">{data?.robots?.wired?.length ?? 0} / {data?.robots?.total ?? 0}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500">Last research</dt>
              <dd className="text-gray-300">
                {typeof data?.last_research?.robot === 'string' ? data.last_research.robot : 'none'}
              </dd>
            </div>
          </dl>
        </div>
      </div>

      {data?.last_research && (
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <Terminal className="w-5 h-5 text-gray-400" />
            <h3 className="font-semibold text-gray-100">Last Research Snapshot</h3>
          </div>
          <pre className="text-xs text-gray-400 overflow-x-auto font-mono">
            {JSON.stringify(data.last_research, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
};
