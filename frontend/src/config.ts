const DEFAULT_API_BASE = 'http://localhost:8000';

export const API_BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') || DEFAULT_API_BASE;

export const apiUrl = (path: string) => `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;

export const staticReportUrl = (path: string) => apiUrl(path);
