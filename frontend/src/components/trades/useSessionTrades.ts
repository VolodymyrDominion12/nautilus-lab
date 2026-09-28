import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchSessionTrade, fetchSessionTrades } from '../../services/api';
import type { TradeDetailResponse, TradesResponse } from '../../services/api';

/** Chart context a trade page needs; it travels in the link, so a reload keeps the chart. */
export interface TradeChartContext {
  instrumentId?: string;
  barInterval?: string;
  catalogPath?: string;
}

interface TradesState {
  data: TradesResponse | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * The trades of one session, re-read while the session is live.
 *
 * `sessionKey` is a live session id/name **or** a research run id: the API resolves both
 * against the same decision log, which is what lets the terminal and the Backtest Details
 * modal share one list. A key of `null` means there is nothing to ask for yet (a session
 * that has not started) and stays idle instead of firing a request that would 404.
 */
export function useSessionTrades(sessionKey: string | null, pollMs = 0): TradesState {
  const [data, setData] = useState<TradesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const keyRef = useRef(sessionKey);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    keyRef.current = sessionKey;
    if (!sessionKey) {
      setData(null);
      setError(null);
      return;
    }
    let cancelled = false;

    const load = async (showSpinner: boolean) => {
      if (showSpinner) setLoading(true);
      try {
        const payload = await fetchSessionTrades(sessionKey);
        if (cancelled || keyRef.current !== sessionKey) return;
        setData(payload);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Не вдалося прочитати список угод');
      } finally {
        if (!cancelled && showSpinner) setLoading(false);
      }
    };

    void load(true);
    const timer = pollMs > 0 ? setInterval(() => void load(false), pollMs) : null;
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [sessionKey, pollMs, nonce]);

  return { data, loading, error, reload };
}

interface TradeState {
  data: TradeDetailResponse | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/** One trade with its decisions and the candles around it. */
export function useTrade(
  sessionKey: string | null,
  tradeId: string | null,
  context: TradeChartContext,
  pollMs = 0,
): TradeState {
  const [data, setData] = useState<TradeDetailResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const { instrumentId, barInterval, catalogPath } = context;

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    if (!sessionKey || !tradeId) {
      setData(null);
      return;
    }
    let cancelled = false;

    const load = async (showSpinner: boolean) => {
      if (showSpinner) setLoading(true);
      try {
        const payload = await fetchSessionTrade(sessionKey, tradeId, {
          instrumentId,
          barInterval,
          catalogPath,
        });
        if (cancelled) return;
        setData(payload);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Не вдалося прочитати угоду');
      } finally {
        if (!cancelled && showSpinner) setLoading(false);
      }
    };

    void load(true);
    const timer = pollMs > 0 ? setInterval(() => void load(false), pollMs) : null;
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [sessionKey, tradeId, instrumentId, barInterval, catalogPath, pollMs, nonce]);

  return { data, loading, error, reload };
}
