import React from 'react';
import { AlertTriangle } from 'lucide-react';

import type { DataSource } from '../../lib/researchForm';

interface ResearchBannersProps {
  /** The result on screen came from synthetic bars (not the toggle currently set). */
  syntheticResultOnScreen: boolean;
  source: DataSource;
  fullSample: boolean;
  catalogError: string | null;
  launchError: string | null;
  onDismissLaunchError: () => void;
  staleNotice: string | null;
}

/** Warnings above the form: synthetic data, in-sample only, catalog and launch errors. */
export const ResearchBanners: React.FC<ResearchBannersProps> = ({
  syntheticResultOnScreen,
  source,
  fullSample,
  catalogError,
  launchError,
  onDismissLaunchError,
  staleNotice,
}) => (
  <>
    {(syntheticResultOnScreen || source === 'synthetic') && (
      <div className="p-3 bg-amber-950/40 border border-amber-800/60 rounded-xl flex items-center gap-3 text-amber-300 text-xs font-medium">
        <AlertTriangle className="w-4 h-4 flex-shrink-0" />
        <span>
          {syntheticResultOnScreen
            ? 'The result below came from synthetic bars — a smoke test of the plumbing, never evidence of an edge.'
            : 'Synthetic bars are for smoke tests only and can produce absurd returns. Real research needs the Parquet catalog with walk-forward folds.'}
        </span>
      </div>
    )}

    {source === 'catalog' && fullSample && (
      <div className="p-3 bg-amber-950/40 border border-amber-800/60 rounded-xl flex items-center gap-3 text-amber-300 text-xs font-medium">
        <AlertTriangle className="w-4 h-4 flex-shrink-0" />
        <span>
          Full-sample runs use the whole series with no split, so the numbers are in-sample only.
          They are not an out-of-sample report.
        </span>
      </div>
    )}

    {catalogError && (
      <div className="p-3 bg-red-950/40 border border-red-800/60 rounded-xl flex items-center gap-3 text-red-300 text-xs">
        <AlertTriangle className="w-4 h-4 flex-shrink-0" />
        <span>Catalog error: {catalogError}</span>
      </div>
    )}

    {launchError && (
      <div className="p-3 bg-red-950/40 border border-red-800/60 rounded-xl flex items-center justify-between gap-3 text-red-300 text-xs">
        <span className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          {launchError}
        </span>
        <button type="button" onClick={onDismissLaunchError} className="text-red-400/70 hover:text-red-300">
          dismiss
        </button>
      </div>
    )}

    {staleNotice && (
      <div className="p-3 bg-amber-950/40 border border-amber-800/60 rounded-xl flex items-center gap-3 text-amber-300 text-xs">
        <AlertTriangle className="w-4 h-4 flex-shrink-0" />
        <span>{staleNotice}</span>
      </div>
    )}
  </>
);
