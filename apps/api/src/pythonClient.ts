/**
 * Typed HTTP client for the Python FastAPI service.
 *
 * The control-plane endpoints in this API historically returned hard-coded demo
 * data (PRD_V2 §25/§26/§27 violation). This client lets them proxy *real* data
 * from the Python service instead. When the Python service is unreachable the
 * caller must surface a 503 with `source: "unavailable"` — never fabricated
 * numbers.
 *
 * Implemented with `node:http`/`node:https` (rather than global fetch) so the
 * request has an explicit timeout and works under the project's
 * ES2022-commonjs tsconfig without extra DOM libs.
 */

import http from 'node:http';
import https from 'node:https';
import { URL } from 'node:url';

/** Default Python service base URL when `PYTHON_SERVICE_URL` is unset. */
export const DEFAULT_PYTHON_SERVICE_URL = 'http://127.0.0.1:8000';

/** Default request timeout in milliseconds. */
export const DEFAULT_TIMEOUT_MS = 5000;

export type ProxySource = 'live' | 'unavailable';

/** Extra request headers to forward to the Python service. */
export type RequestHeaders = Record<string, string>;

/** Successful proxy result: parsed JSON plus the resolved source label. */
export interface PythonProxySuccess<T = unknown> {
  ok: true;
  source: 'live';
  status: number;
  data: T;
}

/** Failed proxy result: the upstream was unreachable or returned an error. */
export interface PythonProxyFailure {
  ok: false;
  source: 'unavailable';
  status: number;
  error: string;
  detail?: string;
  /**
   * When the upstream Python service answered with a non-2xx status, the real
   * status code is recorded here (the top-level `status` stays 502 for
   * backwards compatibility with existing callers/tests). Proxies that want to
   * preserve an upstream 4xx (e.g. a validation rejection carrying a `message`)
   * can pass it through instead of masking it as 503.
   */
  upstreamStatus?: number;
  /** Parsed upstream JSON body for non-2xx responses, when parseable. */
  upstreamBody?: unknown;
}

export type PythonProxyResult<T = unknown> = PythonProxySuccess<T> | PythonProxyFailure;

function resolveBaseUrl(): string {
  const raw = process.env.PYTHON_SERVICE_URL || DEFAULT_PYTHON_SERVICE_URL;
  // Trim a trailing slash so path concatenation stays predictable.
  return raw.replace(/\/+$/, '');
}

function resolveTimeoutMs(): number {
  const raw = process.env.PYTHON_SERVICE_TIMEOUT_MS;
  const parsed = raw ? Number.parseInt(raw, 10) : NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_TIMEOUT_MS;
}

/**
 * Perform a GET request against the Python service and parse the JSON body.
 *
 * Never throws: transport failures, timeouts, non-2xx responses and malformed
 * JSON all resolve to a `PythonProxyFailure` with `source: "unavailable"`.
 *
 * @param path Target path (e.g. `/scheduler/status`).
 * @param timeoutMs Optional override request timeout.
 * @param headers Optional extra headers (e.g. `{ 'X-Trace-Id': id }`) to
 *   forward so distributed traces propagate end-to-end (PRD §26/§27).
 */
export function getJson<T = unknown>(
  path: string,
  timeoutMs: number = resolveTimeoutMs(),
  headers: RequestHeaders = {},
): Promise<PythonProxyResult<T>> {
  return request('GET', path, undefined, timeoutMs, headers);
}

/**
 * Perform a POST request against the Python service with a JSON body and parse
 * the JSON response.
 *
 * Used by control-plane endpoints that trigger work (e.g. `POST /pipeline/run`)
 * rather than merely read state. Never throws: failures resolve to a
 * `PythonProxyFailure` with `source: "unavailable"`.
 *
 * @param path Target path (e.g. `/pipeline/run`).
 * @param body JSON-serialisable request body.
 * @param timeoutMs Optional override request timeout.
 * @param headers Optional extra headers (e.g. `{ 'X-Trace-Id': id }`).
 */
export function postJson<T = unknown>(
  path: string,
  body: unknown = {},
  timeoutMs: number = resolveTimeoutMs(),
  headers: RequestHeaders = {},
): Promise<PythonProxyResult<T>> {
  return request('POST', path, body, timeoutMs, headers);
}

