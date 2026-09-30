import React from 'react';
import type { BatchRoute } from '../../lib/batch';
import { BatchListPage } from './BatchListPage';
import { BatchTablePage } from './BatchTablePage';
import { RunPage } from './RunPage';

/** The batch-backtest pages, picked by the route in the address (`lib/batch.ts`). */
export const BatchSection: React.FC<{ route: BatchRoute }> = ({ route }) => {
  if (route.page === 'batch') return <BatchTablePage key={route.batchId} batchId={route.batchId} />;
  if (route.page === 'run') {
    return (
      <RunPage
        key={`${route.batchId}/${route.cellId}`}
        batchId={route.batchId}
        cellId={route.cellId}
        fold={route.fold}
        tab={route.tab}
      />
    );
  }
  return <BatchListPage />;
};
