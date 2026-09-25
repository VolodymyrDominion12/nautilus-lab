import React from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, BookOpen, CheckCircle2, ExternalLink, RefreshCw, Sparkles, TriangleAlert } from 'lucide-react';

import { formatDateTime } from '../../lib/format';
import type { HypothesisItem } from '../../services/api';
import { hypothesesQuery, hypothesisDetailQuery, queryKeys } from '../../services/queries';
import { HypothesisCard } from './HypothesisCard';
import type { TestInResearch } from './HypothesisCard';

interface HypothesisArchiveProps {
  /** The file whose hypotheses are shown; null shows the list of files. */
  selectedFile: string | null;
  onSelectFile: (file: string | null) => void;
  onTestInResearch?: TestInResearch;
}

/** The files in research/hypotheses/, and the parsed hypotheses of the one selected. */
export const HypothesisArchive: React.FC<HypothesisArchiveProps> = ({
  selectedFile,
  onSelectFile,
  onTestInResearch,
}) => {
  const queryClient = useQueryClient();
  const list = useQuery(hypothesesQuery());
  const detail = useQuery(hypothesisDetailQuery(selectedFile));
  const hypotheses = list.data?.hypotheses ?? [];
  const selectedRun = selectedFile ? (detail.data ?? null) : null;
  const loadingHypo = list.isFetching;
  const loadingRun = Boolean(selectedFile) && detail.isPending;
  const failure = list.error ?? (selectedFile ? detail.error : null);
  const hypoError = failure
    ? failure.message ||
      (failure === list.error ? 'Failed to load hypothesis files' : 'Failed to load hypothesis details')
    : null;
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.hypotheses });
  };

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 flex flex-col gap-5">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-3">
          {selectedFile && (
            <button
              type="button"
              onClick={() => onSelectFile(null)}
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
            onClick={refresh}
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
                {selectedRun.hypotheses.map((item: HypothesisItem, idx: number) => (
                  <HypothesisCard
                    key={item.name || idx}
                    item={item}
                    idx={idx}
                    onTestInResearch={onTestInResearch}
                  />
                ))}
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
                  onClick={() => onSelectFile(hypo.file)}
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
  );
};
