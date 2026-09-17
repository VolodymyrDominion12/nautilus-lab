/**
 * Verdict and preflight logic for the research form.
 *
 * Both functions are pure so they can be reasoned about and tested without a browser,
 * and both are deliberately conservative: they report "unmeasured" rather than guessing,
 * and they only raise an error for conditions the backend is *known* to reject.
 */

import type {
  CatalogInstrument,
  FoldSummary,
  MultiWindowSummary,
  ResearchSummary,
  StrategySpec,
} from '../services/api';
import { dateToUnixSeconds, evidenceBadge } from './format';
import type { EvidenceClass, EvidenceBadge } from './format';
import type { WindowBoundaries } from './windowBands';

export interface Verdict {
  evidence: EvidenceClass;
  badge: EvidenceBadge;
  headline: string;
  /** Human-readable reasons to distrust the headline. Empty means nothing was detected. */
  concerns: string[];
  beatsBuyHold: boolean | null;
  meanOosRaw: number | null;
  meanBuyHoldRaw: number | null;
}

const MINIMUM_BARS_BY_ROBOT: Record<string, number> = {
  regime: 150,
  vpin_momentum: 150,
  meta_label: 150,
  adaptive_ema: 150,
  pairs: 200,
  formulaic_lgbm: 80,
};

/**
 * Warm-up requirement for one leg. Mirrors `_require_warmup` in
 * `application/run_walk_forward.py`; `run_research_backtest.minimum_bars` matches it.
 */
export const minimumBars = (robot: string, spec?: StrategySpec): number => {
  const fromSpec = spec?.minimum_bars;
  if (typeof fromSpec === 'number' && fromSpec > 0) return fromSpec;
  return MINIMUM_BARS_BY_ROBOT[robot] ?? 50;
};

export interface FoldLayout {
  total: number;
  inSampleBars: number;
  perFoldBars: number;
  /** Bars in the single-split out-of-sample leg; null for multi-window layouts. */
  singleOosBars: number | null;
}

/**
 * Bar counts per leg, reimplementing the backend's window layout exactly:
 * `in_sample_bars = floor(total * is_fraction)`,
 * `per_fold = floor((total - in_sample_bars - embargo) / folds)`.
 */
export const foldLayout = (params: {
  total: number;
  folds: number;
  isFraction: number;
  embargoBars: number;
}): FoldLayout => {
  const { total, folds, isFraction, embargoBars } = params;
  const inSampleBars = Math.floor(total * isFraction);
  if (folds > 1) {
    return {
      total,
      inSampleBars,
      perFoldBars: Math.floor((total - inSampleBars - embargoBars) / folds),
      singleOosBars: null,
    };
  }
  return {
    total,
    inSampleBars,
    perFoldBars: 0,
    singleOosBars: Math.max(0, total - inSampleBars - embargoBars),
  };
};

/**
 * Boundaries of the split the backend will actually make.
 *
 * In fraction mode the split is by bar index — `floor(total * is_fraction)` — so the
 * position is derived from the bar count and the observed bar spacing rather than from a
 * naive fraction of wall-clock time. Drawing a boundary the engine will not use is how a
 * selection window gets mistaken for a forecast window.
 */
export const fractionBoundaries = (params: {
  firstDate?: string | null;
  lastDate?: string | null;
  barsCount?: number | null;
  isFraction: number;
  embargoBars: number;
}): WindowBoundaries => {
  const { firstDate, lastDate, barsCount, isFraction, embargoBars } = params;
  const first = dateToUnixSeconds(firstDate);
  const last = dateToUnixSeconds(lastDate);
  if (first == null || last == null || last <= first) {
    return { isStart: null, isEnd: null, oosStart: null, oosEnd: null };
  }
  const total = barsCount && barsCount > 1 ? barsCount : 0;
  if (total === 0) {
    // Bar count unknown: fall back to a time-proportional split; the panel says so.
    const split = first + (last - first) * isFraction;
    return { isStart: first, isEnd: split, oosStart: split, oosEnd: last };
  }
  const spacing = (last - first) / (total - 1);
  const isBars = Math.floor(total * isFraction);
  const isEnd = first + isBars * spacing;
  const oosStart = isEnd + embargoBars * spacing;
  return { isStart: first, isEnd, oosStart, oosEnd: last + spacing };
};

export interface PreflightIssue {
  level: 'error' | 'warning';
  message: string;
}

export interface PreflightInput {
  robot: string;
  spec?: StrategySpec;
  source: 'catalog' | 'synthetic';
  /** Bars in the whole series the run will load. */
  totalBars: number | null;
  syntheticBars: number;
  folds: number;
  isFraction: number;
  embargoBars: number;
  fullSample: boolean;
  useOptuna: boolean;
  pbo: boolean;
  windowMode: 'fraction' | 'custom';
  isStart: string;
  isEnd: string;
  oosStart: string;
  oosEnd: string;
  instrument?: CatalogInstrument | null;
  catalogInstruments?: number;
}

