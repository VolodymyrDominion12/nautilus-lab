import React, { useState } from 'react';
import { Check, CheckCircle2, Copy, RefreshCw, Sparkles, Terminal, TriangleAlert } from 'lucide-react';

import { runPropose } from '../../services/api';

interface ProposePanelProps {
  /** A real (not dry) run saved this hypothesis file: show it in the archive. */
  onArtifact: (filename: string) => void;
}

/** `lab propose` from the dashboard: preview the prompt offline, or draft hypotheses. */
export const ProposePanel: React.FC<ProposePanelProps> = ({ onArtifact }) => {
  const [count, setCount] = useState(5);
  const [dryRun, setDryRun] = useState(true);
  const [journal, setJournal] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [running, setRunning] = useState(false);
  const [output, setOutput] = useState('');
  const [artifactPath, setArtifactPath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const handleRun = async () => {
    setRunning(true);
    setError(null);
    setArtifactPath(null);
    try {
      const result = await runPropose({
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
          const filename = result.artifact_path.split('/').pop();
          if (filename) onArtifact(filename);
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Propose failed');
    } finally {
      setRunning(false);
    }
  };

  const handleCopyOutput = () => {
    navigator.clipboard.writeText(output).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <>
      {/* Warning about requirements */}
      <div className="p-4 bg-amber-950/30 border border-amber-800/40 rounded-2xl text-xs text-amber-300 leading-relaxed flex items-start gap-3">
        <Sparkles className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
        <div>
          <span className="font-semibold">Requires:</span>{' '}
          <span className="font-mono bg-amber-950/80 px-1 py-0.5 rounded border border-amber-800/50">LLM_API_KEY</span> in{' '}
          <span className="font-mono">.env</span> (or configure via Settings). Without it the API returns an error (exit 1).
          Use <span className="font-semibold text-amber-200">Dry run</span> to preview the rendered prompt with 12 factor features without any network call.
        </div>
      </div>

      {/* Generation Panel */}
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
              placeholder="Leave blank to use default 01-generate-alphas.md"
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
            {running ? 'Running…' : dryRun ? 'Preview prompt' : 'Run propose'}
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
          <div className="flex flex-col gap-2 mt-2">
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-xs text-gray-400">
                <Terminal className="w-4 h-4 text-amber-400" />
                {dryRun ? 'Prompt preview (offline dry run)' : 'Proposal Output'}
              </span>
              <button
                type="button"
                onClick={handleCopyOutput}
                className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-200 px-2 py-1 rounded-lg hover:bg-gray-800 transition-colors"
              >
                {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                {copied ? 'Copied!' : 'Copy'}
              </button>
            </div>
            <pre className="text-xs font-mono bg-gray-950 border border-gray-800 rounded-xl p-4 max-h-72 overflow-auto whitespace-pre-wrap text-gray-300">
              {output}
            </pre>
            {artifactPath && (
              <p className="text-xs text-emerald-400 font-mono flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                Saved artifact: {artifactPath}
              </p>
            )}
          </div>
        )}
      </div>
    </>
  );
};
