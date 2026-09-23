const DEFAULT_API_BASE = 'http://localhost:8000';

export const API_BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') || DEFAULT_API_BASE;

export const apiUrl = (path: string) => `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;

export const staticReportUrl = (path: string) => apiUrl(path);

/**
 * Shared secret for the API gate (`API_TOKEN` in the backend `.env`). Empty = the API
 * relies on its origin check alone. It is compiled into the bundle, so it protects the
 * API from other web pages, not from someone who can already read this dashboard.
 */
export const API_TOKEN = ((import.meta.env.VITE_API_TOKEN as string | undefined) ?? '').trim();
