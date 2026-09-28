/**
 * Smoke test (docs/27 E-2.4): the dashboard opens and reads the API, a live paper
 * session is visible, and its WebSocket stream connects.
 *
 * This tests the wiring, not trading logic: CORS and the origin gate, `VITE_API_URL`
 * baked into the build, the sessions REST list, the `/api/paper/live-stream` socket.
 * These are the places where a deploy breaks while every unit test stays green.
 * Market data is synthetic (scripts/e2e_server.py).
 */
import { expect, test, type Page } from '@playwright/test';

import { API } from './servers.ts';

/** Uncaught exceptions on the page fail the test, not only a missing element. */
function collectPageErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  return errors;
}

test('the dashboard opens and reads the API', async ({ page }) => {
  const errors = collectPageErrors(page);
  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Nautilus Lab' })).toBeVisible();
  // Rendered only from a successful /api/status: the build reached the API.
  await expect(page.getByText('Safety: fail-closed')).toBeVisible();
  // The front page (Command Center) reads /api/command-center through the query cache.
  await expect(page.getByRole('heading', { name: 'Command Center' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Last measured result' })).toBeVisible();
  await expect(page.getByText(/Cannot reach|not allowed to use this API/)).toHaveCount(0);

  // The catalog tab reads three queries (catalog, catalog list, coverage) at once.
  await page.getByRole('button', { name: 'Parquet Catalog' }).click();
  await expect(page.getByRole('heading', { name: 'Parquet Data Catalog' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Ingest Binance data' })).toBeVisible();

  // The research tab: form, preflight and result panels render from the shared queries.
  await page.getByRole('button', { name: 'Research & Backtest' }).click();
  await expect(page.getByRole('heading', { name: 'Research Lab' })).toBeVisible();
  await expect(page.getByRole('button', { name: /Run research|Run blocked/ })).toBeVisible();

  await page.getByRole('button', { name: 'Alpha Ideas' }).click();
  await expect(page.getByRole('heading', { name: 'Propose hypotheses' })).toBeVisible();

  expect(errors).toEqual([]);
});

test('a live paper session is listed and its stream connects', async ({ page, request }) => {
  const errors = collectPageErrors(page);
  const name = `e2e-smoke-${Date.now().toString(36)}`;
  const started = await request.post(`${API}/api/paper/sessions`, {
    data: { symbol: 'BTCUSDT', interval: '1m', robot: 'regime', name },
  });
  expect(started.ok(), await started.text()).toBe(true);
  const { session_id: sessionId } = (await started.json()) as { session_id: string };

  try {
    await page.goto('/');
    await page.getByRole('button', { name: 'Trading Terminal' }).click();

    // The sessions panel lists it, and the terminal opens on the first running session.
    await expect(page.getByRole('cell', { name })).toBeVisible();
    await expect(page.getByText('Stream Active')).toBeVisible();

    // Synthetic closed bars keep arriving: the "Last bar" cell must move.
    const row = page.getByRole('row').filter({ hasText: name });
    const lastBar = row.getByRole('cell').nth(8);
    const before = await lastBar.innerText();
    await expect(lastBar).not.toHaveText(before, { timeout: 20_000 });
  } finally {
    await request.post(`${API}/api/paper/sessions/${encodeURIComponent(sessionId)}/stop`);
  }

  expect(errors).toEqual([]);
});

test('the trade list and a trade page open from the session', async ({ page, request }) => {
  const errors = collectPageErrors(page);
  const name = `e2e-trades-${Date.now().toString(36)}`;
  const started = await request.post(`${API}/api/paper/sessions`, {
    data: { symbol: 'BTCUSDT', interval: '1m', robot: 'regime', name },
  });
  expect(started.ok(), await started.text()).toBe(true);
  const { session_id: sessionId } = (await started.json()) as { session_id: string };

  try {
    await page.goto('/');
    await page.getByRole('button', { name: 'Trading Terminal' }).click();
    await page.getByRole('button', { name: /Trades & Analysis/ }).click();

    // The panel reads `GET /api/paper/sessions/{key}/trades` and lists what it finds. This
    // server runs no decision log, so the honest answer is an empty list with the reason —
    // not a spinner, an error banner, or a table that looks like a robot that never traded.
    await expect(page.getByText('Кожен рядок веде на окрему сторінку розбору')).toBeVisible();
    await expect(page.getByText(/Угод:/)).toBeVisible();
  } finally {
    await request.post(`${API}/api/paper/sessions/${encodeURIComponent(sessionId)}/stop`);
  }

  // A trade page has an address of its own: opening the fragment directly renders it (this
  // is the link the list puts on every row), and a trade that is not in the log says so
  // instead of showing a blank page.
  await page.goto(
    `/#/trade?session=${encodeURIComponent(sessionId)}&id=${encodeURIComponent(sessionId)}-trade-1` +
      '&instrument=BTCUSDT&interval=1m&origin=paper',
  );
  await expect(page.getByRole('button', { name: 'Назад' })).toBeVisible();
  await expect(page.getByText('Угоду не вдалося прочитати')).toBeVisible();

  // Back returns to the dashboard tab the link was opened from, not to a fresh page.
  await page.getByRole('button', { name: 'Назад' }).click();
  await expect(page.getByRole('heading', { name: 'Nautilus Lab' })).toBeVisible();

  expect(errors).toEqual([]);
});
