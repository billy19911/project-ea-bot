// TASK 04 — AI Control error taxonomy helpers (web side).
//
// Mirrors `apps/api/src/errorTaxonomy.ts` for the codes the UI renders. Kept as
// a tiny dependency-free module so the cause labels and retry policy can be
// unit-tested without rendering the page.

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

// Human-facing label for a taxonomy code. NEVER returns "agent error" for an
// infrastructure/LLM failure (invariant 19).
export const CAUSE_LABEL: Record<ErrorCode, string> = {
  NODE_API_UNAVAILABLE: 'Node API tidak terjangkau',
  PYTHON_SERVICE_UNAVAILABLE: 'Python service tidak tersedia',
  PYTHON_ENDPOINT_4XX: 'Endpoint Python menolak (4xx)',
  PYTHON_ENDPOINT_5XX: 'Endpoint Python gagal (5xx)',
  AGENT_TIMEOUT: 'Agent timeout',
  AGENT_EXCEPTION: 'Agent exception',
  LLM_PROVIDER_4XX: 'LLM provider menolak (4xx)',
  LLM_PROVIDER_5XX: 'LLM provider gagal (5xx)',
  LLM_PROVIDER_503: 'LLM provider 503',
  LLM_TIMEOUT: 'LLM timeout',
  MODEL_UNAVAILABLE: 'Model tidak tersedia',
  AUTH_FAILURE: 'Autentikasi gagal',
  DATA_GUARD_FAILURE: 'Data guard menolak',
};

// Retry policy (MASTER_PLAN §6). Deterministic client errors are NOT retryable:
// invalid schema / 4xx, risk rejection, auth failure, missing data, model gap.
const NON_RETRYABLE: ReadonlySet<ErrorCode> = new Set([
  'PYTHON_ENDPOINT_4XX',
  'LLM_PROVIDER_4XX',
  'MODEL_UNAVAILABLE',
  'AUTH_FAILURE',
  'DATA_GUARD_FAILURE',
]);

export function isRetryable(code: string | undefined): boolean {
  if (!code || !(ERROR_CODES as readonly string[]).includes(code)) return false;
  return !NON_RETRYABLE.has(code as ErrorCode);
}

export function causeLabel(code: string | undefined): string {
  if (!code) return 'Penyebab tidak diketahui';
  return (CAUSE_LABEL as Record<string, string>)[code] ?? code;
}
