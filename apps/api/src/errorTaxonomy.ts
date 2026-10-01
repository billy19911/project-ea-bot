/**
 * TASK 04 — AI Control error taxonomy.
 *
 * Invariant 18/19 (MASTER_PLAN §0): AI Control must distinguish Python
 * unavailable, endpoint 4xx, endpoint 5xx, agent error, LLM provider 5xx/503
 * and timeout — and a 503 must NEVER be surfaced as a generic "agent error"
 * without the real failing layer.
 *
 * Before this module every failure collapsed into one of three opaque shapes:
 *   - Node proxy: `{ error: 'python_service_unavailable' }` (correct at the
 *     proxy boundary, but the UI then blamed the agent);
 *   - `recordError({ source: 'api', message: 'HTTP 503 on GET /x' })`;
 *   - Python: the LLM client swallowed provider failures into a rule-based
 *     mock, so a provider 503 never reached the UI at all.
 *
 * This module is the single source of truth for the 13 required taxonomy codes,
 * the set of fields every classified error must carry, and the retry policy.
 * It is plain logic (no Express imports) so it is unit-testable directly and
 * can be imported from `index.ts`, `pythonClient.ts` and `metrics.ts`.
 */

/** The 13 required error classes (MASTER_PLAN §6 / TASK 04). */
export const ERROR_CODES = [
  'NODE_API_UNAVAILABLE',
  'PYTHON_SERVICE_UNAVAILABLE',
  'PYTHON_ENDPOINT_4XX',
  'PYTHON_ENDPOINT_5XX',
  'AGENT_TIMEOUT',
  'AGENT_EXCEPTION',
  'LLM_PROVIDER_4XX',
  'LLM_PROVIDER_5XX',
  'LLM_PROVIDER_503',
  'LLM_TIMEOUT',
  'MODEL_UNAVAILABLE',
  'AUTH_FAILURE',
  'DATA_GUARD_FAILURE',
] as const;

export type ErrorCode = (typeof ERROR_CODES)[number];

/** Human-readable layer each code belongs to (UI renders this, not "agent"). */
export const ERROR_LAYER: Record<ErrorCode, string> = {
  NODE_API_UNAVAILABLE: 'node_api',
  PYTHON_SERVICE_UNAVAILABLE: 'python_service',
  PYTHON_ENDPOINT_4XX: 'python_endpoint',
  PYTHON_ENDPOINT_5XX: 'python_endpoint',
  AGENT_TIMEOUT: 'agent',
  AGENT_EXCEPTION: 'agent',
  LLM_PROVIDER_4XX: 'llm_provider',
  LLM_PROVIDER_5XX: 'llm_provider',
  LLM_PROVIDER_503: 'llm_provider',
  LLM_TIMEOUT: 'llm_provider',
  MODEL_UNAVAILABLE: 'llm_provider',
  AUTH_FAILURE: 'auth',
  DATA_GUARD_FAILURE: 'data_guard',
};

/**
 * Retry policy (MASTER_PLAN §6 "Retry policy").
 *
 * Only retryable errors may be retried. Transient/infra failures (service
 * down, provider 5xx/503, timeouts) are retryable. Deterministic client
 * failures MUST NOT be retried: invalid schema/4xx, auth failure, risk
 * rejection, missing/stale data (data guard).
 */
const RETRYABLE: Record<ErrorCode, boolean> = {
  NODE_API_UNAVAILABLE: true,
  PYTHON_SERVICE_UNAVAILABLE: true,
  PYTHON_ENDPOINT_4XX: false, // validation / bad request: deterministic
  PYTHON_ENDPOINT_5XX: true,
  AGENT_TIMEOUT: true,
  AGENT_EXCEPTION: true,
  LLM_PROVIDER_4XX: false, // invalid request/schema to the provider
  LLM_PROVIDER_5XX: true,
  LLM_PROVIDER_503: true,
  LLM_TIMEOUT: true,
  MODEL_UNAVAILABLE: false, // routing gap, not transient — needs operator fix
  AUTH_FAILURE: false,
  DATA_GUARD_FAILURE: false, // missing/stale data: do not retry blindly
};

export function isRetryable(code: ErrorCode): boolean {
  return RETRYABLE[code] ?? false;
}

/**
 * The canonical classified-error payload. Every field is present (null when the
 * layer genuinely has no value) so the UI never has to guess which layer failed.
 */
export interface ClassifiedError {
  /** Taxonomy code — the REAL failing layer. */
  code: ErrorCode;
  /** Coarse layer label derived from the code (`llm_provider`, not `agent`). */
  layer: string;
  trace_id: string | null;
  service: string | null;
  endpoint: string | null;
  status_code: number | null;
  agent: string | null;
  event_id: string | null;
  model: string | null;
  provider: string | null;
  timestamp: string;
  message: string;
  retryable: boolean;
}

