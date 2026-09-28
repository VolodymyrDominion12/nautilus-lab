/**
 * The logic behind the trade pages: the link, the marker geometry and the money labels.
 *
 * Three things here have already gone wrong in this dashboard and are pinned by tests:
 * a marker that lands on no candle is dropped silently by lightweight-charts (decisions
 * are stamped with the bar's end, candles with their open); a route that cannot be parsed
 * back is a link that opens nothing; and a PnL shown without its basis reads as account
 * PnL even when it is price arithmetic on an assumed size.
 */
import { describe, expect, test } from 'vitest';

import {
  buildTradeHash,
  describeMissingDetail,
  describePnlBasis,
  formatDuration,
  indicatorRows,
  outcomeLabel,
  parseTradeHash,
  snapToBar,
  tradeMarkers,
  tradePriceLines,
} from './trades';
import type { TradeChartBar } from '../services/api';

const bar = (time: number, close = 100): TradeChartBar => ({
  time,
  open: close - 1,
  high: close + 2,
  low: close - 2,
  close,
  volume: 1,
});

describe('a trade has an address of its own', () => {
  test('a route survives the round trip through the fragment', () => {
    const hash = buildTradeHash({
      session: 'ema-eth-159a09',
      id: 'ema-eth-159a09-trade-3',
      instrument: 'ETH/USDT.SIM',
      interval: '1m',
      catalog: 'catalog',
      title: 'ema-eth',
      origin: 'paper',
    });

    expect(hash.startsWith('#/trade?')).toBe(true);
    expect(parseTradeHash(hash)).toEqual({
      session: 'ema-eth-159a09',
      id: 'ema-eth-159a09-trade-3',
      instrument: 'ETH/USDT.SIM',
      interval: '1m',
      catalog: 'catalog',
      title: 'ema-eth',
      origin: 'paper',
    });
  });

  test('a fragment that is not a trade route is not one', () => {
    expect(parseTradeHash('')).toBeNull();
    expect(parseTradeHash('#/research')).toBeNull();
    // Half a route: an id with no session names no log to read.
    expect(parseTradeHash('#/trade?id=trade-1')).toBeNull();
    expect(parseTradeHash('#/trade?session=abc')).toBeNull();
  });

  test('an unknown origin is dropped instead of echoed into the page', () => {
    expect(parseTradeHash('#/trade?session=a&id=b&origin=whatever')?.origin).toBeUndefined();
  });

  test('a session id with unusual characters survives encoding', () => {
    const route = { session: 'run 1/x', id: 'trade 2' };
    expect(parseTradeHash(buildTradeHash(route))).toMatchObject(route);
  });
});

describe('markers land on candles that exist', () => {
  const bars = [bar(1000), bar(1060), bar(1120), bar(1180)];

  test('a decision stamped with the bar close snaps to that candle', () => {
    // The log keeps the bar's `ts_event` (00:59:59.999 for a one-minute bar) while the
    // candle is plotted at the time the API reports; the two never match exactly.
    expect(snapToBar(1059.999, [1000, 1060, 1120])).toBe(1060);
    expect(snapToBar(1060, [1000, 1060, 1120])).toBe(1060);
  });

  test('a chart of another interval still lands on the candle containing the decision', () => {
    // Hourly candles, a decision inside the first hour: entry is marked on that candle
    // rather than dropped for not matching a timestamp.
    const hourly = [3599, 7199, 10799];
    expect(snapToBar(300, hourly)).toBe(3599);
  });

  test('a trade older than the fetched window gets no marker, not a wrong one', () => {
    expect(snapToBar(10, [1000, 1060, 1120, 1180])).toBeNull();
    expect(snapToBar(1000, [])).toBeNull();
  });

  test('a long trade gets an entry below the bar and an exit above it', () => {
    const markers = tradeMarkers(
      {
        side: 'LONG',
        entry_time: new Date(1060 * 1000).toISOString(),
        exit_time: new Date(1180 * 1000).toISOString(),
        exit_outcome: 'TAKE_PROFIT',
      },
      bars,
    );

    expect(markers.map((m) => [m.time, m.position, m.shape])).toEqual([
      [1060, 'belowBar', 'arrowUp'],
      [1180, 'aboveBar', 'arrowDown'],
    ]);
    expect(markers[1]!.color).toBe('#10b981');
  });

  test('a short trade flips the arrows and keeps the stop red', () => {
    const markers = tradeMarkers(
      {
        side: 'SHORT',
        entry_time: new Date(1060 * 1000).toISOString(),
        exit_time: new Date(1120 * 1000).toISOString(),
        exit_outcome: 'STOP_LOSS',
      },
      bars,
    );

    expect(markers[0]!.shape).toBe('arrowDown');
    expect(markers[0]!.position).toBe('aboveBar');
    expect(markers[1]!.shape).toBe('arrowUp');
    expect(markers[1]!.color).toBe('#ef4444');
  });

  test('an open trade has an entry marker and no exit marker', () => {
    const markers = tradeMarkers(
      { side: 'LONG', entry_time: new Date(1060 * 1000).toISOString(), exit_time: null },
      bars,
    );

    expect(markers).toHaveLength(1);
    expect(markers[0]!.text).toBe('Вхід LONG');
  });

  test('an exit on the entry bar does not stack two arrows on one candle', () => {
    const markers = tradeMarkers(
      {
        side: 'LONG',
        entry_time: new Date(1060 * 1000).toISOString(),
        exit_time: new Date(1060 * 1000).toISOString(),
        exit_outcome: 'EXIT',
      },
      bars,
    );

    expect(markers).toHaveLength(1);
  });
});

