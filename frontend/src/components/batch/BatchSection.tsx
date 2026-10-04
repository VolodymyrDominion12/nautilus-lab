import React from 'react';
import type { BatchRoute } from '../../lib/batch';
import { BatchListPage } from './BatchListPage';
import { BatchTablePage } from './BatchTablePage';
import { RunPage } from './RunPage';

/** What the Research tab needs to re-run one cell as a candidate (docs/35 §8 п.21). */
export interface PromoteCandidate {
  robot: string;
  instrumentId?: string;
  folds?: number;
  notes?: string;
}

interface BatchSectionProps {
  route: BatchRoute;
  /** Absent when the dashboard cannot switch tabs (tests, a standalone section). */
  onPromoteCandidate?: (cfg: PromoteCandidate) => void;
}

/** The batch-backtest pages, picked by the route in the address (`lib/batch.ts`). */
export const BatchSection: React.FC<BatchSectionProps> = ({ route, onPromoteCandidate }) => {
  if (route.page === 'batch') return <BatchTablePage key={route.batchId} batchId={route.batchId} />;
  if (route.page === 'run') {
    return (
      <RunPage
        key={`${route.batchId}/${route.cellId}`}
        batchId={route.batchId}
        cellId={route.cellId}
        fold={route.fold}
        tab={route.tab}
        onPromoteCandidate={onPromoteCandidate}
      />
    );
  }
  return <BatchListPage />;
};
