const DEFAULT_API_BASE = 'http://localhost:8000';

/**
 * Where the API lives. `VITE_API_URL=same-origin` is for a deployment where one
 * reverse proxy serves both the dashboard and `/api` (deploy/Caddyfile): the bundle
 * then talks to whatever host it was loaded from, so the same build works behind a
 * domain, a Tailscale name or a bare IP. WebSockets follow (`https` -> `wss`).
 */
function resolveApiBase(): string {
  const raw = ((import.meta.env.VITE_API_URL as string | undefined) ?? '').trim();
  if (raw === 'same-origin') {
    return typeof window === 'undefined' ? DEFAULT_API_BASE : window.location.origin;
  }
  return raw.replace(/\/$/, '') || DEFAULT_API_BASE;
}

export const API_BASE = resolveApiBase();

export const apiUrl = (path: string) => `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;

export const staticReportUrl = (path: string) => apiUrl(path);

/**
 * Shared secret for the API gate (`API_TOKEN` in the backend `.env`). Empty = the API
 * relies on its origin check alone. It is compiled into the bundle, so it protects the
 * API from other web pages, not from someone who can already read this dashboard.
 */
export const API_TOKEN = ((import.meta.env.VITE_API_TOKEN as string | undefined) ?? '').trim();
