import { API_BASE, API_TOKEN } from '../config';

export const TOKEN_HEADER = 'X-Lab-Token';

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input.url;
}

/**
 * Attach the API token to every fetch aimed at the API, in one place.
 *
 * `services/api.ts` issues ~40 fetches; threading a header through each one would be
 * easy to forget on the next endpoint. Wrapping `fetch` once keeps the rule total.
 * Requests to any other origin pass through untouched, so the token never leaks.
 */
export function installApiAuth(): void {
  if (!API_TOKEN || typeof window === 'undefined') return;
  const original = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    if (!requestUrl(input).startsWith(API_BASE)) return original(input, init);
    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
    headers.set(TOKEN_HEADER, API_TOKEN);
    return original(input, { ...init, headers });
  };
}

/** WebSockets cannot carry custom headers; the API reads `?token=` for them instead. */
export function withWsToken(url: string): string {
  if (!API_TOKEN) return url;
  const separator = url.includes('?') ? '&' : '?';
  return `${url}${separator}token=${encodeURIComponent(API_TOKEN)}`;
}