export interface ClassifyInput {
  code: ErrorCode;
  message?: string;
  trace_id?: string | null;
  service?: string | null;
  endpoint?: string | null;
  status_code?: number | null;
  agent?: string | null;
  event_id?: string | null;
  model?: string | null;
  provider?: string | null;
  timestamp?: string;
}

/**
 * Build a fully-populated {@link ClassifiedError}. Unknown fields become null
 * (honest "unknown", never a fabricated value) and `retryable` is always
 * derived from the code so callers cannot accidentally mark a deterministic
 * error retryable.
 */
export function classify(input: ClassifyInput): ClassifiedError {
  const code = input.code;
  return {
    code,
    layer: ERROR_LAYER[code] ?? 'unknown',
    trace_id: input.trace_id ?? null,
    service: input.service ?? null,
    endpoint: input.endpoint ?? null,
    status_code: typeof input.status_code === 'number' ? input.status_code : null,
    agent: input.agent ?? null,
    event_id: input.event_id ?? null,
    model: input.model ?? null,
    provider: input.provider ?? null,
    timestamp: input.timestamp ?? new Date().toISOString(),
    message: input.message ?? defaultMessage(code),
    retryable: isRetryable(code),
  };
}

function defaultMessage(code: ErrorCode): string {
  switch (code) {
    case 'NODE_API_UNAVAILABLE':
      return 'Node control-plane API is unreachable.';
    case 'PYTHON_SERVICE_UNAVAILABLE':
      return 'Python analysis service is unreachable.';
    case 'PYTHON_ENDPOINT_4XX':
      return 'Python endpoint rejected the request (client error).';
    case 'PYTHON_ENDPOINT_5XX':
      return 'Python endpoint failed internally (server error).';
    case 'AGENT_TIMEOUT':
      return 'Agent exceeded its time budget.';
    case 'AGENT_EXCEPTION':
      return 'Agent raised an exception while analysing.';
    case 'LLM_PROVIDER_4XX':
      return 'LLM provider rejected the request (client error).';
    case 'LLM_PROVIDER_5XX':
      return 'LLM provider returned a server error.';
    case 'LLM_PROVIDER_503':
      return 'LLM provider reported 503 Service Unavailable.';
    case 'LLM_TIMEOUT':
      return 'LLM provider request timed out.';
    case 'MODEL_UNAVAILABLE':
      return 'No capable/available model for the request.';
    case 'AUTH_FAILURE':
      return 'Authentication/authorization failed.';
    case 'DATA_GUARD_FAILURE':
      return 'Data guard rejected missing/invalid input.';
    default:
      return 'Unknown error.';
  }
}

/**
 * Map a Node proxy (`pythonClient`) failure result into the taxonomy.
 *
 * Distinguishes the proxy boundary cases so the UI can tell "Python is down"
 * from "Python answered 4xx/5xx" from "the proxy itself timed out":
 *   - connection error            → PYTHON_SERVICE_UNAVAILABLE (503)
 *   - proxy timeout               → LLM_TIMEOUT? no → AGENT_TIMEOUT layer is
 *     python; use PYTHON_SERVICE_UNAVAILABLE with status 504? We keep the
 *     endpoint-timeout distinct as PYTHON_ENDPOINT_5XX-style timeout: the
 *     transport timed out, so the endpoint is effectively unavailable → 504.
 *   - upstream 401/403            → AUTH_FAILURE
 *   - upstream 4xx (other)        → PYTHON_ENDPOINT_4XX
 *   - upstream 5xx                → PYTHON_ENDPOINT_5XX (503 preserved as-is)
 *   - malformed JSON              → PYTHON_ENDPOINT_5XX
 */