/**
 * Reject a run that the backend is guaranteed to refuse, before ~40 seconds of engine
 * work and a traceback. Errors block the Run button; warnings are shown but allowed.
 */
export const preflight = (input: PreflightInput): PreflightIssue[] => {
  const issues: PreflightIssue[] = [];
  const minimum = minimumBars(input.robot, input.spec);

  if (!input.spec) {
    issues.push({
      level: 'error',
      message: `Robot "${input.robot}" has no spec under specs/strategies, so its warm-up requirement is unknown.`,
    });
  } else if (input.spec && !input.spec.wired_in_backtest) {
    issues.push({
      level: 'error',
      message: `Robot "${input.robot}" is not wired to the backtest engine; the run will fail closed.`,
    });
  }

  if (input.fullSample && input.useOptuna) {
    issues.push({
      level: 'error',
      message:
        'Full-sample and Optuna are mutually exclusive: full-sample is one in-sample run, Optuna needs a split to select on.',
    });
  }

  if (input.folds > 1 && input.windowMode === 'custom') {
    issues.push({
      level: 'error',
      message:
        'Multi-window runs derive their own windows; drop the custom IS/OOS dates or use 1 fold.',
    });
  }

  if (input.windowMode === 'custom') {
    const dates = [input.isStart, input.isEnd, input.oosStart, input.oosEnd];
    const filled = dates.filter(Boolean).length;
    if (filled !== 0 && filled !== 4) {
      issues.push({
        level: 'error',
        message:
          'Custom windows need all four dates (IS start, IS end, OOS start, OOS end) — the backend rejects partial ones.',
      });
    }
  }

  if (input.isFraction <= 0 || input.isFraction >= 1) {
    issues.push({
      level: 'error',
      message: `In-sample fraction must be strictly between 0 and 1, got ${input.isFraction}.`,
    });
  }

  if (input.pbo && input.source === 'synthetic') {
    issues.push({
      level: 'warning',
      message: 'A PBO audit on synthetic bars measures the synthetic generator, not the market.',
    });
  }

  if (input.source === 'catalog') {
    if (!input.instrument || input.totalBars == null || input.totalBars <= 0) {
      issues.push({
        level: 'error',
        message:
          'No instrument selected from this catalog. Run an ingest first, or pick another catalog.',
      });
    } else if ((input.catalogInstruments ?? 1) > 1) {
      issues.push({
        level: 'warning',
        message: `This catalog holds ${input.catalogInstruments} instruments; the run uses "${input.instrument.raw_symbol}".`,
      });
    }
  }

  const total = input.source === 'synthetic' ? input.syntheticBars : input.totalBars;
  if (total != null && total > 0 && !input.pbo) {
    if (total < 3) {
      issues.push({
        level: 'error',
        message: `Only ${total} bars available; walk-forward needs at least 3.`,
      });
    } else {
      const layout = foldLayout({
        total,
        folds: input.folds,
        isFraction: input.isFraction,
        embargoBars: input.embargoBars,
      });
      if (input.folds > 1 && layout.perFoldBars < 1) {
        issues.push({
          level: 'error',
          message: `${total} bars cannot fill ${input.folds} folds at is_fraction=${input.isFraction} with embargo ${input.embargoBars}. Use fewer folds or more bars.`,
        });
      }
      if (!input.fullSample) {
        if (layout.inSampleBars < minimum) {
          issues.push({
            level: 'error',
            message: `In-sample leg gets ${layout.inSampleBars} bars but "${input.robot}" needs ${minimum} to warm up. Lower is_fraction or use a longer series.`,
          });
        }
        const oosBars = layout.singleOosBars ?? layout.perFoldBars;
        if (oosBars < minimum) {
          issues.push({
            level: 'error',
            message: `Each out-of-sample leg gets ${oosBars} bars but "${input.robot}" needs ${minimum} to warm up. Use fewer folds, lower is_fraction or a longer series.`,
          });
        }
      } else if (total < minimum) {
        issues.push({
          level: 'error',
          message: `Full-sample run has ${total} bars but "${input.robot}" needs ${minimum} to warm up.`,
        });
      }
    }
  }

  return issues;
};

export const preflightBlocking = (issues: PreflightIssue[]): boolean =>
  issues.some((issue) => issue.level === 'error');

/** Folds that actually made money out of sample, for the small per-fold strip. */
export const profitableFoldCount = (folds: FoldSummary[]): number =>
  folds.filter((fold) => (fold.oos_return_raw != null ? Number(fold.oos_return_raw) > 0 : false))
    .length;

/**
 * Turn a finished run into an honest verdict.
 *
 * The headline never claims an edge from an in-sample number, and a fold count of zero
 * or no fills is reported as "unmeasured" instead of being rounded into a win.
 */
