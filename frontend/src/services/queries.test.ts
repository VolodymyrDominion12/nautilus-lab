/**
 * The polling contract of the query cache (docs/27 E-2.5): polling pauses on a hidden
 * tab, the ingest log is read only while an ingest runs, and each query has its own key.
 */
import { describe, expect, test } from 'vitest';

import {
  INGEST_LOG_POLL_MS,
  STATUS_POLL_MS,
  createQueryClient,
  ingestLogQuery,
  queryKeys,
  statusQuery,
} from './queries';

describe('query client defaults', () => {
  test('a hidden tab does not poll', () => {
    const defaults = createQueryClient().getDefaultOptions().queries;
    expect(defaults?.refetchIntervalInBackground).toBe(false);
  });

  test('a failed request is retried once, not three times', () => {
    expect(createQueryClient().getDefaultOptions().queries?.retry).toBe(1);
  });
});

describe('query options', () => {
  test('the status polls on its interval', () => {
    expect(statusQuery('catalog').refetchInterval).toBe(STATUS_POLL_MS);
  });

  test('the ingest log is read only while an ingest runs', () => {
    expect(ingestLogQuery(false).enabled).toBe(false);
    expect(ingestLogQuery(false).refetchInterval).toBe(false);
    expect(ingestLogQuery(true).enabled).toBe(true);
    expect(ingestLogQuery(true).refetchInterval).toBe(INGEST_LOG_POLL_MS);
  });

  test('keys of different catalogs differ', () => {
    expect(queryKeys.status('a')).not.toEqual(queryKeys.status('b'));
    expect(queryKeys.catalog('a')).not.toEqual(queryKeys.dataHealth('a'));
  });
});