export function classifyProxyFailure(
  result: {
    error: string;
    status: number;
    detail?: string;
    upstreamStatus?: number;
  },
  ctx: { service?: string; endpoint?: string; trace_id?: string | null } = {},
): ClassifiedError {
  const service = ctx.service ?? 'python_service';
  const endpoint = ctx.endpoint ?? null;
  const trace_id = ctx.trace_id ?? null;
  const upstream = result.upstreamStatus;
  const detail = result.detail ?? '';

  // Upstream answered with a concrete status.
  if (typeof upstream === 'number') {
    if (upstream === 401 || upstream === 403) {
      return classify({
        code: 'AUTH_FAILURE',
        message: `Python endpoint auth failure (${upstream}). ${detail}`.trim(),
        service,
        endpoint,
        status_code: upstream,
        trace_id,
      });
    }
    if (upstream >= 400 && upstream < 500) {
      return classify({
        code: 'PYTHON_ENDPOINT_4XX',
        message: `Python endpoint returned ${upstream}. ${detail}`.trim(),
        service,
        endpoint,
        status_code: upstream,
        trace_id,
      });
    }
    // 5xx (503 preserved verbatim — still an ENDPOINT failure, not agent).
    return classify({
      code: 'PYTHON_ENDPOINT_5XX',
      message: `Python endpoint returned ${upstream}. ${detail}`.trim(),
      service,
      endpoint,
      status_code: upstream,
      trace_id,
    });
  }

  // Transport-level: distinguish timeout from unreachable from bad payload.
  switch (result.error) {
    case 'python_service_timeout':
      return classify({
        code: 'PYTHON_SERVICE_UNAVAILABLE',
        message: `Python service timed out. ${detail}`.trim(),
        service,
        endpoint,
        status_code: 504,
        trace_id,
      });
    case 'python_service_invalid_json':
      return classify({
        code: 'PYTHON_ENDPOINT_5XX',
        message: `Python endpoint returned malformed JSON. ${detail}`.trim(),
        service,
        endpoint,
        status_code: 502,
        trace_id,
      });
    case 'python_service_invalid_url':
      return classify({
        code: 'PYTHON_SERVICE_UNAVAILABLE',
        message: `Python service URL is invalid. ${detail}`.trim(),
        service,
        endpoint,
        status_code: 502,
        trace_id,
      });
    case 'python_service_error':
      return classify({
        code: 'PYTHON_ENDPOINT_5XX',
        message: `Python endpoint error. ${detail}`.trim(),
        service,
        endpoint,
        status_code: result.status ?? 502,
        trace_id,
      });
    case 'python_service_unavailable':
    default:
      return classify({
        code: 'PYTHON_SERVICE_UNAVAILABLE',
        message: `Python service unreachable. ${detail}`.trim(),
        service,
        endpoint,
        status_code: 503,
        trace_id,
      });
  }
}

/**
 * Classify a raw HTTP status from an arbitrary subsystem probe (used for the
 * status tiles: Python / LLM Gateway / 9Router). Returns null when the probe
 * succeeded (2xx) so callers only surface real failures.
 */
export function classifyHttpStatus(
  status: number,
  ctx: { service?: string; endpoint?: string; trace_id?: string | null; message?: string } = {},
): ClassifiedError | null {
  if (status >= 200 && status < 300) return null;
  const service = ctx.service ?? null;
  const endpoint = ctx.endpoint ?? null;
  const trace_id = ctx.trace_id ?? null;
  const message = ctx.message ?? `HTTP ${status}`;
  if (status === 401 || status === 403) {
    return classify({ code: 'AUTH_FAILURE', message, service, endpoint, status_code: status, trace_id });
  }
  if (status >= 400 && status < 500) {
    return classify({
      code: 'PYTHON_ENDPOINT_4XX',
      message,
      service,
      endpoint,
      status_code: status,
      trace_id,
    });
  }
  return classify({
    code: 'PYTHON_ENDPOINT_5XX',
    message,
    service,
    endpoint,
    status_code: status,
    trace_id,
  });
}

/**
 * Normalise an already-classified error from Python (it emits the same field
 * names) so mixed Node+Python error lists render identically. Never throws.
 */
export function normalizeIncoming(raw: any): ClassifiedError | null {
  if (!raw || typeof raw !== 'object') return null;
  const code = raw.code ?? raw.error_code;
  if (typeof code !== 'string' || !(ERROR_CODES as readonly string[]).includes(code)) {
    return null;
  }
  const c = code as ErrorCode;
  return classify({
    code: c,
    message: typeof raw.message === 'string' ? raw.message : undefined,
    trace_id: raw.trace_id ?? null,
    service: raw.service ?? null,
    endpoint: raw.endpoint ?? null,
    status_code: typeof raw.status_code === 'number' ? raw.status_code : null,
    agent: raw.agent ?? null,
    event_id: raw.event_id ?? null,
    model: raw.model ?? null,
    provider: raw.provider ?? null,
    timestamp: typeof raw.timestamp === 'string' ? raw.timestamp : undefined,
  });
}

/** Whether the given error may be retried (retry policy enforcement). */
export function shouldRetry(err: ClassifiedError | { retryable?: boolean } | null | undefined): boolean {
  if (!err) return false;
  if (typeof (err as ClassifiedError).retryable === 'boolean') {
    return (err as ClassifiedError).retryable;
  }
  return false;
}
