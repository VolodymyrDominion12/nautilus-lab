/**
 * Formatting helpers shared by the result panels.
 *
 * The backend sends two shapes of the same number: a preformatted string (`"+1.23%"`,
 * `"n/a"`) and a raw value (`"0.0123"`). Charts and tone decisions must use the raw one —
 * parsing the display string back into a number is how a `"n/a"` becomes a `0`.
 */

export const toNumber = (raw: string | number | null | undefined): number | null => {
  if (raw == null || raw === '') return null;
  const value = typeof raw === 'number' ? raw : Number(raw);
  return Number.isFinite(value) ? value : null;
};

/** Fraction -> signed percent, e.g. 0.0123 -> "+1.23%". */
export const formatPct = (value: number | null | undefined, digits = 2): string => {
  if (value == null || !Number.isFinite(value)) return 'n/a';
  const percent = value * 100;
  const sign = percent > 0 ? '+' : '';
  return `${sign}${percent.toFixed(digits)}%`;
};

/** Fraction -> basis points, e.g. 0.0005 -> "5.0 bps". Fees live in this unit. */
export const formatBps = (value: number | null | undefined, digits = 1): string => {
  if (value == null || !Number.isFinite(value)) return 'n/a';
  return `${(value * 10000).toFixed(digits)} bps`;
};

export const formatMoney = (value: number | null | undefined): string => {
  if (value == null || !Number.isFinite(value)) return 'n/a';
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
};

export type Tone = 'positive' | 'negative' | 'neutral';

/** Tone by sign. `null` is neutral — an unmeasured number is not a loss. */
export const toneOf = (value: number | null | undefined): Tone => {
  if (value == null || !Number.isFinite(value)) return 'neutral';
  if (value > 0) return 'positive';
  if (value < 0) return 'negative';
  return 'neutral';
};

export const TONE_TEXT: Record<Tone, string> = {
  positive: 'text-emerald-400',
  negative: 'text-red-400',
  neutral: 'text-gray-300',
};

export const TONE_BORDER: Record<Tone, string> = {
  positive: 'border-emerald-800/60',
  negative: 'border-red-800/60',
  neutral: 'border-gray-800',
};

export const formatDateTime = (iso: string | null | undefined): string => {
  if (!iso) return '—';
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toISOString().replace('T', ' ').slice(0, 19);
};

export const formatDate = (iso: string | null | undefined): string => {
  if (!iso) return '—';
  return iso.slice(0, 10);
};

/** Seconds -> "1m 20s". Used for the elapsed timer on running jobs. */
export const formatElapsed = (seconds: number | null | undefined): string => {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '';
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${secs}s`;
  return `${secs}s`;
};

/**
 * How a run's numbers must be read. This is the project's core discipline: an
 * in-sample number is a parameter-selection artefact, not a result, and a PBO audit
 * measures the selection procedure rather than a strategy's profit.
 */
export type EvidenceClass =
  | 'out-of-sample'
  | 'in-sample-only'
  | 'overfitting-audit'
  | 'none';

export interface EvidenceBadge {
  label: string;
  detail: string;
  className: string;
}

export const evidenceBadge = (evidence: EvidenceClass): EvidenceBadge => {
  switch (evidence) {
    case 'out-of-sample':
      return {
        label: 'out-of-sample (report this)',
        detail: 'Parameters were chosen on the in-sample window only; these are forecast results.',
        className: 'bg-emerald-950/60 text-emerald-400 border-emerald-800/50',
      };
    case 'in-sample-only':
      return {
        label: 'in-sample only (selection only)',
        detail:
          'No out-of-sample split was made, so this number cannot show an edge. Do not report it as a result.',
        className: 'bg-amber-950/60 text-amber-400 border-amber-800/50',
      };
    case 'overfitting-audit':
      return {
        label: 'overfitting audit (no PnL verdict)',
        detail:
          'This measures whether the parameter selection generalises, not whether a strategy is profitable.',
        className: 'bg-purple-950/60 text-purple-300 border-purple-800/50',
      };
    default:
      return {
        label: 'no result yet',
        detail: 'Run a research job to produce evidence.',
        className: 'bg-gray-950 text-gray-500 border-gray-800',
      };
  }
};

/** "YYYY-MM-DD..." -> unix seconds at 00:00 UTC. null when unparseable. */
export const dateToUnixSeconds = (date: string | null | undefined): number | null => {
  if (!date) return null;
  const parsed = Math.floor(new Date(`${date.slice(0, 10)}T00:00:00Z`).getTime() / 1000);
  return Number.isFinite(parsed) ? parsed : null;
};

export type Staleness = 'current' | 'aging' | 'stale' | 'unknown';

/**
 * How old the newest bar is, in whole days, and how to read it.
 *
 * A catalog that ends months ago silently turns every walk-forward into a study of the
 * past, and nothing in the result payload says so — only the data does. `null` stays
 * `unknown`: an unparseable date is not evidence of freshness.
 */
export const describeStaleness = (
  lastDate: string | null | undefined,
  nowMs: number = Date.now(),
): { days: number | null; level: Staleness } => {
  const last = dateToUnixSeconds(lastDate);
  if (last == null) return { days: null, level: 'unknown' };
  const days = Math.floor((nowMs / 1000 - last) / 86_400);
  if (days <= 7) return { days, level: 'current' };
  if (days <= 30) return { days, level: 'aging' };
  return { days, level: 'stale' };
};
