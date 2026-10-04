import { beforeEach, describe, expect, test } from 'vitest';
import {
  BATCH_FORM_STORAGE_KEY,
  loadStoredBatchForm,
  saveStoredBatchForm,
  type StoredBatchForm,
} from './batchForm';

describe('batchForm storage', () => {
  let mockStore: Record<string, string>;
  let mockStorage: Storage;

  beforeEach(() => {
    mockStore = {};
    mockStorage = {
      getItem: (key: string) => mockStore[key] ?? null,
      setItem: (key: string, value: string) => {
        mockStore[key] = value;
      },
      removeItem: (key: string) => {
        delete mockStore[key];
      },
      clear: () => {
        mockStore = {};
      },
      key: (index: number) => Object.keys(mockStore)[index] ?? null,
      get length() {
        return Object.keys(mockStore).length;
      },
    };
  });

  test('returns null when nothing is stored', () => {
    expect(loadStoredBatchForm(mockStorage)).toBeNull();
  });

  test('round-trips batch form state', () => {
    const state: StoredBatchForm = {
      robots: ['regime', 'ema'],
      symbols: ['BTCUSDT', 'SOLUSDT'],
      catalog: 'catalog_perp_4h',
      barInterval: '4h',
      folds: 6,
      isFraction: 0.8,
      embargoBars: 15,
      costProfile: 'stress_x1_5',
    };
    saveStoredBatchForm(state, mockStorage);
    expect(loadStoredBatchForm(mockStorage)).toEqual(state);
  });

  test('handles corrupted storage gracefully', () => {
    mockStorage.setItem(BATCH_FORM_STORAGE_KEY, 'invalid-json{{{');
    expect(loadStoredBatchForm(mockStorage)).toBeNull();
  });
});
