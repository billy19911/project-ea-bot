// Shared client-side API helper (PRD_V2 §28).
//
// All API routes except the public allowlist (/health, /metrics, /auth/token)
// require a Bearer token. The token is stored in localStorage under the
// `ea-bot-token` key; the /login page is the supported way to fill it
// (POST /auth/token in dev), replacing the old manual DevTools paste.
//
// Transport: the browser calls the *web* origin via the `/ea-api/*` rewrite
// (see next.config.mjs), which proxies to the Node control-plane API. This
// keeps the Node API port configurable at runtime without rebuilding the web
// bundle and avoids CORS. NEXT_PUBLIC_API_URL is only used in local dev when
// the rewrite is not active (e.g. `next dev` without the backend).
export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  (typeof window !== 'undefined' ? `${window.location.origin}/ea-api` : '/ea-api');

export function getAuthToken(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return localStorage.getItem('ea-bot-token');
  } catch {
    return null;
  }
}

/**
 * Resolve the realtime WebSocket URL for the Node control-plane API.
 *
 * Order of preference:
 *   1. NEXT_PUBLIC_WS_URL (explicit, e.g. ws://10.0.0.5:3789/ws).
 *   2. Derived from NEXT_PUBLIC_API_URL / API_BASE when it points at the API
 *      origin (ws://<api-origin>/ws).
 *   3. Fallback to the current host with the Node API port (default 3789),
 *      matching the `/ea-api`-less WS connection used in local dev.
 *
 * Audit P2-12: the auth token is NOT put in the query string (it would leak
 * into proxy/access logs). Instead it is passed as a WebSocket subprotocol via
 * {@link getLiveSocketProtocols} (``bearer.<token>``), which browsers send in
 * the ``Sec-WebSocket-Protocol`` header.
 */
export function getLiveSocketUrl(): string | null {
  if (typeof window === 'undefined') return null;

  const explicit = process.env.NEXT_PUBLIC_WS_URL;
  let base = explicit || '';

  if (!base) {
    const apiEnv = process.env.NEXT_PUBLIC_API_URL;
    if (apiEnv && /^https?:\/\//.test(apiEnv)) {
      base = apiEnv.replace(/^http/, 'ws');
    } else {
      const port = process.env.NEXT_PUBLIC_WS_PORT || '3789';
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      base = `${proto}//${window.location.hostname}:${port}`;
    }
  }

  base = base.replace(/\/+$/, '');
  return new URL(base + '/ws').toString();
}

/**
 * WebSocket subprotocols carrying the auth token (audit P2-12).
 *
 * Returns ``['bearer.<token>']`` when signed in, else an empty array. The
 * server reads the token from ``Sec-WebSocket-Protocol`` instead of the query
 * string so the token never appears in URLs/logs.
 */
export function getLiveSocketProtocols(): string[] {
  const token = getAuthToken();
  return token ? [`bearer.${token}`] : [];
}

export function generateTraceId(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID();
    }
  } catch {
    // fall through to manual fallback
  }
  return `trace-${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
}

export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);

  const token = getAuthToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  if (!headers.has('X-Trace-Id')) {
    headers.set('X-Trace-Id', generateTraceId());
  }

  return fetch(API_BASE + path, { ...init, headers });
}

/**
 * apiFetchTyped — bungkus apiFetch untuk kontrak data PRD §85.
 *
 * Setiap endpoint yang mengikuti kontrak {value,status,updated_at,source}
 * bisa dipanggil lewat helper ini sehingga UI tidak pernah "menebak" data:
 * field yang hilang dikembalikan sebagai null/unknown, bukan angka 0 palsu.
 */
export async function apiFetchTyped<T>(
  path: string,
  init: RequestInit = {}
): Promise<{ value: T | null; status: string; updated_at: string; source: string }> {
  const resp = await apiFetch(path, init);
  let json: Record<string, unknown> = {};
  try {
    json = (await resp.json()) as Record<string, unknown>;
  } catch {
    json = {};
  }
  return {
    value: (json?.value as T) ?? null,
    status: (json?.status as string) ?? (resp.ok ? 'OK' : 'ERROR'),
    updated_at: (json?.updated_at as string) ?? new Date().toISOString(),
    source: (json?.source as string) ?? 'unknown',
  };
}

