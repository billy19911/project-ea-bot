/**
 * Live market stream — WebSocket broadcaster for realtime price & P&L.
 *
 * Design goals (kept deliberately lightweight so the dashboard stays fast):
 * - ONE server-side poll loop per tick interval, shared by ALL connected
 *   clients (not one HTTP poll per browser tab). With zero clients connected
 *   the loop is idle: no upstream traffic at all.
 * - Fail-safe/honest: a failed upstream read is sent as `source:"unavailable"`
 *   and never fabricated into fake numbers.
 * - Read-only: only proxies GET endpoints (`/mt5/market/tick`, `/mt5/positions`).
 *
 * Wire format (JSON text frames):
 *   client → server : { "type": "subscribe", "symbols": ["XAUUSD", ...] }
 *   server → client : { "type": "quotes",    "data": { "XAUUSD": {...} } }
 *                     { "type": "positions", "data": [ ... ] }
 *                     { "type": "hello",     "interval_ms": 2500 }
 */

import type { Server as HttpServer } from 'http';
import { WebSocketServer, type WebSocket } from 'ws';
import { getJson } from './pythonClient';
import { logger } from './logger';

const DEFAULT_SYMBOLS = ['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'BTCUSD'];
const MAX_SYMBOLS = 12;

type ClientState = {
  ws: WebSocket;
  symbols: string[];
};

type TickResponse = {
  data?: {
    symbol?: string;
    bid?: number;
    ask?: number;
    last?: number;
    time?: number | string;
    volume?: number;
  };
};

type PositionsResponse = {
  positions?: unknown[];
};

type AccountResponse = {
  login?: number | null;
  server?: string;
  balance?: number;
  equity?: number;
  margin?: number;
  free_margin?: number;
  margin_level?: number;
  currency?: string;
  name?: string;
  trade_mode?: number | string;
};

export type LiveStreamHandle = {
  close: () => void;
  clients: () => number;
  wss: WebSocketServer;
};

function normaliseSymbol(raw: unknown): string | null {
  const s = String(raw ?? '').trim().toUpperCase();
  if (!/^[A-Z0-9._#+-]{1,32}$/.test(s)) return null;
  return s;
}

/**
 * Attach the live WebSocket stream to an existing HTTP server.
 *
 * `authCheck` is invoked per upgrade request and must return true to accept
 * the connection (reuses the project's wsAuthHandler). Connections that fail
 * auth are closed with code 4401.
 */
export function attachLiveStream(
  server: HttpServer,
  opts: {
    authCheck: (req: unknown) => boolean;
    onConnection?: (ws: WebSocket, req: unknown) => void;
    intervalMs?: number;
  },
): LiveStreamHandle {
  const intervalMs = opts.intervalMs ?? 2500;
  const wss = new WebSocketServer({ noServer: true });

  server.on('upgrade', (req, socket, head) => {
    let pathname = '/';
    try {
      pathname = new URL(req.url ?? '/', 'http://localhost').pathname;
    } catch {
      pathname = req.url ?? '/';
    }
    if (pathname !== '/ws') {
      socket.destroy();
      return;
    }
    if (!opts.authCheck(req)) {
      // Complete the handshake then close, so the browser sees a WS close
      // code instead of a generic socket error.
      wss.handleUpgrade(req, socket, head, (ws) => {
        ws.close(4401, 'unauthorized');
      });
      return;
    }
    wss.handleUpgrade(req, socket, head, (ws) => {
      opts.onConnection?.(ws, req);
      wss.emit('connection', ws, req);
    });
  });

  const clients = new Set<ClientState>();

  wss.on('connection', (ws: WebSocket) => {
    const state: ClientState = { ws, symbols: [...DEFAULT_SYMBOLS] };
    clients.add(state);

    try {
      ws.send(JSON.stringify({ type: 'hello', interval_ms: intervalMs }));
    } catch {
      /* ignore */
    }

    ws.on('message', (raw: Buffer) => {
      try {
        const msg = JSON.parse(raw.toString());
        if (msg && msg.type === 'subscribe' && Array.isArray(msg.symbols)) {
          const next: string[] = [];
          for (const s of msg.symbols) {
            const sym = normaliseSymbol(s);
            if (sym && !next.includes(sym)) next.push(sym);
            if (next.length >= MAX_SYMBOLS) break;
          }
          state.symbols = next.length ? next : [...DEFAULT_SYMBOLS];
          // Answer immediately so a newly focused tab fills without waiting
          // for the next tick.
          void publish({ only: state });
        }
      } catch {
        /* ignore malformed client frames */
      }
    });

    ws.on('close', () => clients.delete(state));
    ws.on('error', () => clients.delete(state));
  });

  /** Union of every symbol any client is watching. */
  function watchedSymbols(): string[] {
    const out = new Set<string>();
    for (const c of clients) for (const s of c.symbols) out.add(s);
    return [...out];
  }

  async function publish(targets?: { only: ClientState }): Promise<void> {
    if (clients.size === 0) return;
    const list = targets ? [targets.only] : [...clients];
    if (list.length === 0) return;

    const symbols = targets ? targets.only.symbols : watchedSymbols();

    // Fetch ticks + positions + account in parallel; all are fail-safe.
    const [tickResults, positionsResult, accountResult] = await Promise.all([
      Promise.all(
        symbols.map(async (symbol) => {
          const r = await getJson<TickResponse>(
            `/mt5/market/tick?symbol=${encodeURIComponent(symbol)}`,
            4000,
          );
          if (!r.ok) return [symbol, null] as const;
          const d = r.data?.data ?? (r.data as TickResponse['data']);
          if (!d) return [symbol, null] as const;
          // MT5 often reports last=0 (brokers that publish only bid/ask, e.g.
          // many XAUUSD feeds). Treat any non-positive quote as "no value" and
          // fall back to a usable price — never broadcast a 0 that would wreck
          // the chart's price scale.
          const pos = (v: unknown): number | null =>
            typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : null;
          const bid = pos(d.bid);
          const ask = pos(d.ask);
          const lastRaw = pos(d.last);
          const last = lastRaw ?? bid ?? ask;
          return [
            symbol,
            {
              symbol: d.symbol ?? symbol,
              bid,
              ask,
              last,
              time: d.time ?? null,
            },
          ] as const;
        }),
      ),
      getJson<PositionsResponse>('/mt5/positions', 4000),
      getJson<AccountResponse>('/mt5/accounts/info', 4000),
    ]);

    const quotes: Record<string, unknown> = {};
    for (const [sym, q] of tickResults) quotes[sym] = q;

    const positions = positionsResult.ok ? positionsResult.data?.positions ?? [] : null;

    const quotesMsg = JSON.stringify({ type: 'quotes', data: quotes });
    const posMsg = JSON.stringify({ type: 'positions', data: positions });

    const account = accountResult.ok ? accountResult.data ?? null : null;
    const acctMsg = JSON.stringify({ type: 'account', data: account });

    for (const c of list) {
      try {
        if (c.ws.readyState === c.ws.OPEN) {
          c.ws.send(quotesMsg);
          if (positionsResult.ok) c.ws.send(posMsg);
          if (accountResult.ok) c.ws.send(acctMsg);
        }
      } catch {
        /* a dead socket is cleaned up on its close event */
      }
    }
  }

  const timer = setInterval(() => {
    void publish();
  }, intervalMs);
  // Never hold the process open just for the stream.
  if (typeof timer.unref === 'function') timer.unref();

  logger.info({ intervalMs }, 'live_stream.started');

  return {
    clients: () => clients.size,
    wss,
    close: () => {
      clearInterval(timer);
      for (const c of clients) {
        try {
          c.ws.close(1001, 'server shutting down');
        } catch {
          /* ignore */
        }
      }
      clients.clear();
      wss.close();
    },
  };
}
