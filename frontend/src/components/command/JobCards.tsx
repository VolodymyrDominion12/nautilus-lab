import React from 'react';

import { formatElapsed } from '../../lib/format';
import type { CommandCenterResponse } from '../../services/api';

/** One card per background job: running or idle, and for how long. */
export const JobCards: React.FC<{ jobs: CommandCenterResponse['jobs'] }> = ({ jobs }) => {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
      {Object.entries(jobs).map(([key, job]) => (
        <div
          key={key}
          className={`bg-gray-900 border rounded-2xl p-4 transition-colors ${
            job.running ? 'border-amber-800/50 bg-amber-950/10' : 'border-gray-800'
          }`}
        >
          <div className="flex items-center justify-between mb-2 gap-2">
            <span className="text-xs text-gray-400 uppercase tracking-wide">
              {key.replace('_', ' ')}
            </span>
            <span
              className={`text-[10px] px-2 py-0.5 rounded-full font-mono shrink-0 flex items-center gap-1.5 ${
                job.running
                  ? 'bg-amber-950/50 text-amber-300 border border-amber-800/40'
                  : 'bg-gray-950 text-gray-500 border border-gray-800'
              }`}
            >
              {job.running && (
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
              )}
              {job.running ? 'RUNNING' : 'IDLE'}
            </span>
          </div>
          <p className="text-sm text-gray-200">{job.label}</p>
          {job.running && (
            <p className="text-[11px] font-mono text-amber-300 mt-1">
              {formatElapsed(job.elapsed_seconds ?? null) || 'starting…'} elapsed
            </p>
          )}
        </div>
      ))}
    </div>
  );
};
