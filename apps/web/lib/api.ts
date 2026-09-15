// Shared client-side API helper (PRD_V2 §28).
//
// All API routes except the public allowlist (/health, /metrics, /auth/token)
// require a Bearer token. The dashboard has no login UI yet, so the token is
// read from localStorage under the `ea-bot-token` key (the established
// convention used by the control-plane page).

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3001';

export function getAuthToken(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return localStorage.getItem('ea-bot-token');
  } catch {
    return null;
  }
}

function generateTraceId(): string {
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
