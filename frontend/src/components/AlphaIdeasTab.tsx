import React, { useEffect, useState } from 'react';
import { BookOpen, ClipboardCopy, RefreshCw, Sparkles, Terminal, TriangleAlert } from 'lucide-react';
import { runPropose } from '../services/api';
import type { ProposeResponse } from '../services/api';
import { formatDateTime } from '../lib/format';

interface HypothesisEntry {
  file: string;
  modified: string;
  size_kb: number;
  url: string;
}

/**
 * Standalone tab for the offline LLM alpha-hypothesis workflow.
 *
 * ProposeAlpha was previously buried inside JournalKanban. This gives it its own
 * space and adds hypothesis file listing + previewing.
 */
export const AlphaIdeasTab: React.FC = () => {
  const [count, setCount] = useState(5);
  const [dryRun, setDryRun] = useState(true);
  const [journal, setJournal] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [running, setRunning] = useState(false);
  const [output, setOutput] = useState('');
  const [artifactPath, setArtifactPath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [hypotheses, setHypotheses] = useState<HypothesisEntry[]>([]);
  const [hypoError, setHypoError] = useState<string | null>(null);
  const [loadingHypo, setLoadingHypo] = useState(false);

  const fetchHypotheses = () => {
    setLoadingHypo(true);
    // Hypotheses are served from the reports-style endpoint; fall back gracefully
    // if the endpoint does not exist yet.
    fetch('/api/hypotheses')
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then((data: { hypotheses: HypothesisEntry[] }) => {
        setHypotheses(data.hypotheses ?? []);
        setHypoError(null);
      })
      .catch(() => {
        // Endpoint may not exist — not a blocking error
        setHypoError(null);
        setHypotheses([]);
      })
      .finally(() => setLoadingHypo(false));
  };

  useEffect(() => {
    fetchHypotheses();
  }, []);

  const handleRun = async () => {
    setRunning(true);
    setError(null);
    setArtifactPath(null);
    try {
      const result: ProposeResponse = await runPropose({
        count,
        dry_run: dryRun,
        journal,
        prompt: prompt.trim() || undefined,
      });
      if (result.status === 'dry_run') {
        setOutput(String(result.prompt ?? result.message ?? JSON.stringify(result, null, 2)));
      } else {
        setOutput(
          [result.summary, result.artifact_path ? `artifact=${result.artifact_path}` : '']
            .filter(Boolean)
            .join('\n\n'),
        );
        if (result.artifact_path) {
          setArtifactPath(result.artifact_path);
          fetchHypotheses();
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Propose failed');
    } finally {
      setRunning(false);
    }
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(output).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-bold text-gray-100 flex items-center gap-2">
          <Sparkles className="w-6 h-6 text-amber-400" />
          Alpha Ideas
        </h2>
        <p className="text-sm text-gray-400 mt-1">
          Offline LLM hypothesis drafting.{' '}
          <span className="font-mono text-xs">lab propose</span> — never runs on the backtest hot
          path.
        </p>
      </div>

      {/* Warning about requirements */}
      <div className="p-4 bg-amber-950/30 border border-amber-800/40 rounded-2xl text-xs text-amber-300 leading-relaxed">
        <span className="font-semibold">Requires:</span>{' '}
        <span className="font-mono">LLM_API_KEY</span> in{' '}
        <span className="font-mono">.env</span>. Without it the API returns an error (exit 1).
        Use <span className="font-semibold">Dry run</span> to preview the prompt without any
        network call.
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 flex flex-col gap-5">
        <h3 className="text-sm font-semibold text-gray-100 flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-amber-400" />
          Propose hypotheses
        </h3>

        {/* Controls */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-gray-300">
              Number of hypotheses
            </label>
            <input
              type="number"
              min={1}
              max={20}
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
              className="bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 focus:border-amber-500 focus:outline-none font-mono w-28"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-gray-300">Custom prompt (optional)</label>
            <input
              type="text"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Leave blank to use the default prompt"
              className="bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 focus:border-amber-500 focus:outline-none"
            />
          </div>
        </div>

        <div className="flex flex-wrap gap-4 items-center">
          <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
              className="rounded bg-gray-950 border-gray-700 text-amber-600 focus:ring-0"
            />
            Dry run (preview prompt, no API call)
          </label>
          <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer">
            <input
              type="checkbox"
              checked={journal}
              onChange={(e) => setJournal(e.target.checked)}
              className="rounded bg-gray-950 border-gray-700 text-amber-600 focus:ring-0"
            />
            Write journal entry on success
          </label>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <button
            type="button"
            onClick={handleRun}
            disabled={running}
            className="px-5 py-2.5 bg-amber-700 hover:bg-amber-600 disabled:bg-gray-800 disabled:text-gray-500 text-white font-medium rounded-xl transition-colors flex items-center gap-2"
          >
            {running ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Sparkles className="w-4 h-4" />
            )}
            {running ? 'Running\u2026' : dryRun ? 'Preview prompt' : 'Run propose'}
          </button>
          <span className="text-xs text-gray-500 font-mono">
            CLI:{' '}
            <span className="text-gray-300">
              lab propose{dryRun ? ' --dry-run' : ''} --count {count}
              {journal ? ' --journal' : ''}
            </span>
          </span>
        </div>

        {error && (
          <div className="p-3 bg-red-950/40 border border-red-800/60 rounded-xl text-red-300 text-xs flex items-start gap-2">
            <TriangleAlert className="w-4 h-4 shrink-0 mt-0.5" />
            {error}
          </div>
        )}

        {output && (
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-xs text-gray-500">
                <Terminal className="w-4 h-4" />
                {dryRun ? 'Prompt preview' : 'Output'}
              </span>
              <button
                type="button"
                onClick={handleCopy}
                className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-200 px-2 py-1 rounded-lg hover:bg-gray-800 transition-colors"
              >
                <ClipboardCopy className="w-3.5 h-3.5" />
                {copied ? 'Copied!' : 'Copy'}
              </button>
            </div>
            <pre className="text-xs font-mono bg-gray-950 border border-gray-800 rounded-xl p-4 max-h-72 overflow-auto whitespace-pre-wrap text-gray-300">
              {output}
            </pre>
            {artifactPath && (
              <p className="text-xs text-emerald-400 font-mono">
                Saved to: {artifactPath}
              </p>
            )}
          </div>
        )}
      </div>

      {/* Hypothesis archive */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-4">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-gray-100 flex items-center gap-2">
            <BookOpen className="w-4 h-4 text-purple-400" />
            Hypothesis archive
          </h3>
          <button
            type="button"
            onClick={fetchHypotheses}
            disabled={loadingHypo}
            className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-200 px-2 py-1 rounded-lg hover:bg-gray-800 transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loadingHypo ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>

        {hypoError && (
          <p className="text-xs text-red-400">{hypoError}</p>
        )}

        {hypotheses.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-gray-600 text-sm gap-2">
            <Sparkles className="w-8 h-8 text-gray-700" />
            <span>No hypothesis files in research/hypotheses/ yet.</span>
            <span className="text-xs">
              Run <span className="font-mono text-gray-400">lab propose</span> to generate the first one.
            </span>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {hypotheses.map((hypo) => (
              <div
                key={hypo.file}
                className="flex items-center justify-between gap-3 p-3 bg-gray-950 border border-gray-800 rounded-xl text-xs"
              >
                <div className="flex flex-col gap-0.5">
                  <span className="font-mono text-gray-200">{hypo.file}</span>
                  <span className="text-gray-500">
                    {formatDateTime(hypo.modified)} &middot; {hypo.size_kb} KB
                  </span>
                </div>
                {hypo.url && (
                  <a
                    href={hypo.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-amber-400 hover:text-amber-300 underline underline-offset-2 whitespace-nowrap"
                  >
                    View
                  </a>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
