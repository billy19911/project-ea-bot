'use client';

import { useCallback, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { useAutoRefresh } from '@/lib/useAutoRefresh';

/**
 * useApiData — one fetch, one honest state, shared by the ops/control pages.
 *
 * The dashboard's honesty rule (see `execution-quality/page.tsx` and the PRD
 * §85 data contract) is: a missing number is shown as "—", never as a fake 0.
 * This hook centralises that contract so every page behaves the same way:
 *
 *   - `data`     : the parsed `value` field (or the raw body when it has none).
 *   - `error`    : a human-readable message, or null. A 503 is reported as
 *                  "Python service unavailable." — the operator sees WHY.
 *   - `loading`  : true until the first response settles (success OR failure).
 *   - `refresh`  : manual re-fetch (for Refresh buttons).
 *
 * `useAutoRefresh` is wired in so pages update on their own, pausing while the
 * tab is hidden (no background spam).
 *
 * `pick` lets a caller pull a specific envelope field; when omitted the hook
 * prefers `body.value` and falls back to the whole body, matching the two
 * conventions already used across the dashboard.
 */
export type ApiState<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
};

export function useApiData<T = unknown>(
  path: string,
  options: { intervalMs?: number; pick?: (body: unknown) => T | null } = {}
): ApiState<T> {
  const { intervalMs = 10_000, pick } = options;

  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch(path);
      if (!res.ok) {
        setError(errorMessageFor(res.status));
        return;
      }
      let body: unknown = null;
      try {
        body = await res.json();
      } catch {
        body = null;
      }
      setData(pick ? pick(body) : extractValue<T>(body));
      setError(null);
    } catch {
      setError('Could not reach the API.');
    } finally {
      setLoading(false);
    }
  }, [path, pick]);

  useAutoRefresh(load, intervalMs);

  return { data, error, loading, refresh: load };
}

/**
 * errorMessageFor — turn an HTTP status into an operator-facing message.
 *
 * Never leak the raw status code on its own. A 401/403 means "you are not
 * signed in (or the session expired)", which the rest of the dashboard
 * already phrases as "open the Sign in page" (see `research/page.tsx`); a 503
 * means the Python brain is down. Unknown statuses keep the code so support
 * can still diagnose, but are labelled honestly.
 */
function errorMessageFor(status: number): string {
  if (status === 401 || status === 403) {
    return 'Sesi tidak valid — buka halaman Masuk untuk mendapatkan token.';
  }
  if (status === 429) {
    return 'Terlalu banyak permintaan (rate limit) — tunggu sebentar lalu coba lagi.';
  }
  if (status === 503) {
    return 'Python service unavailable.';
  }
  return `Request failed (${status})`;
}

/** Exported so pages that fetch outside the hook reuse the same wording. */
export { errorMessageFor };

/**
 * Prefer the PRD §85 envelope `{ value, status, updated_at, source }`; fall
 * back to the whole body so endpoints that return a bare object/array also
 * work without a per-page adapter.
 */
function extractValue<T>(body: unknown): T | null {
  if (body && typeof body === 'object' && 'value' in (body as Record<string, unknown>)) {
    return ((body as Record<string, unknown>).value as T) ?? null;
  }
  return (body as T) ?? null;
}

/**
 * fmtNum — format a possibly-missing number honestly.
 *
 * Returns the em-dash placeholder when the value is absent or not finite, so
 * tables never display a misleading `0`. `digits` controls fixed precision.
 */
export function fmtNum(value: unknown, digits = 2, placeholder = '—'): string {
  if (value == null) return placeholder;
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return placeholder;
  return n.toFixed(digits);
}

/** fmtPct — format a 0..1 ratio as a percentage, honestly. */
export function fmtPct(value: unknown, digits = 2, placeholder = '—'): string {
  if (value == null) return placeholder;
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return placeholder;
  return `${(n * 100).toFixed(digits)}%`;
}

/** fmtDate — locale date-time, honest placeholder for missing values. */
export function fmtDate(value: unknown, placeholder = '—'): string {
  if (value == null || value === '') return placeholder;
  const d = new Date(value as string);
  if (Number.isNaN(d.getTime())) return placeholder;
  return d.toLocaleString();
}

/** fmtDateTime — compact `YYYY-MM-DD HH:MM:SS` (local), honest placeholder.
 *
 * Preferred for log/activity tables so operators read a stable, sortable
 * timestamp instead of a raw ISO string with microseconds. Falls back to the
 * raw value only when it truly cannot be parsed (never a fabricated date). */
export function fmtDateTime(value: unknown, placeholder = '—'): string {
  if (value == null || value === '') return placeholder;
  const d = new Date(value as string);
  if (Number.isNaN(d.getTime())) {
    // Unparseable — show the raw string rather than hide it.
    return typeof value === 'string' ? value : placeholder;
  }
  const p = (n: number) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
    `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
  );
}

/** fmtTime — local `HH:MM:SS` only (for dense log rows). */
export function fmtTime(value: unknown, placeholder = '—'): string {
  if (value == null || value === '') return placeholder;
  const d = new Date(value as string);
  if (Number.isNaN(d.getTime())) {
    return typeof value === 'string' ? value : placeholder;
  }
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/**
 * formatDetails — render an arbitrary audit/metadata value safely as text.
 *
 * API `details` fields are often JSON objects/arrays (e.g. a reconciliation
 * summary). Rendering those directly as a React child throws
 * "Objects are not valid as a React child". This collapses objects to compact
 * JSON and passes primitives through. Arrays of primitives join with ', '.
 */
export function formatDetails(value: unknown, placeholder = '—'): string {
  if (value === null || value === undefined || value === '') return placeholder;
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) {
    if (value.length === 0) return placeholder;
    if (value.every((v) => typeof v === 'string' || typeof v === 'number')) {
      return value.join(', ');
    }
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
