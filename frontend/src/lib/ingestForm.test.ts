import { describe, expect, test } from 'vitest';

import {
  DEFAULT_FORM,
  archiveTarget,
  buildIngestRequest,
  ingestWarnings,
  symbolPresets,
} from './ingestForm';
import type { IngestFormState } from './ingestForm';

const form = (patch: Partial<IngestFormState>): IngestFormState => ({ ...DEFAULT_FORM, ...patch });

describe('ingest form', () => {
  test('archive requests never carry the selected catalog', () => {
    const body = buildIngestRequest(form({ interval: '4h' }), 'catalog_spot_1d', false);
    expect(body.catalog).toBeUndefined();
    expect(body.source).toBe('archive');
    expect(body.market).toBe('spot');
    expect(body.interval).toBe('4h');
  });

  test('archive targets one catalog per market and interval', () => {
    expect(archiveTarget(form({ market: 'um', interval: '4h' }))).toBe('catalog_perp_4h');
    expect(archiveTarget(form({ series: 'premium_index', interval: '1d' }))).toBe(
      'catalog_perp_1d',
    );
    expect(archiveTarget(form({ series: 'funding' }))).toContain('catalog_perp_*');
  });

  test('funding has no interval and no market', () => {
    const body = buildIngestRequest(form({ series: 'funding' }), '', false);
    expect(body.interval).toBeUndefined();
    expect(body.market).toBeUndefined();
  });

  test('rest requests keep the selected catalog and drop the window where it has none', () => {
    const incremental = buildIngestRequest(form({ source: 'rest' }), 'catalog_spot_1d', true);
    expect(incremental.catalog).toBe('catalog_spot_1d');
    expect(incremental.incremental).toBe(true);
    expect(incremental.start).toBeUndefined();

    const depth = buildIngestRequest(
      form({ source: 'rest', series: 'depth', end: '2026-01-01' }),
      '',
      false,
    );
    expect(depth.start).toBeUndefined();
    expect(depth.end).toBeUndefined();
  });

  test('only the archive offers the whole universe', () => {
    expect(symbolPresets(form({})).some((preset) => preset.value === 'all')).toBe(true);
    expect(symbolPresets(form({ source: 'rest' })).some((preset) => preset.value === 'all')).toBe(
      false,
    );
  });

  test('warnings: inverted window, huge sub-hour series, all symbols, rest funding', () => {
    const now = new Date('2026-10-03T00:00:00Z');
    expect(ingestWarnings(form({ start: '2026-02-01', end: '2026-01-01' }), now)).toContain(
      'Start must be before end.',
    );
    expect(ingestWarnings(form({ interval: '1m', start: '2020-01-01' }), now).join(' ')).toMatch(
      /very large series/,
    );
    expect(ingestWarnings(form({ symbols: 'all' }), now).join(' ')).toMatch(/hundreds/);
    expect(ingestWarnings(form({ source: 'rest', series: 'funding' }), now).join(' ')).toMatch(
      /archive is the reference/,
    );
    expect(ingestWarnings(form({}), now)).toEqual([]);
  });
});
