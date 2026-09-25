import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity, ShieldCheck } from 'lucide-react';

import { InfoTooltip } from './InfoTooltip';
import { DataCoverage } from './command/DataCoverage';
import { JobCards } from './command/JobCards';
import { JournalSummary } from './command/JournalSummary';
import { LastResultPanel } from './command/LastResultPanel';
import { RecentExperiments } from './command/RecentExperiments';
import { SystemPanels } from './command/SystemPanels';
import { commandCenterQuery } from '../services/queries';

/**
 * The lab's front page.
 *
 * Deliberately built around the two questions that decide whether work continues: what did
 * the last out-of-sample run actually prove, and is anything running right now. The old
 * version dumped `last_run.json` as raw JSON, which is data without a reading.
 */
export const CommandCenter: React.FC = () => {
  const result = useQuery(commandCenterQuery());
  const data = result.data ?? null;
  const error = result.error
    ? result.error.message || 'Failed to load the command center'
    : null;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-100 flex items-center gap-2">
            <Activity className="w-6 h-6 text-blue-400" />
            Command Center
          </h2>
          <p className="text-sm text-gray-400 mt-1">
            Research jobs, the last measured result, catalog coverage and the experiment journal.
          </p>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-emerald-950/40 border border-emerald-800/40 text-emerald-400 text-xs">
          <ShieldCheck className="w-4 h-4" />
          {data?.safety?.mode ?? 'FAIL_CLOSED'}
          <span className="text-emerald-600/80 font-mono">
            {data?.safety?.live_enabled ? 'live flag set (ignored)' : 'live disabled'}
          </span>
          <InfoTooltip term="fail_closed" size="xs" />
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-950/30 border border-red-800/40 text-red-300 text-sm">
          {error}
        </div>
      )}

      <JobCards jobs={data?.jobs ?? {}} />

      <LastResultPanel last={data?.last_research ?? null} />

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <RecentExperiments experimentRows={data?.recent_experiments ?? []} />
        <JournalSummary journal={data?.journal ?? {}} />
      </div>

      <DataCoverage data={data} />

      <SystemPanels data={data} />
    </div>
  );
};
