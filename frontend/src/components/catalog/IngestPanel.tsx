import React, { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Download, Plus, RefreshCw, Square } from 'lucide-react';

import { cancelIngest, runIngest } from '../../services/api';
import { ingestLogQuery, statusQuery } from '../../services/queries';
import { DEFAULT_FORM, buildIngestRequest, ingestWarnings, startMessage } from '../../lib/ingestForm';
import type { IngestFormState } from '../../lib/ingestForm';
import { IngestForm } from './IngestForm';

interface IngestPanelProps {
  selectedCatalogPath: string;
  /** The ingest ended (finished, failed or cancelled): its data may have changed. */
  onFinished: () => void;
  onError: (message: string) => void;
}

const SUMMARY_LINE = /^symbol=|^WARNING |^NOTE |FAILED:|^archive cache:/;

/** Lines of the log worth reading first: per-symbol results, warnings, failures. */
function summaryLines(log: string): string[] {
  return log.split('\n').filter((line) => SUMMARY_LINE.test(line));
}

/** The ingest form, its start/stop buttons and the streamed log of the running job. */
export const IngestPanel: React.FC<IngestPanelProps> = ({
  selectedCatalogPath,
  onFinished,
  onError,
}) => {
  const [form, setForm] = useState<IngestFormState>(DEFAULT_FORM);
  const [ingestLog, setIngestLog] = useState('');
  /** Button state: true from the click until the server reports the job idle. */
  const [ingestRunning, setIngestRunning] = useState(false);
  /** Log polling: only once the API has accepted the job. */
  const [polling, setPolling] = useState(false);
  /** When polling began; an answer older than this is from a previous run. */
  const pollingSince = useRef(0);

  const logQuery = useQuery(ingestLogQuery(polling));
  const statusRes = useQuery(statusQuery(selectedCatalogPath));

  useEffect(() => {
    if (statusRes.data?.ingest_running && !polling) {
      setPolling(true);
      setIngestRunning(true);
      pollingSince.current = 0;
    }
  }, [statusRes.data?.ingest_running, polling]);

  useEffect(() => {
    const res = logQuery.data;
    if (!polling || !res || logQuery.dataUpdatedAt < pollingSince.current) return;
    setIngestLog(res.log);
    // Stop as soon as the server reports idle, whatever the log says (BUG-1: waiting for
    // "Process finished" left the button stuck when the process crashed or was cancelled).
    if (!res.is_running) {
      setPolling(false);
      setIngestRunning(false);
      onFinished();
    }
  }, [logQuery.data, logQuery.dataUpdatedAt, polling, onFinished]);

  const blocked = ingestWarnings(form).includes('Start must be before end.');

  const startIngest = async (incremental: boolean) => {
    onError('');
    setIngestRunning(true);
    setIngestLog(startMessage(form, incremental));
    try {
      const response = await runIngest(buildIngestRequest(form, selectedCatalogPath, incremental));
      if (response.status === 'started') {
        pollingSince.current = Date.now();
        setPolling(true);
      } else {
        setIngestRunning(false);
        onError(response.message ?? 'The ingest was refused by the API.');
      }
    } catch (err) {
      setIngestRunning(false);
      const message = err instanceof Error ? err.message : String(err);
      setIngestLog((prev) => `${prev}\nError: ${message}\n`);
      onError(message);
    }
  };

  const cancel = async () => {
    try {
      const response = await cancelIngest();
      setIngestLog((prev) => `${prev}\n${response.message ?? response.status}\n`);
      if (response.status === 'idle') {
        setPolling(false);
        setIngestRunning(false);
      }
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Failed to cancel the ingest');
    }
  };

  const summary = summaryLines(ingestLog);
  const canIncrement = form.source === 'rest' && form.series === 'klines';

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div className="bg-gray-900 border border-gray-800 p-6 rounded-2xl flex flex-col gap-4">
        <div className="flex items-center gap-2">
          <Download className="w-5 h-5 text-emerald-400" />
          <h3 className="text-lg font-bold text-gray-100">Ingest Binance data</h3>
        </div>
        <p className="text-xs text-gray-400">
          Public data only, no API keys. History comes from the archive; REST is for the newest
          days, ticks and live depth.
        </p>

        <IngestForm
          form={form}
          onChange={(patch) => setForm((prev) => ({ ...prev, ...patch }))}
          selectedCatalogPath={selectedCatalogPath}
        />

        <button
          type="button"
          onClick={() => startIngest(false)}
          disabled={ingestRunning || !form.symbols.trim() || blocked}
          className="w-full py-3 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-800 text-white font-medium rounded-xl flex items-center justify-center gap-2"
        >
          {ingestRunning ? (
            <RefreshCw className="w-5 h-5 animate-spin" />
          ) : (
            <Download className="w-5 h-5" />
          )}
          {form.source === 'archive' ? 'Ingest from archive' : 'Fetch via REST'}
        </button>

        {canIncrement && (
          <button
            type="button"
            onClick={() => startIngest(true)}
            disabled={ingestRunning || !form.symbols.trim()}
            title="Fetch only bars newer than the last stored one"
            className="w-full py-3 bg-blue-700 hover:bg-blue-600 disabled:bg-gray-800 disabled:text-gray-500 text-white font-medium rounded-xl flex items-center justify-center gap-2"
          >
            <Plus className="w-5 h-5" />
            Update bars (incremental)
          </button>
        )}

        {ingestRunning && (
          <button
            type="button"
            onClick={cancel}
            className="w-full py-2 bg-red-950/60 hover:bg-red-900/60 text-red-300 border border-red-800/60 text-sm font-medium rounded-xl flex items-center justify-center gap-2"
          >
            <Square className="w-3.5 h-3.5" />
            Stop ingest
          </button>
        )}
      </div>

      <div className="lg:col-span-2 flex flex-col gap-4">
        {summary.length > 0 && (
          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-4 max-h-[220px] overflow-y-auto">
            <h4 className="text-xs font-bold text-gray-300 mb-2">Result per symbol</h4>
            <ul className="font-mono text-[11px] space-y-0.5">
              {summary.map((line, index) => (
                <li
                  key={`${index}-${line}`}
                  className={
                    /FAILED|quality=fail/.test(line)
                      ? 'text-red-400'
                      : /^WARNING|quality=warn/.test(line)
                        ? 'text-amber-300'
                        : 'text-gray-300'
                  }
                >
                  {line}
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="bg-[#0a0f18] border border-gray-800 rounded-2xl flex flex-col overflow-hidden h-[400px]">
          <div className="bg-gray-900/80 px-4 py-2.5 border-b border-gray-800 flex justify-between items-center">
            <span className="text-xs font-mono text-gray-400">Ingest log</span>
            <span className="text-[11px] font-mono text-gray-500">
              {ingestRunning ? 'streaming…' : 'idle'}
            </span>
          </div>
          <div className="p-4 flex-1 overflow-y-auto font-mono text-xs text-emerald-400 whitespace-pre-wrap">
            {ingestLog || 'Ready to download data.\n'}
          </div>
        </div>
      </div>
    </div>
  );
};
