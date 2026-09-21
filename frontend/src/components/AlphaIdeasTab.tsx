import React, { useEffect, useState } from 'react';
import {
  ArrowLeft,
  BookOpen,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  ExternalLink,
  Flame,
  Lightbulb,
  RefreshCw,
  Sparkles,
  Terminal,
  TrendingDown,
  TrendingUp,
  TriangleAlert,
} from 'lucide-react';
import {
  fetchHypotheses,
  fetchHypothesisDetail,
  runPropose,
} from '../services/api';
import type {
  HypothesisEntry,
  HypothesisItem,
  HypothesisRunDetail,
  ProposeResponse,
} from '../services/api';
import { formatDateTime } from '../lib/format';

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

  // Archive states
  const [hypotheses, setHypotheses] = useState<HypothesisEntry[]>([]);
  const [hypoError, setHypoError] = useState<string | null>(null);
  const [loadingHypo, setLoadingHypo] = useState(false);

  // Selected hypothesis run detail
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<HypothesisRunDetail | null>(null);
  const [loadingRun, setLoadingRun] = useState(false);
  const [copiedFormula, setCopiedFormula] = useState<string | null>(null);

  const loadHypothesesList = () => {
    setLoadingHypo(true);
    fetchHypotheses()
      .then((data) => {
        setHypotheses(data.hypotheses ?? []);
        setHypoError(null);
      })
      .catch((err) => {
        setHypoError(err instanceof Error ? err.message : 'Failed to load hypothesis files');
        setHypotheses([]);
      })
      .finally(() => setLoadingHypo(false));
  };

  useEffect(() => {
    loadHypothesesList();
  }, []);

  const handleSelectRun = async (file: string) => {
    setSelectedFile(file);
    setLoadingRun(true);
    try {
      const detail = await fetchHypothesisDetail(file);
      setSelectedRun(detail);
    } catch (err) {
      setHypoError(err instanceof Error ? err.message : 'Failed to load hypothesis details');
      setSelectedRun(null);
    } finally {
      setLoadingRun(false);
    }
  };

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
          loadHypothesesList();
          // Extract filename and auto-inspect
          const filename = result.artifact_path.split('/').pop();
          if (filename) {
            handleSelectRun(filename);
          }
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

  const handleCopyFormula = (formula: string, name: string) => {
    navigator.clipboard.writeText(formula).then(() => {
      setCopiedFormula(name);
      setTimeout(() => setCopiedFormula(null), 1500);
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
          <span className="font-mono text-xs text-amber-300/90">lab propose</span> — never runs on the backtest hot path.
        </p>
      </div>

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

      {/* Hypothesis Explorer & Archive */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 flex flex-col gap-5">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-3">
            {selectedFile && (
              <button
                type="button"
                onClick={() => {
                  setSelectedFile(null);
                  setSelectedRun(null);
                }}
                className="p-1.5 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-xl transition-colors flex items-center gap-1 text-xs"
                title="Back to file list"
              >
                <ArrowLeft className="w-4 h-4" />
              </button>
            )}
            <h3 className="text-sm font-semibold text-gray-100 flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-purple-400" />
              {selectedFile ? `Hypotheses: ${selectedFile}` : 'Hypothesis archive & Explorer'}
            </h3>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={loadHypothesesList}
              disabled={loadingHypo}
              className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-200 px-3 py-1.5 rounded-xl border border-gray-800 hover:bg-gray-800 transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loadingHypo ? 'animate-spin' : ''}`} />
              Refresh archive
            </button>
          </div>
        </div>

        {hypoError && (
          <div className="p-3 bg-red-950/40 border border-red-800/60 rounded-xl text-red-300 text-xs">
            {hypoError}
          </div>
        )}

        {/* If a specific run is selected, show its parsed hypotheses */}
        {selectedFile && (
          <div className="flex flex-col gap-4">
            {loadingRun ? (
              <div className="py-12 flex flex-col items-center justify-center gap-2 text-gray-400 text-sm">
                <RefreshCw className="w-6 h-6 animate-spin text-purple-400" />
                <span>Loading hypothesis cards...</span>
              </div>
            ) : selectedRun ? (
              <div className="flex flex-col gap-4">
                {/* Run Metadata Header */}
                <div className="bg-gray-950 border border-gray-800/80 rounded-xl p-4 flex flex-wrap items-center justify-between gap-3 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="px-2 py-0.5 rounded-md bg-purple-950/60 text-purple-300 border border-purple-800/50 font-mono">
                      Model: {selectedRun.model}
                    </span>
                    <span className="px-2 py-0.5 rounded-md bg-gray-800 text-gray-300">
                      As of: {selectedRun.as_of}
                    </span>
                    <span className="px-2 py-0.5 rounded-md bg-gray-800 text-gray-300">
                      {selectedRun.count_parsed} hypotheses
                    </span>
                    {selectedRun.count_flagged > 0 ? (
                      <span className="px-2 py-0.5 rounded-md bg-amber-950/60 text-amber-300 border border-amber-800/50 flex items-center gap-1">
                        <TriangleAlert className="w-3.5 h-3.5" />
                        {selectedRun.count_flagged} flagged
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded-md bg-emerald-950/60 text-emerald-300 border border-emerald-800/50 flex items-center gap-1">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        Valid DSL features
                      </span>
                    )}
                  </div>
                  <a
                    href={`/static_hypotheses/${selectedFile}`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-amber-400 hover:text-amber-300 flex items-center gap-1 hover:underline"
                  >
                    View raw JSON
                    <ExternalLink className="w-3 h-3" />
                  </a>
                </div>

                {/* Hypotheses Grid */}
                <div className="grid grid-cols-1 gap-4">
                  {selectedRun.hypotheses.map((item: HypothesisItem, idx: number) => {
                    const isCopied = copiedFormula === item.name;
                    const isLong = item.expected_sign === 1;
                    const hasUnknown = Boolean(item.unknown_identifiers && item.unknown_identifiers.length > 0);

                    return (
                      <div
                        key={item.name || idx}
                        className="bg-gray-950 border border-gray-800 rounded-2xl p-5 flex flex-col gap-3.5 hover:border-gray-700 transition-colors"
                      >
                        {/* Top info */}
                        <div className="flex items-start justify-between gap-3 flex-wrap">
                          <div className="flex items-center gap-2.5 flex-wrap">
                            <span className="w-6 h-6 rounded-lg bg-gray-900 border border-gray-800 flex items-center justify-center font-mono text-xs text-gray-400">
                              {idx + 1}
                            </span>
                            <span className="font-semibold text-gray-100 font-mono text-sm">
                              {item.name}
                            </span>
                            <span
                              className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                                isLong
                                  ? 'bg-emerald-950/80 text-emerald-400 border border-emerald-800/60'
                                  : 'bg-rose-950/80 text-rose-400 border border-rose-800/60'
                              }`}
                            >
                              {isLong ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
                              {isLong ? '+1 LONG' : '-1 SHORT'}
                            </span>
                            <span className="inline-flex items-center gap-1 text-xs text-gray-400 bg-gray-900 px-2 py-0.5 rounded-md border border-gray-800">
                              <Clock className="w-3 h-3 text-gray-500" />
                              {item.horizon_bars} bars
                            </span>
                          </div>

                          {hasUnknown ? (
                            <span className="text-xs text-amber-400 bg-amber-950/50 border border-amber-800/50 px-2 py-0.5 rounded-md flex items-center gap-1">
                              <TriangleAlert className="w-3.5 h-3.5" />
                              Unknown feature: {item.unknown_identifiers?.join(', ')}
                            </span>
                          ) : (
                            <span className="text-xs text-emerald-400 bg-emerald-950/40 border border-emerald-800/40 px-2 py-0.5 rounded-md flex items-center gap-1">
                              <CheckCircle2 className="w-3.5 h-3.5" />
                              DSL Verified
                            </span>
                          )}
                        </div>

                        {/* Formula block */}
                        <div className="flex flex-col gap-1">
                          <div className="flex items-center justify-between text-xs text-gray-500">
                            <span className="font-mono">Formula DSL</span>
                            <button
                              type="button"
                              onClick={() => handleCopyFormula(item.formula, item.name)}
                              className="flex items-center gap-1 text-amber-400 hover:text-amber-300 transition-colors"
                            >
                              {isCopied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                              {isCopied ? 'Copied!' : 'Copy formula'}
                            </button>
                          </div>
                          <div className="p-3 bg-gray-900 border border-gray-800/90 rounded-xl font-mono text-xs text-amber-200/90 break-all select-all">
                            {item.formula}
                          </div>
                        </div>

                        {/* Mechanism & Kill condition */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs pt-1">
                          <div className="p-3 bg-gray-900/60 border border-gray-800/60 rounded-xl flex flex-col gap-1.5">
                            <span className="font-semibold text-gray-300 flex items-center gap-1.5">
                              <Lightbulb className="w-3.5 h-3.5 text-amber-400" />
                              Економічний механізм (Mechanism)
                            </span>
                            <p className="text-gray-400 leading-relaxed">
                              {item.mechanism}
                            </p>
                          </div>

                          <div className="p-3 bg-gray-900/60 border border-gray-800/60 rounded-xl flex flex-col gap-1.5">
                            <span className="font-semibold text-rose-300 flex items-center gap-1.5">
                              <Flame className="w-3.5 h-3.5 text-rose-400" />
                              Умова спростування (Kill Condition)
                            </span>
                            <p className="text-gray-400 leading-relaxed">
                              {item.kill_condition}
                            </p>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </div>
        )}

        {/* List of files when none is selected */}
        {!selectedFile && (
          <>
            {hypotheses.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-10 text-gray-500 text-sm gap-2">
                <Sparkles className="w-8 h-8 text-gray-700" />
                <span>No hypothesis files in research/hypotheses/ yet.</span>
                <span className="text-xs text-gray-600">
                  Uncheck Dry run and click <span className="font-mono text-amber-400">Run propose</span> to draft your first alpha ideas.
                </span>
              </div>
            ) : (
              <div className="flex flex-col gap-2.5">
                {hypotheses.map((hypo) => (
                  <div
                    key={hypo.file}
                    onClick={() => handleSelectRun(hypo.file)}
                    className="flex items-center justify-between gap-4 p-4 bg-gray-950 border border-gray-800 hover:border-purple-800/60 rounded-xl text-xs cursor-pointer transition-all hover:bg-gray-950/80 group"
                  >
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-gray-200 font-medium group-hover:text-purple-300 transition-colors">
                          {hypo.file}
                        </span>
                        {hypo.model && (
                          <span className="px-1.5 py-0.5 rounded bg-purple-950/60 text-purple-300 border border-purple-900/50 text-[10px] font-mono">
                            {hypo.model}
                          </span>
                        )}
                        {hypo.as_of && (
                          <span className="px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 text-[10px]">
                            as of {hypo.as_of}
                          </span>
                        )}
                      </div>
                      <span className="text-gray-500">
                        {formatDateTime(hypo.modified)} &middot; {hypo.size_kb} KB
                        {typeof hypo.count_parsed === 'number' && ` · ${hypo.count_parsed} hypotheses`}
                      </span>
                    </div>

                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        className="px-3 py-1.5 rounded-lg bg-gray-900 group-hover:bg-purple-900/40 text-gray-300 group-hover:text-purple-200 font-medium border border-gray-800 group-hover:border-purple-700/50 transition-colors flex items-center gap-1"
                      >
                        Inspect
                        <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};