describe('price lines say what they are', () => {
  test('a closed trade draws entry, exit, stop and target', () => {
    const lines = tradePriceLines({
      entry_price: 100,
      exit_price: 110,
      mark_price: null,
      stop_loss: 95,
      take_profit: 120,
      status: 'CLOSED',
    });

    expect(lines.map((line) => [line.title, line.price])).toEqual([
      ['Вхід', 100],
      ['Вихід', 110],
      ['Стоп-лос', 95],
      ['Тейк-профіт', 120],
    ]);
  });

  test('an open trade marks the current price instead of an exit', () => {
    const lines = tradePriceLines({
      entry_price: 100,
      exit_price: null,
      mark_price: 104,
      stop_loss: null,
      take_profit: null,
      status: 'OPEN',
    });

    expect(lines.map((line) => line.title)).toEqual(['Вхід', 'Поточна ціна']);
  });

  test('a trade with no stop or target draws neither', () => {
    const lines = tradePriceLines({
      entry_price: 100,
      exit_price: 99,
      mark_price: null,
      stop_loss: null,
      take_profit: null,
      status: 'CLOSED',
    });

    expect(lines).toHaveLength(2);
  });
});

describe('the money number says how it was produced', () => {
  test('a backtest PnL admits the size was assumed and fees are missing', () => {
    const text = describePnlBasis({
      pnl_source: 'price_delta',
      qty_known: false,
      fee_known: false,
      status: 'CLOSED',
    });

    expect(text).toContain('розмір позиції');
    expect(text).toContain('Комісії не враховано');
  });

  test('a filled paper trade says the ledger produced it', () => {
    expect(
      describePnlBasis({ pnl_source: 'fills', qty_known: true, fee_known: true, status: 'CLOSED' }),
    ).toContain('З журналу угод сесії');
  });

  test('an open position is a mark, not a result', () => {
    expect(
      describePnlBasis({ pnl_source: 'mark', qty_known: true, fee_known: true, status: 'OPEN' }),
    ).toContain('Плаваючий результат');
  });
});

describe('indicators are compared entry against exit', () => {
  test('every indicator either side is listed, with its change', () => {
    const rows = indicatorRows({ er: '0.62', slope: '18.86' }, { er: '0.16', atr: '12' });

    expect(rows.map((row) => row.name)).toEqual(['atr', 'er', 'slope']);
    const er = rows.find((row) => row.name === 'er');
    expect(er?.entry).toBeCloseTo(0.62);
    expect(er?.exit).toBeCloseTo(0.16);
    expect(er?.delta).toBeCloseTo(-0.46);
  });

  test('a value that is not a number is not read as zero', () => {
    const rows = indicatorRows({ regime: 'uptrend' }, {});
    expect(rows[0]!.entry).toBeNull();
    expect(rows[0]!.delta).toBeNull();
  });

  test('no indicators on either side is an empty list, not a crash', () => {
    expect(indicatorRows(undefined, undefined)).toEqual([]);
  });
});

describe('durations and outcomes read like Ukrainian', () => {
  test('a duration carries its bar count', () => {
    expect(formatDuration(7200, 3)).toBe('2г 0хв · 3 бар.');
    expect(formatDuration(45)).toBe('45с');
    expect(formatDuration(null)).toBe('—');
  });

  test('known outcomes are translated and unknown ones are passed through', () => {
    expect(outcomeLabel('TAKE_PROFIT')).toBe('Тейк-профіт');
    expect(outcomeLabel('SOMETHING_NEW')).toBe('SOMETHING_NEW');
    expect(outcomeLabel(null)).toBe('—');
  });
});

describe('missing detail is announced, not rendered as empty', () => {
  test('a backtest log with no steps says the chain was never written', () => {
    const text = describeMissingDetail({
      decisions: [{ ts: '2026-09-25T14:00:00+00:00', outcome: 'ENTRY_OPENED' }],
    } as never);

    expect(text).toContain('steps');
  });

  test('a log with steps needs no excuse', () => {
    expect(
      describeMissingDetail({
        decisions: [
          { ts: '2026-09-25T14:00:00+00:00', outcome: 'ENTRY_OPENED', steps: [{ stage: 'risk' }] },
        ],
      } as never),
    ).toBeNull();
  });

  test('a trade with no records at all says so', () => {
    expect(describeMissingDetail({ decisions: [] } as never)).toContain('немає жодного запису');
  });
});
