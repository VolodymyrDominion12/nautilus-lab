import { useEffect, useRef, useState, useCallback } from 'react';
import { fetchLivePaperState, getLivePaperWsUrl } from '../../services/api';
import type { LiveBar, LivePaperState } from '../../services/api';

export function useLiveTradingSession(sessionId: string | null) {
  const [state, setState] = useState<LivePaperState | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [statusMsg, setStatusMsg] = useState('Ready');
  const [lastBar, setLastBar] = useState<LiveBar | null>(null);

  // Editable Stops in UI
  const [editSl, setEditSl] = useState('');
  const [editTp, setEditTp] = useState('');

  const wsRef = useRef<WebSocket | null>(null);

  // Fetch initial state
  const loadInitialState = useCallback(async () => {
    if (!sessionId) {
      setState(null);
      return;
    }
    try {
      const data = await fetchLivePaperState(sessionId);
      setState(data);
      if (data.position) {
        setEditSl(data.position.stop_loss || '');
        setEditTp(data.position.take_profit || '');
      }
    } catch (err) {
      console.error('Failed to fetch live paper state:', err);
    }
  }, [sessionId]);

  useEffect(() => {
    loadInitialState();
  }, [loadInitialState]);

  // WebSocket Connection with reconnection backoff
  useEffect(() => {
    let disposed = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let pingTimer: ReturnType<typeof setInterval> | null = null;
    let attempt = 0;

    if (!sessionId) {
      setIsConnected(false);
      setStatusMsg('No session selected: fill in the form and press Start');
      return () => {
        disposed = true;
      };
    }

    const connect = () => {
      if (disposed) return;
      const ws = new WebSocket(getLivePaperWsUrl(sessionId));
      wsRef.current = ws;

      ws.onopen = () => {
        attempt = 0;
        setIsConnected(true);
        setStatusMsg('Connected to Live Stream');
      };

      ws.onclose = (event) => {
        if (pingTimer) clearInterval(pingTimer);
        pingTimer = null;
        setIsConnected(false);
        if (disposed) return;
        const delayMs = Math.min(15000, 1000 * 2 ** attempt);
        attempt += 1;
        if (event.code === 1008) {
          setStatusMsg(
            `Refused by the API: ${event.reason || 'origin or token'} — open the dashboard at the ` +
              'address listed in API_ALLOWED_ORIGINS (and check API_TOKEN)',
          );
        } else {
          setStatusMsg(`Stream disconnected — reconnecting in ${Math.round(delayMs / 1000)}s`);
        }
        retryTimer = setTimeout(connect, delayMs);
      };

      ws.onerror = (err) => {
        console.warn('Live Paper WS error:', err);
      };

      ws.onmessage = (event) => {
        if (event.data === 'pong') return;
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'INIT_STATE' || msg.type === 'STATE_UPDATE') {
            const newState = msg.data as LivePaperState;
            setState(newState);
            if (newState.position) {
              setEditSl(newState.position.stop_loss || '');
              setEditTp(newState.position.take_profit || '');
            }
          } else if (msg.type === 'BAR_UPDATE') {
            const bar = msg.data as LiveBar;
            setLastBar(bar);

            // Update position mark price and floating PnL
            setState((prev) => {
              if (!prev) return null;
              return {
                ...prev,
                last_price: msg.last_price ?? prev.last_price,
                current_equity: msg.current_equity ?? prev.current_equity,
                unrealized_pnl: msg.unrealized_pnl ?? prev.unrealized_pnl,
                position: msg.position ?? prev.position,
              };
            });
          }
        } catch (e) {
          console.error('Error parsing WS message:', e);
        }
      };

      pingTimer = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, 15000);
    };

    connect();

    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      if (pingTimer) clearInterval(pingTimer);
      wsRef.current?.close();
    };
  }, [sessionId]);

  return {
    state,
    setState,
    isConnected,
    statusMsg,
    setStatusMsg,
    lastBar,
    editSl,
    setEditSl,
    editTp,
    setEditTp,
    reloadState: loadInitialState,
  };
}
