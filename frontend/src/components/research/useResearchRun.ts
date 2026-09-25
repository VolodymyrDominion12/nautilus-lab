import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { cancelResearch, runResearch } from '../../services/api';
import type { ResearchRunParams, ResearchSummary } from '../../services/api';
import { researchLogQuery } from '../../services/queries';

interface Launch {
  /** Wall-clock start, to tell this run's result from an older one on disk. */
  startedAtMs: number;
  sawRunning: boolean;
  polls: number;
  /** `dataUpdatedAt` of the last answer handled, so one answer is counted once. */
  lastSeen: number;
}

const STALE_RESULT =
  'The numbers below are from a previous run: this job ended without writing a result. Check the log.';
const DIED_WITHOUT_RESULT =
  'The research process stopped without writing a result. The log above has the reason.';

/**
 * One research job: launch, poll its log and summary while it runs, cancel.
 *
 * The log is polled only between a launch the API accepted and the job's end, through the
 * shared query cache, so a hidden tab stops polling too. `onFinished` runs once per job,
 * whether it wrote a result or died without one.
 */
export function useResearchRun({
  onFinished,
  onTearsheet,
}: {
  onFinished: () => void;
  onTearsheet: (url: string) => void;
}) {
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState('');
  const [summary, setSummary] = useState<ResearchSummary | null>(null);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [launchedAtIso, setLaunchedAtIso] = useState<string | null>(null);
  const [staleNotice, setStaleNotice] = useState<string | null>(null);
  const launchRef = useRef<Launch | null>(null);

  const logResult = useQuery(researchLogQuery(running));

  const finish = useCallback(() => {
    launchRef.current = null;
    setRunning(false);
    onFinished();
  }, [onFinished]);

  useEffect(() => {
    const res = logResult.data;
    const launch = launchRef.current;
    const at = logResult.dataUpdatedAt;
    // An answer from before this launch belongs to the previous job (the cache keeps it).
    if (!running || !res || !launch || at < launch.startedAtMs || at === launch.lastSeen) return;
    launch.lastSeen = at;
    launch.polls += 1;
    if (res.is_running) launch.sawRunning = true;

    setLog(res.log);
    setSummary(res.summary);
    if (res.summary.tearsheet_url) onTearsheet(res.summary.tearsheet_url);

    if (!res.is_running && res.summary.is_finished) {
      const finishedMs = res.summary.finished_at ? Date.parse(res.summary.finished_at) : null;
      const own = finishedMs != null && finishedMs >= launch.startedAtMs - 2000;
      setStaleNotice(own ? null : STALE_RESULT);
      finish();
      return;
    }
    // The process died before writing last_run.json. Without this the UI would say
    // "Simulating..." forever, because polling stops only on a finished result. A job that
    // died before the first poll never shows `is_running`, so a quiet idle server also
    // ends the wait after a few polls.
    if (!res.is_running && launch.polls > 2 && (launch.sawRunning || launch.polls > 5)) {
      setStaleNotice(DIED_WITHOUT_RESULT);
      finish();
    }
  }, [logResult.data, logResult.dataUpdatedAt, running, finish, onTearsheet]);

  const run = async (params: ResearchRunParams) => {
    setLaunchError(null);
    setStaleNotice(null);
    try {
      const response = await runResearch(params);
      if (response.status !== 'started') {
        // HTTP 200 with status "error": the old UI ignored this and spun forever.
        setLaunchError(response.message ?? 'The run was refused by the API.');
        setRunning(false);
        return;
      }
      launchRef.current = { startedAtMs: Date.now(), sawRunning: false, polls: 0, lastSeen: 0 };
      setLaunchedAtIso(new Date().toISOString());
      setRunning(true);
      setLog(`Starting research for ${params.robot} (${params.source} mode)...\n`);
    } catch (err) {
      setRunning(false);
      setLaunchError(err instanceof Error ? err.message : 'Failed to start research');
    }
  };

  const cancel = async () => {
    try {
      const response = await cancelResearch();
      setLog((prev) => `${prev}\nCancellation requested: ${response.message ?? response.status}\n`);
    } catch (err) {
      setLog((prev) => `${prev}\nCancel failed: ${err instanceof Error ? err.message : err}\n`);
    }
  };

  return {
    running,
    log,
    summary,
    launchError,
    setLaunchError,
    launchedAtIso,
    staleNotice,
    run,
    cancel,
  };
}
