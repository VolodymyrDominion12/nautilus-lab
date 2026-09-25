/** The dashboard's tabs, and which tab shows each background job. */
import type { JobKey } from './services/api';

export type TabId =
  | 'home'
  | 'research'
  | 'catalog'
  | 'strategies'
  | 'ml'
  | 'journal'
  | 'paper'
  | 'scan'
  | 'alpha'
  | 'settings';

export const JOB_TABS: Record<JobKey, TabId> = {
  research: 'research',
  ingest: 'catalog',
  ml_train: 'ml',
  paper: 'paper',
};
