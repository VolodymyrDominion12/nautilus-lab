export const BATCH_FORM_STORAGE_KEY = 'nautilus-lab:batch-form:v1';

export interface StoredBatchForm {
  robots?: string[];
  symbols?: string[];
  extraSymbols?: string;
  barInterval?: string;
  catalog?: string;
  days?: number | '';
  folds?: number;
  isFraction?: number;
  embargoBars?: number;
  parallel?: number;
  label?: string;
  envText?: string;
  variantsText?: string;
  costProfile?: string;
}

export const loadStoredBatchForm = (
  storage?: Pick<Storage, 'getItem'>,
): StoredBatchForm | null => {
  try {
    const s = storage ?? (typeof window !== 'undefined' ? window.localStorage : undefined);
    const raw = s?.getItem(BATCH_FORM_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as StoredBatchForm) : null;
  } catch {
    return null;
  }
};

export const saveStoredBatchForm = (
  form: StoredBatchForm,
  storage?: Pick<Storage, 'setItem'>,
): void => {
  try {
    const s = storage ?? (typeof window !== 'undefined' ? window.localStorage : undefined);
    s?.setItem(BATCH_FORM_STORAGE_KEY, JSON.stringify(form));
  } catch {
    // Ignore storage errors
  }
};

export const ROBOTS = [
  'regime',
  'ema',
  'adaptive_ema',
  'vpin_momentum',
  'formulaic_lgbm',
  'meta_label',
  'pairs',
  'funding',
  'ml_obi',
] as const;

export const ALL_LAB_SYMBOLS = [
  'BTCUSDT',
  'ETHUSDT',
  'SOLUSDT',
  'BNBUSDT',
  'XRPUSDT',
  'DOGEUSDT',
  'ADAUSDT',
  'AVAXUSDT',
  'DOTUSDT',
  'LINKUSDT',
  'MATICUSDT',
] as const;

export function normalizeSymbol(raw: string): string {
  return raw.replace(/[^A-Za-z0-9]/g, '').replace(/PERP$/i, '').toUpperCase();
}
