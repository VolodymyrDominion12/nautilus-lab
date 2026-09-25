/**
 * Browser smoke test (docs/27 E-2.4): the built dashboard against the real API.
 *
 *   npm run e2e            # starts both servers, runs e2e/*.e2e.ts in Chromium
 *
 * The API is `scripts/e2e_server.py`: `create_app` with synthetic markets instead of
 * Binance. It needs no network or keys and uses no journal. It runs on its own port,
 * so a dashboard API on :8000 can stay up. The dashboard is a production build
 * (`vite build`, then `vite preview`): that is what ships, and it needs no file
 * watcher (see README, ENOSPC).
 */
import { defineConfig, devices } from '@playwright/test';

import { API, API_PORT, WEB, WEB_PORT } from './e2e/servers.ts';

const CI = Boolean(process.env.CI);

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.ts',
  // One API process holds the sessions: tests run in order, not against each other.
  workers: 1,
  fullyParallel: false,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: WEB,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `uv run python scripts/e2e_server.py --port ${API_PORT} --origin ${WEB}`,
      cwd: '..',
      url: `${API}/healthz`,
      reuseExistingServer: !CI,
      timeout: 120_000,
    },
    {
      command: `npx vite build --outDir dist-e2e --emptyOutDir && npx vite preview --outDir dist-e2e --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: WEB,
      reuseExistingServer: !CI,
      timeout: 120_000,
      // Vite reads variables that are already set before any .env file, so a local
      // .env.local cannot point the smoke build at another API or add a token.
      env: { VITE_API_URL: API, VITE_API_TOKEN: '' },
    },
  ],
});
