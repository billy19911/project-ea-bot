'use client';

/**
 * useLiveQuotes — subscribe to the Node API live WebSocket (price + P&L).
 *
 * Ringkas & ringan:
 * - Satu koneksi WS per halaman; reconnect dengan backoff + jeda.
 * - Menutup koneksi saat tab tidak aktif (document.hidden) dan menyambung lagi
 *   saat tab kembali — menghemat CPU/network dan tidak "membebani website".
 * - Data selalu read-only dan apa adanya: kalau server tidak mengirim nilai,
 *   hook mengembalikan null (bukan angka palsu).
 */

import { useEffect, useRef, useState } from 'react';
import { getLiveSocketUrl } from './api';

export type LiveQuote = {
  symbol: string;
  bid: number | null;
  ask: number | null;
  last: number | null;
  time: number | string | null;
};

export type LivePosition = {
  ticket?: number | string;
  symbol?: string;
  side?: string;
  volume?: number | string;
  price_open?: number;
  price_current?: number;
  current?: number;
  sl?: number | null;
  tp?: number | null;
  profit?: number;
  unrealized_pnl?: number;
};

export type LiveAccount = {
  login?: number | null;
  server?: string;
  balance?: number;
  equity?: number;
  margin?: number;
  free_margin?: number;
  margin_level?: number;
  currency?: string;
  name?: string;
};

export type LiveStatus = 'connecting' | 'live' | 'offline';

type Options = {
  /** Symbols to subscribe to. Reconnect/re-subscribe when this changes. */
  symbols?: string[];
  /** Also stream open positions (default true). */
  positions?: boolean;
  /** Disable the stream entirely (e.g. feature off). */
  enabled?: boolean;
};

export function useLiveQuotes({ symbols, positions = true, enabled = true }: Options = {}) {
  const [quotes, setQuotes] = useState<Record<string, LiveQuote>>({});
  const [livePositions, setLivePositions] = useState<LivePosition[] | null>(null);
  const [account, setAccount] = useState<LiveAccount | null>(null);
  const [status, setStatus] = useState<LiveStatus>('connecting');
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const closedRef = useRef(false);
  const symbolsKey = (symbols ?? []).join(',');

  useEffect(() => {
    if (!enabled) return;
    if (typeof window === 'undefined') return;

    closedRef.current = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      const url = getLiveSocketUrl();
      if (!url) {
        setStatus('offline');
        return;
      }
      setStatus((s) => (s === 'live' ? 'live' : 'connecting'));

      let ws: WebSocket;
      try {
        ws = new WebSocket(url);
      } catch {
        scheduleReconnect();
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        retryRef.current = 0;
        setStatus('live');
        const syms = symbolsKey ? symbolsKey.split(',') : undefined;
        if (syms && syms.length) {
          try {
            ws.send(JSON.stringify({ type: 'subscribe', symbols: syms }));
          } catch {
            /* ignored */
          }
        }
      };

      ws.onmessage = (ev) => {
        let msg: { type?: string; data?: unknown };
        try {
          msg = JSON.parse(ev.data as string);
        } catch {
          return;
        }
        if (msg.type === 'quotes' && msg.data && typeof msg.data === 'object') {
          const incoming = msg.data as Record<string, LiveQuote | null>;
          setQuotes((prev) => {
            const next = { ...prev };
            for (const [sym, q] of Object.entries(incoming)) {
              if (q) next[sym] = q;
            }
            return next;
          });
          setLastUpdate(new Date());
        } else if (msg.type === 'positions' && Array.isArray(msg.data)) {
          setLivePositions(msg.data as LivePosition[]);
          setLastUpdate(new Date());
        } else if (msg.type === 'account' && msg.data && typeof msg.data === 'object') {
          setAccount(msg.data as LiveAccount);
          setLastUpdate(new Date());
        }
      };

      ws.onclose = (ev) => {
        if (wsRef.current === ws) wsRef.current = null;
        if (closedRef.current) return;
        // 4401 = unauthorized (no/expired token). Surface as offline; the user
        // must sign in — retrying forever would just churn.
        if (ev.code === 4401) {
          setStatus('offline');
          return;
        }
        setStatus('offline');
        scheduleReconnect();
      };

      ws.onerror = () => {
        // onclose handles the reconnect; just reflect the state.
        setStatus('offline');
      };
    };

    const scheduleReconnect = () => {
      if (closedRef.current) return;
      retryRef.current = Math.min(retryRef.current + 1, 6);
      const delay = Math.min(1000 * 2 ** (retryRef.current - 1), 15000);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(() => {
        if (!closedRef.current && !document.hidden) connect();
      }, delay);
    };

    const disconnect = () => {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws) {
        try {
          ws.close(1000, 'hidden');
        } catch {
          /* ignore */
        }
      }
    };

    // Only stream while the tab is visible — no background churn.
    const onVisibility = () => {
      if (document.hidden) {
        disconnect();
        setStatus('offline');
      } else {
        connect();
      }
    };

    if (document.hidden) {
      setStatus('offline');
    } else {
      connect();
    }
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      closedRef.current = true;
      document.removeEventListener('visibilitychange', onVisibility);
      disconnect();
    };
  }, [symbolsKey, enabled]);

  return {
    quotes,
    positions: positions ? livePositions : null,
    account,
    status,
    lastUpdate,
  };
}