/**
 * Perform a PUT request against the Python service with a JSON body.
 *
 * Used by the settings endpoint (UI/UX ide #7) where the operation is an
 * idempotent update of a small allowlisted resource. Never throws: failures
 * resolve to a `PythonProxyFailure` with `source: "unavailable"`.
 *
 * @param path Target path (e.g. `/settings`).
 * @param body JSON-serialisable request body.
 * @param timeoutMs Optional override request timeout.
 * @param headers Optional extra headers (e.g. `{ 'X-Trace-Id': id }`).
 */
export function putJson<T = unknown>(
  path: string,
  body: unknown = {},
  timeoutMs: number = resolveTimeoutMs(),
  headers: RequestHeaders = {},
): Promise<PythonProxyResult<T>> {
  return request('PUT', path, body, timeoutMs, headers);
}

/**
 * Shared transport for GET/POST proxying to the Python service.
 *
 * Centralising this keeps timeout, error and JSON-parsing semantics identical
 * across verbs so callers can rely on the same `source` labelling.
 */
function request<T>(
  method: 'GET' | 'POST' | 'PUT',
  path: string,
  body: unknown,
  timeoutMs: number,
  headers: RequestHeaders,
): Promise<PythonProxyResult<T>> {
  return new Promise((resolve) => {
    let target: URL;
    try {
      target = new URL(`${resolveBaseUrl()}${path}`);
    } catch (err) {
      resolve({
        ok: false,
        source: 'unavailable',
        status: 502,
        error: 'python_service_invalid_url',
        detail: err instanceof Error ? err.message : String(err),
      });
      return;
    }

    const transport = target.protocol === 'https:' ? https : http;
    let settled = false;

    const finish = (result: PythonProxyResult<T>): void => {
      if (settled) return;
      settled = true;
      resolve(result);
    };

    const requestHeaders: RequestHeaders = { accept: 'application/json', ...headers };
    let payload: string | undefined;
    if (method === 'POST' || method === 'PUT') {
      payload = JSON.stringify(body ?? {});
      requestHeaders['content-type'] = 'application/json';
      requestHeaders['content-length'] = Buffer.byteLength(payload).toString();
    }

    const req = transport.request(
      {
        protocol: target.protocol,
        hostname: target.hostname,
        port: target.port,
        path: `${target.pathname}${target.search}`,
        method,
        headers: requestHeaders,
      },
      (response) => {
        const chunks: Buffer[] = [];
        response.on('data', (chunk: Buffer) => chunks.push(chunk));
        response.on('end', () => {
          const bodyText = Buffer.concat(chunks).toString('utf-8');
          const status = response.statusCode ?? 502;

          if (status < 200 || status >= 300) {
            // Record the real upstream status/body so callers can choose to
            // preserve it (see `sendPostProxy`) while `status`/`error` keep the
            // historical "unavailable" semantics other callers rely on.
            let upstreamBody: unknown;
            if (bodyText) {
              try {
                upstreamBody = JSON.parse(bodyText);
              } catch {
                upstreamBody = bodyText;
              }
            }
            finish({
              ok: false,
              source: 'unavailable',
              status: 502,
              error: 'python_service_error',
              detail: `upstream ${status}`,
              upstreamStatus: status,
              upstreamBody,
            });
            return;
          }

          try {
            const data = (bodyText ? JSON.parse(bodyText) : {}) as T;
            finish({ ok: true, source: 'live', status, data });
          } catch (err) {
            finish({
              ok: false,
              source: 'unavailable',
              status: 502,
              error: 'python_service_invalid_json',
              detail: err instanceof Error ? err.message : String(err),
            });
          }
        });
      },
    );

    req.setTimeout(timeoutMs, () => {
      req.destroy();
      finish({
        ok: false,
        source: 'unavailable',
        status: 504,
        error: 'python_service_timeout',
      });
    });

    req.on('error', (err: Error) => {
      finish({
        ok: false,
        source: 'unavailable',
        status: 503,
        error: 'python_service_unavailable',
        detail: err.message,
      });
    });

    req.end(payload);
  });
}

/**
 * Convenience helper: returns the parsed data on success (spreading the
 * `source` label into the payload) or `null` on failure.
 *
 * Callers that need to distinguish "unavailable" from "live" should use
 * {@link getJson} directly; this helper is for endpoint handlers that simply
 * want to merge real data with a source label.
 */
export async function proxyJson<T = Record<string, unknown>>(
  path: string,
  headers: RequestHeaders = {},
): Promise<(T & { source: ProxySource }) | null> {
  const result = await getJson<T>(path, resolveTimeoutMs(), headers);
  if (!result.ok) return null;
  return { ...(result.data as T), source: 'live' };
}