export const verdictFor = (summary: ResearchSummary | null): Verdict => {
  const empty: Verdict = {
    evidence: 'none',
    badge: evidenceBadge('none'),
    headline: 'No completed run yet.',
    concerns: [],
    beatsBuyHold: null,
    meanOosRaw: null,
    meanBuyHoldRaw: null,
  };
  if (!summary || !summary.is_finished || summary.is_error) return empty;

  const runType = summary.run_type;
  if (runType === 'pbo') {
    const pbo = summary.pbo;
    return {
      evidence: 'overfitting-audit',
      badge: evidenceBadge('overfitting-audit'),
      headline: pbo?.summary_line ?? 'PBO audit finished.',
      concerns: pbo && !pbo.is_meaningful
        ? ['Fewer than 2 configurations or 2 splits, so PBO is undefined here.']
        : [],
      beatsBuyHold: null,
      meanOosRaw: null,
      meanBuyHoldRaw: null,
    };
  }

  // Synthetic bars come from a random walk, so no split over them can measure an edge. The
  // banner says so, but the verdict must too: a number cannot be labelled a forecast just
  // because the run happened to have an out-of-sample leg.
  const syntheticConcern =
    summary.source === 'synthetic'
      ? 'Produced from synthetic bars: a plumbing smoke test, not a market measurement.'
      : null;

  const multi: MultiWindowSummary | null | undefined = summary.multi_window;
  if (multi) {
    const meanOos = multi.mean_oos_raw != null ? Number(multi.mean_oos_raw) : null;
    const meanBuyHold =
      multi.buy_and_hold_mean_raw != null ? Number(multi.buy_and_hold_mean_raw) : null;
    const concerns: string[] = [];
    if (syntheticConcern) concerns.push(syntheticConcern);
    if (multi.total_oos_fills === 0) {
      concerns.push('Zero out-of-sample fills: no trades were executed, so there is nothing to score.');
    }
    if (multi.fold_count < 2) {
      concerns.push('Only one fold: a single out-of-sample stretch cannot separate an edge from luck.');
    }
    if (multi.beats_buy_and_hold === false) {
      concerns.push('Lost to simply holding the instrument over the same out-of-sample periods.');
    }
    if (multi.fold_count >= 2 && profitableFoldCount(multi.folds ?? []) < multi.fold_count) {
      const ratio = `${profitableFoldCount(multi.folds ?? [])}/${multi.fold_count}`;
      concerns.push(`Only ${ratio} folds were profitable, so the aggregate hides a losing stretch.`);
    }
    if (multi.mean_breakeven_cost != null && multi.mean_breakeven_cost < 0) {
      // A negative breakeven cost is the stronger statement: the run loses money before any
      // fees at all, so cheaper execution would not have saved it.
      concerns.push(
        'Breakeven cost is negative: the run loses money even before fees, so cheaper execution would not have saved it.',
      );
    } else if (multi.cost_headroom != null && multi.cost_headroom <= 0) {
      concerns.push(
        'Breakeven cost is at or below the cost actually paid: the result depends on cheap execution.',
      );
    }
    const headline =
      meanOos == null
        ? 'Out-of-sample return unmeasured.'
        : multi.beats_buy_and_hold === true
          ? `Beat buy&hold out of sample by ${multi.mean_excess_return}.`
          : multi.beats_buy_and_hold === false
            ? `Did not beat buy&hold out of sample (${multi.mean_excess_return} vs baseline).`
            : `Out-of-sample mean ${multi.mean_oos}; baseline not measurable.`;
    return {
      evidence: 'out-of-sample',
      badge: evidenceBadge('out-of-sample'),
      headline,
      concerns,
      beatsBuyHold: multi.beats_buy_and_hold ?? null,
      meanOosRaw: meanOos,
      meanBuyHoldRaw: meanBuyHold,
    };
  }

  const walk = summary.walk_forward;
  if (walk) {
    return {
      evidence: 'out-of-sample',
      badge: evidenceBadge('out-of-sample'),
      headline: `Single-split walk-forward: out-of-sample ${walk.out_of_sample_return ?? 'n/a'}, in-sample ${walk.in_sample_return ?? 'n/a'}.`,
      concerns: [
        ...(syntheticConcern ? [syntheticConcern] : []),
        'One anchored split only, and buy&hold is not measured for it: a single stretch cannot show an edge.',
      ],
      beatsBuyHold: null,
      meanOosRaw: walk.out_of_sample_return_raw != null ? Number(walk.out_of_sample_return_raw) : null,
      meanBuyHoldRaw: null,
    };
  }

  if (summary.single_backtest) {
    return {
      evidence: 'in-sample-only',
      badge: evidenceBadge('in-sample-only'),
      headline: summary.report_label ?? 'Full-sample run.',
      concerns: [
        ...(syntheticConcern ? [syntheticConcern] : []),
        'No out-of-sample split: these numbers include the bars the parameters were chosen on.',
      ],
      beatsBuyHold: null,
      meanOosRaw: null,
      meanBuyHoldRaw: null,
    };
  }

  return { ...empty, headline: 'Run finished but carried no result payload.' };
};
