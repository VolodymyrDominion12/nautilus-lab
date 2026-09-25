import React, { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Sparkles } from 'lucide-react';

import { HypothesisArchive } from './alpha/HypothesisArchive';
import { ProposePanel } from './alpha/ProposePanel';
import type { TestInResearch } from './alpha/HypothesisCard';
import { queryKeys } from '../services/queries';

export interface AlphaIdeasTabProps {
  onTestInResearch?: TestInResearch;
}

/**
 * Offline LLM hypothesis drafting (`lab propose`) and the archive of drafted hypotheses.
 * A drafted file opens in the archive, and each hypothesis can go to the Research tab.
 */
export const AlphaIdeasTab: React.FC<AlphaIdeasTabProps> = ({ onTestInResearch }) => {
  const queryClient = useQueryClient();
  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  const showArtifact = (filename: string) => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.hypotheses });
    setSelectedFile(filename);
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

      <ProposePanel onArtifact={showArtifact} />

      <HypothesisArchive
        selectedFile={selectedFile}
        onSelectFile={setSelectedFile}
        onTestInResearch={onTestInResearch}
      />
    </div>
  );
};
