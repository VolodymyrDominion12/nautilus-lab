/**
 * Server state for the dashboard: one TanStack Query cache instead of a `setInterval`
 * in each component (docs/27 E-2.5).
 *
 * The client gives three things the hand-written polling did not:
 * - A hidden browser tab stops polling (`refetchIntervalInBackground: false`) and
 *   catches up when it is shown again. A dashboard left open overnight no longer
 *   hits the API every 1.5 s.
 * - Two panels that read the same thing (the status in the sidebar and a tab, the
 *   catalog list in the header and the Catalog tab) share one request and one answer.
 * - A finished job invalidates the data it changed, by key, from wherever it finished.
 *
 * Query keys and options live only here; components use the `*Query` factories with
 * `useQuery`, so a key cannot be spelled two ways.
 */
import { QueryClient, queryOptions } from '@tanstack/react-query';

import {
  fetchCatalog,
  fetchCatalogs,
  fetchCommandCenter,
  fetchDataHealth,
  fetchHypotheses,
  fetchHypothesisDetail,
  fetchIngestLog,
  fetchReports,
  fetchResearchLog,
  fetchStatus,
  fetchStrategies,
} from './api';

/** How often the sidebar re-reads /api/status (job badges, catalog counts). */
export const STATUS_POLL_MS = 15_000;
/** How often the front page re-reads jobs and the last result. */
export const COMMAND_CENTER_POLL_MS = 5_000;
/** How often a running ingest's log is re-read. */
export const INGEST_LOG_POLL_MS = 1_500;
/** How often a running research job's log and summary are re-read. */
export const RESEARCH_LOG_POLL_MS = 1_000;

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // TanStack's default, stated because E-2.5's acceptance depends on it.
        refetchIntervalInBackground: false,
        refetchOnWindowFocus: true,
        // A local API either answers or is down; retrying three times with backoff
        // only delays the "Cannot reach the API" banner.
        retry: 1,
        staleTime: 2_000,
      },
    },
  });
}

export const queryKeys = {
  status: (catalogPath: string) => ['status', catalogPath] as const,
  catalog: (catalogPath: string) => ['catalog', catalogPath] as const,
  catalogs: ['catalogs'] as const,
  dataHealth: (catalogPath: string) => ['data-health', catalogPath] as const,
  strategies: ['strategies'] as const,
  ingestLog: ['ingest-log'] as const,
  researchLog: ['research-log'] as const,
  reports: ['reports'] as const,
  commandCenter: ['command-center'] as const,
  hypotheses: ['hypotheses'] as const,
  hypothesis: (file: string) => ['hypotheses', file] as const,
};

export const statusQuery = (catalogPath: string) =>
  queryOptions({
    queryKey: queryKeys.status(catalogPath),
    queryFn: () => fetchStatus(catalogPath),
    refetchInterval: STATUS_POLL_MS,
  });

export const catalogQuery = (catalogPath: string) =>
  queryOptions({
    queryKey: queryKeys.catalog(catalogPath),
    queryFn: () => fetchCatalog(catalogPath),
    refetchInterval: STATUS_POLL_MS,
  });

export const catalogsQuery = () =>
  queryOptions({ queryKey: queryKeys.catalogs, queryFn: fetchCatalogs });

/** Coverage of the optional series. Missing coverage is shown as "no table", not an error. */
export const dataHealthQuery = (catalogPath: string) =>
  queryOptions({
    queryKey: queryKeys.dataHealth(catalogPath),
    queryFn: () => fetchDataHealth(catalogPath),
    retry: false,
  });

export const strategiesQuery = () =>
  queryOptions({ queryKey: queryKeys.strategies, queryFn: fetchStrategies, staleTime: 60_000 });

export const ingestLogQuery = (polling: boolean) =>
  queryOptions({
    queryKey: queryKeys.ingestLog,
    queryFn: fetchIngestLog,
    enabled: polling,
    refetchInterval: polling ? INGEST_LOG_POLL_MS : false,
  });

export const researchLogQuery = (polling: boolean) =>
  queryOptions({
    queryKey: queryKeys.researchLog,
    queryFn: fetchResearchLog,
    enabled: polling,
    refetchInterval: polling ? RESEARCH_LOG_POLL_MS : false,
  });

/** HTML tearsheets in reports/, newest first. */
export const reportsQuery = () => queryOptions({ queryKey: queryKeys.reports, queryFn: fetchReports });

export const commandCenterQuery = () =>
  queryOptions({
    queryKey: queryKeys.commandCenter,
    queryFn: fetchCommandCenter,
    refetchInterval: COMMAND_CENTER_POLL_MS,
  });

/** Hypothesis files in research/hypotheses/; `hypothesis(file)` shares the prefix. */
export const hypothesesQuery = () =>
  queryOptions({ queryKey: queryKeys.hypotheses, queryFn: fetchHypotheses });

/** One file's parsed hypotheses; disabled while no file is selected. */
export const hypothesisDetailQuery = (file: string | null) =>
  queryOptions({
    queryKey: queryKeys.hypothesis(file ?? ''),
    queryFn: () => fetchHypothesisDetail(file ?? ''),
    enabled: file != null,
  });

/** Everything an ingest can change: the catalog, its coverage, the status counts. */
export const catalogDataKeys = [
  ['catalog'],
  ['catalogs'],
  ['data-health'],
  ['status'],
] as const;
