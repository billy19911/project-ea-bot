'use client';

import { useCallback, useMemo, useState } from 'react';
import styles from './page.module.css';
import { apiFetch } from '../../lib/api';
import { useAutoRefresh } from '../../lib/useAutoRefresh';
import { fmtDateTime } from '../../lib/useApiData';
import AppShell from '../../components/AppShell';
import Pagination from '../../components/ui/pagination';
import { isRetryable, causeLabel, type ErrorCode } from '../../lib/errorTaxonomy';

// ── TASK 04 — error taxonomy (mirrors apps/api/src/errorTaxonomy.ts) ──────────
// The 13 required classes. The UI must show the REAL failing layer, never a
// generic "agent error" for a 503 (MASTER_PLAN invariants 18/19).

type ClassifiedError = {
  code: ErrorCode;
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
};

type SubsystemTile = {
  name: 'supervisor' | 'python' | 'llm_gateway' | 'nine_router';
  status: string;
  detail: string | null;
  code: ErrorCode | null;
};

type AgentStatus = 'active' | 'idle' | 'error';
type AgentNode = {
  name: string;
  /** Human-facing callsign (e.g. TREND-SCAN); falls back to `name`. */
  displayName?: string;
  type: string;
  status: AgentStatus;
  priority: number | null;
  // REAL runtime metrics from the activity tracker.
  invocations: number;
  errors: number;
  errorRate: number;
  avgConfidence: number | null;
  lastActive: string | null;
  last_event_type?: string | null;
  signalCounts: Record<string, number>;
  /** TASK 04: taxonomy-classified last error (or null when healthy). */
  lastError?: ClassifiedError | null;
};
type ActivityLog = {
  id: string;
  timestamp: string;
  agent: string;
  action: string;
  status: 'success' | 'warning' | 'error';
  duration?: number;
};
type ModelUsage = {
  model: string;
  provider: string;
  calls: number;
  promptTokens: number;
  completionTokens: number;
  cost: number;
  isFree?: boolean;
};
type SupervisorStatus = {
  supervisor: { status: string; routing_policy: string; max_concurrency: number | null; token_budget: number | null; token_used: number | null; uptime: number | null };
  agents: AgentNode[];
  models: ModelUsage[];
  errors: ClassifiedError[];
  subsystems?: SubsystemTile[];
  trace_id?: string;
  activity?: ActivityLog[];
  degraded?: Record<string, string>;
  source?: SourceState;
};

type SourceState = 'live' | 'unavailable';

// Real uptime (seconds) → human string; '—' for unknown. Never prints raw floats.
function formatUptime(seconds: number | null | undefined): string {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${h}h ${m}m ${s}s`;
}

// `number | null` → locale string or '—' (no fabricated zeros).
function formatCount(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : '—';
}

// Human-facing callsign for a routing name (mirrors backend display_name).
const CALLSIGNS: Record<string, string> = {
  supervisor: 'OVERWATCH',
  market_lead: 'MARKET-LEAD',
  risk_lead: 'RISK-LEAD',
  review_lead: 'REVIEW-LEAD',
  technical_analyst: 'TREND-SCAN',
  structure_analyst: 'STRUCTURE',
  momentum_analyst: 'MOMENTUM',
  volatility_analyst: 'VOLATILITY',
  news_sentiment: 'NEWS-WIRE',
  fundamental_analyst: 'MACRO',
  post_trade_review: 'REVIEW',
  'Account Risk Analyst': 'RISK-ACC',
  'Position Risk Analyst': 'RISK-POS',
  'Portfolio Risk Analyst': 'RISK-PORT',
  'Drawdown Analyst': 'RISK-DD',
};

function callsignFor(name: string): string {
  if (CALLSIGNS[name]) return CALLSIGNS[name];
  return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function SourceBadge({ source }: { source: SourceState | undefined }) {
  const live = source === 'live';
  return (
    <span className={`${styles.badge} ${live ? styles.success : styles.muted}`}>
      {live ? 'LIVE' : 'UNAVAILABLE'}
    </span>
  );
}

// Status → css class for a subsystem tile value.
function subsystemClass(status: string): string {
  switch (status) {
    case 'HEALTHY':
    case 'ACTIVE':
      return styles.subsystemHealthy;
    case 'DEGRADED':
      return styles.subsystemDegraded;
    case 'UNAVAILABLE':
      return styles.subsystemUnavailable;
    default:
      return '';
  }
}

const SUBSYSTEM_LABEL: Record<SubsystemTile['name'], string> = {
  supervisor: 'Supervisor',
  python: 'Python',
  llm_gateway: 'LLM Gateway',
  nine_router: '9Router',
};

type AdvisorStatus = {
  enabled: boolean;
  calls: number;
  refusals: number;
  limits: { max_tokens: number; timeout_s: number };
  usage: Record<string, number>;
  budget: { available: boolean; token_budget?: number; token_used?: number };
  checked_at?: string;
};

type AdvisorResult = {
  ok: boolean;
  reason?: string;
  content?: string;
  model?: string;
  is_fallback?: boolean;
  classified_error?: ClassifiedError | null;
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number; cost_usd: number; latency_s: number };
  guardrails?: Record<string, unknown>;
};

export default function AIControlPage() {
  const [agents, setAgents] = useState<AgentNode[]>([]);
  const [activity, setActivity] = useState<ActivityLog[]>([]);
  const [errors, setErrors] = useState<ClassifiedError[]>([]);
  const [subsystems, setSubsystems] = useState<SubsystemTile[]>([]);
  const [traceId, setTraceId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<number | null>(null);
  const [models, setModels] = useState<ModelUsage[]>([]);
  const [reasoning, setReasoning] = useState('');
  const [supervisorStatus, setSupervisorStatus] = useState<SupervisorStatus | null>(null);
  const [source, setSource] = useState<SourceState>('unavailable');
  const [loading, setLoading] = useState(true);
  const [modelPage, setModelPage] = useState(1);
  const [modelPageSize, setModelPageSize] = useState(10);
  // TASK 04: retry policy — only retryable errors may be retried.
  const [retryBusy, setRetryBusy] = useState(false);
  const [retriedAt, setRetriedAt] = useState<string | null>(null);
  // LLM Advisor (ide #1) — advisory-only, guardrail fail-closed.
  const [advisorStatus, setAdvisorStatus] = useState<AdvisorStatus | null>(null);
  const [advisorRole, setAdvisorRole] = useState('market');
  const [advisorSymbol, setAdvisorSymbol] = useState('XAUUSD');
  const [advisorBusy, setAdvisorBusy] = useState(false);
  const [advisorResult, setAdvisorResult] = useState<AdvisorResult | null>(null);

  const load = useCallback(async () => {
      try {
        const res = await apiFetch(`/ai-control/status`);
        if (!res.ok) {
          setSource('unavailable');
          setLoadError(res.status);
          // A 503 from the page endpoint carries a classified body — surface the
          // real layer (Python unavailable / endpoint 5xx), never "agent error".
          try {
            const body = await res.json();
            if (body?.taxonomy) {
              setErrors([body.taxonomy as ClassifiedError]);
              setTraceId(body.trace_id ?? body.taxonomy.trace_id ?? null);
            }
            if (Array.isArray(body?.subsystems)) setSubsystems(body.subsystems as SubsystemTile[]);
          } catch {
            /* body not JSON — keep the HTTP status */
          }
        } else {
          const data = (await res.json()) as SupervisorStatus & { degraded?: Record<string, string> };
          setSupervisorStatus(data);
          setAgents(Array.isArray(data.agents) ? data.agents : []);
          setModels(Array.isArray(data.models) ? data.models : []);
          setErrors(Array.isArray(data.errors) ? data.errors : []);
          setSubsystems(Array.isArray(data.subsystems) ? data.subsystems : []);
          setTraceId(data.trace_id ?? null);
          setActivity(Array.isArray(data.activity) ? data.activity : []);
          setSource(data.source === 'live' ? 'live' : 'unavailable');
          setLoadError(null);
        }
      } catch (err) {
        console.error('Failed to fetch supervisor status:', err);
        setSource('unavailable');
        setLoadError(0);
        // Network failure is a NODE_API-level (or Python) fault, not an agent.
        setErrors([
          {
            code: 'NODE_API_UNAVAILABLE',
            layer: 'node_api',
            trace_id: null,
            service: 'node_api',
            endpoint: '/ai-control/status',
            status_code: null,
            agent: null,
            event_id: null,
            model: null,
            provider: null,
            timestamp: new Date().toISOString(),
            message: 'Node control-plane API tidak terjangkau.',
            retryable: true,
          },
        ]);
      }

      try {
        const res = await apiFetch(`/ai/advisor/status`);
        if (res.ok) {
          setAdvisorStatus((await res.json()) as AdvisorStatus);
        } else {
          setAdvisorStatus(null);
        }
      } catch {
        setAdvisorStatus(null);
      }

      try {
        const res = await apiFetch(`/ai-control/reasoning`);
        if (res.ok) {
          const data = await res.json();
          setReasoning(data.reasoning ?? '');
        } else if (res.status === 401) {
          setReasoning('Reasoning tidak tersedia — butuh token (jalankan token.bat).');
        } else {
          setReasoning(`Reasoning tidak tersedia — API merespons HTTP ${res.status}.`);
        }
      } catch (err) {
        console.error('Failed to fetch reasoning:', err);
        setReasoning('Reasoning tidak tersedia — API tidak terjangkau.');
      } finally {
        setLoading(false);
      }
  }, []);

  useAutoRefresh(load);

  // Retry policy: only retryable errors may be retried. Auth/4xx/data-guard/
  // model-unavailable errors are NOT retried (they need an operator fix).
  // `isRetryable` is the authoritative policy; fall back to the backend flag
  // when the code is present so the UI and backend can never disagree.
  const retryableErrors = useMemo(
    () => errors.filter((e) => (e.code ? isRetryable(e.code) && e.retryable : e.retryable)),
    [errors],
  );
  const nonRetryableErrors = useMemo(() => errors.filter((e) => !retryableErrors.includes(e)), [errors, retryableErrors]);
  const canRetry = retryableErrors.length > 0 && !retryBusy;

  const onRetry = useCallback(async () => {
    if (!canRetry) return;
    setRetryBusy(true);
    try {
      await load();
      setRetriedAt(new Date().toISOString());
    } finally {
      setRetryBusy(false);
    }
  }, [canRetry, load]);

  const totalTokens = models.reduce((sum, m) => sum + m.promptTokens + m.completionTokens, 0);
  const totalCost = models.reduce((sum, m) => sum + m.cost, 0);
  const totalCalls = models.reduce((sum, m) => sum + m.calls, 0);

  const modelPageCount = Math.max(1, Math.ceil(models.length / modelPageSize));
  const safeModelPage = Math.min(modelPage, modelPageCount);
  const visibleModels = models.slice((safeModelPage - 1) * modelPageSize, safeModelPage * modelPageSize);

  const activeAgentCount = agents.filter((a) => a.status === 'active').length;
  const errorAgentCount = agents.filter((a) => a.status === 'error' || a.errors > 0).length;

  return (
    <AppShell
      activeKey="ai-control"
      eyebrow="Xynn / Kontrol AI"
      title="Pusat Kontrol AI"
      actions={<SourceBadge source={source} />}
    >

        <div className={styles.pageBody}>
          {/* Load failure — explicit HTTP status + retry (never a silent empty UI).
              The cause is the REAL layer: Python unavailable ≠ agent error. */}
          {loadError !== null && (
            <section className={styles.card}>
              <div className={styles.empty}>
                {loadError === 0
                  ? 'Gagal memuat — API tidak terjangkau.'
                  : `Gagal memuat (HTTP ${loadError})`}{' '}
                <button type="button" className={styles.advisorRun} onClick={() => load()}>
                  Coba lagi
                </button>
              </div>
            </section>
          )}

          {/* TASK 04 — subsystem health tiles. Every tile is derived from a REAL
              probe; unknown → UNAVAILABLE (never a fabricated HEALTHY). */}
          <section className={styles.card}>
            <h2>Status subsistem</h2>
            <div className={styles.subsystemGrid}>
              {subsystems.length > 0 ? (
                subsystems.map((tile) => (
                  <div key={tile.name} className={styles.subsystemTile}>
                    <span className={styles.subsystemTileLabel}>{SUBSYSTEM_LABEL[tile.name]}</span>
                    <span className={`${styles.subsystemTileValue} ${subsystemClass(tile.status)}`}>
                      {tile.status}
                    </span>
                    {tile.detail && <span className={styles.subsystemDetail}>{tile.detail}</span>}
                    {tile.code && <span className={styles.subsystemCode}>{tile.code}</span>}
                  </div>
                ))
              ) : (
                <div className={styles.subsystemTile}>
                  <span className={styles.subsystemTileLabel}>Subsistem</span>
                  <span className={`${styles.subsystemTileValue} ${styles.subsystemUnavailable}`}>
                    {loading ? '…' : 'UNAVAILABLE'}
                  </span>
                  <span className={styles.subsystemDetail}>Status subsistem belum tersedia.</span>
                </div>
              )}
              {/* Agents tile — real active/error counts from the agent list. */}
              <div className={styles.subsystemTile}>
                <span className={styles.subsystemTileLabel}>Agents</span>
                <span className={styles.subsystemTileValue}>
                  <span className={styles.subsystemHealthy}>{activeAgentCount} active</span>
                  {' / '}
                  <span className={errorAgentCount > 0 ? styles.subsystemUnavailable : styles.subsystemHealthy}>
                    {errorAgentCount} error
                  </span>
                </span>
                <span className={styles.subsystemDetail}>{agents.length} terdaftar</span>
              </div>
            </div>
            {/* Global trace id — visible whenever the page has a request trace. */}
            <div className={styles.traceBar}>
              <span>Trace:</span>
              <code>{traceId ?? '—'}</code>
              {retriedAt && <span>Retry terakhir: {fmtDateTime(retriedAt)}</span>}
            </div>
          </section>

          {/* Partial data notice (Node reports which upstreams are unavailable).
              Each value is now a taxonomy CODE, not the word "unavailable". */}
          {supervisorStatus && 'degraded' in supervisorStatus && supervisorStatus.degraded ? (
            <section className={styles.card}>
              <div className={styles.empty}>
                Sebagian subsistem tidak tersedia:{' '}
                {Object.entries(supervisorStatus.degraded)
                  .map(([k, v]) => `${k} (${v})`)
                  .join(', ')}
              </div>
            </section>
          ) : null}

          {/* Supervisor Status */}
          {supervisorStatus ? (
            <section className={styles.card}>
              <h2>Status supervisor</h2>
              <div className={styles.supervisorGrid}>
                <div><small>Status</small><strong className={styles.statusActive}>{supervisorStatus.supervisor.status}</strong></div>
                <div><small>Routing policy</small><strong>{supervisorStatus.supervisor.routing_policy}</strong></div>
                <div><small>Max concurrency</small><strong>{formatCount(supervisorStatus.supervisor.max_concurrency)}</strong></div>
                <div><small>Token budget</small><strong>{formatCount(supervisorStatus.supervisor.token_budget)}</strong></div>
                <div><small>Token used</small><strong>{formatCount(supervisorStatus.supervisor.token_used)}</strong></div>
                <div><small>Uptime</small><strong>{formatUptime(supervisorStatus.supervisor.uptime)}</strong></div>
              </div>
            </section>
          ) : (
            <section className={styles.card}>
              <h2>Status supervisor</h2>
              <div className={styles.empty}>
                {loading
                  ? 'Memuat status supervisor…'
                  : 'Status supervisor tidak tersedia — API belum mengembalikan data. Cek token lalu muat ulang.'}
              </div>
            </section>
          )}

          {/* Agent Hierarchy */}
          <section className={styles.card}>
            <h2>Hierarki agent</h2>
            <div className={styles.agentTree}>
              {agents.map((agent) => (
                <div key={agent.name} className={styles.agentCard}>
                  <div className={styles.agentCardHeader}>
                    <div>
                      <strong title={`routing key: ${agent.name}`}>{agent.displayName || callsignFor(agent.name)}</strong>
                      <small>{agent.type}</small>
                    </div>
                    <span className={`${styles.badge} ${
                      agent.status === 'active' ? styles.success :
                      agent.status === 'error' ? styles.danger : styles.muted
                    }`}>
                      {agent.status}
                    </span>
                  </div>
                  <div className={styles.agentCardMeta}>
                    <span>Runs: {agent.invocations}</span>
                    {agent.avgConfidence !== null && (
                      <span>Conf: {(agent.avgConfidence * 100).toFixed(0)}%</span>
                    )}
                    {Object.keys(agent.signalCounts || {}).length > 0 && (
                      <span>
                        {Object.entries(agent.signalCounts)
                          .map(([k, v]) => `${k[0]}${v}`)
                          .join(' ')}
                      </span>
                    )}
                    {agent.lastActive && <span>Last: {agent.lastActive.slice(11, 19)}</span>}
                    {agent.last_event_type && <span>Event: {agent.last_event_type}</span>}
                    {agent.type === 'department_lead' && agent.invocations === 0 && (
                      <span
                        title={
                          agent.name.endsWith('_lead')
                            ? `Hanya aktif saat event ${agent.name.replace('_lead', '').toUpperCase()}_* / TRADE_CLOSE* masuk`
                            : 'Hanya aktif saat event keluarnya masuk'
                        }
                      >
                        idle — hanya saat event cocok masuk
                      </span>
                    )}
                    {agent.errors > 0 && (
                      <span className={styles.errorBadge}>{agent.errors} error</span>
                    )}
                  </div>
                  {/* TASK 04 — if this agent errored, show the REAL cause, not
                      a generic "agent error". Cause/Provider/Model/Retryable/
                      Last event/Trace. */}
                  {agent.lastError && (
                    <dl className={styles.agentErrorDetail}>
                      <dt>Status</dt>
                      <dd>
                        <span className={styles.errorBadge}>ERROR</span>
                      </dd>
                      <dt>Cause</dt>
                      <dd>
                        <span className={styles.causeChip}>{agent.lastError.code}</span>{' '}
                        <span>{causeLabel(agent.lastError.code)}</span>
                      </dd>
                      <dt>Layer</dt>
                      <dd><code>{agent.lastError.layer}</code></dd>
                      {agent.lastError.provider && (
                        <>
                          <dt>Provider</dt>
                          <dd><code>{agent.lastError.provider}</code></dd>
                        </>
                      )}
                      {agent.lastError.model && (
                        <>
                          <dt>Model</dt>
                          <dd><code>{agent.lastError.model}</code></dd>
                        </>
                      )}
                      {agent.lastError.status_code !== null && (
                        <>
                          <dt>HTTP</dt>
                          <dd><code>{agent.lastError.status_code}</code></dd>
                        </>
                      )}
                      <dt>Retryable</dt>
                      <dd className={agent.lastError.retryable ? styles.retryableYes : styles.retryableNo}>
                        {agent.lastError.retryable ? 'YES' : 'NO'}
                      </dd>
                      {agent.lastError.event_id && (
                        <>
                          <dt>Last event</dt>
                          <dd><code>{agent.lastError.event_id}</code></dd>
                        </>
                      )}
                      <dt>Trace</dt>
                      <dd><code>{agent.lastError.trace_id ?? traceId ?? '—'}</code></dd>
                      <dt>Message</dt>
                      <dd>{agent.lastError.message}</dd>
                    </dl>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* Current Reasoning */}
          <section className={styles.card}>
            <h2>Reasoning saat ini</h2>
            <p className={styles.reasoning}>{reasoning}</p>
          </section>

          {/* Activity Log — sourced from real agent events when available */}
          <section className={styles.card}>
            <h2>Log aktivitas agent</h2>
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Waktu</th>
                    <th>Agent</th>
                    <th>Aksi</th>
                    <th>Status</th>
                    <th>Durasi (ms)</th>
                  </tr>
                </thead>
                <tbody>
                  {activity.map((log) => (
                    <tr key={log.id}>
                      <td><code>{fmtDateTime(log.timestamp)}</code></td>
                      <td><strong title={`routing key: ${log.agent}`}>{callsignFor(log.agent)}</strong></td>
                      <td>{log.action}</td>
                      <td>
                        <span className={`${styles.statusBadge} ${
                          log.status === 'success' ? styles.statusSuccess :
                          log.status === 'warning' ? styles.statusWarning : styles.statusError
                        }`}>
                          {log.status}
                        </span>
                      </td>
                      <td>{log.duration || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {activity.length === 0 && (
                <div className={styles.empty}>
                  {source === 'live'
                    ? 'Belum ada aktivitas agent tercatat.'
                    : 'Log aktivitas tidak tersedia — API belum mengembalikan data. Cek token lalu muat ulang.'}
                </div>
              )}
            </div>
          </section>

          {/* Errors — taxonomy-classified. Header is the real layer, NOT the
              generic phrase "agent error". Each row shows cause/layer/provider/
              model/HTTP/retryable/trace. */}
          {errors.length > 0 && (
            <section className={styles.card}>
              <h2>Error (terklasifikasi)</h2>
              <div className={styles.errorList}>
                {errors.map((err, idx) => (
                  <div key={`${err.code}-${err.timestamp}-${idx}`} className={styles.errorItem}>
                    <div className={styles.errorIcon}>!</div>
                    <div className={styles.errorContent}>
                      <div className={styles.errorHeader}>
                        <strong>
                          {err.agent ? callsignFor(err.agent) : err.layer}
                          {' · '}
                          <span className={styles.causeChip}>{err.code}</span>
                        </strong>
                        <code>{fmtDateTime(err.timestamp)}</code>
                      </div>
                      <p>{err.message}</p>
                      <dl className={styles.agentErrorDetail}>
                        <dt>Layer</dt>
                        <dd><code>{err.layer}</code></dd>
                        {err.service && (<><dt>Service</dt><dd><code>{err.service}</code></dd></>)}
                        {err.endpoint && (<><dt>Endpoint</dt><dd><code>{err.endpoint}</code></dd></>)}
                        {err.status_code !== null && (<><dt>HTTP</dt><dd><code>{err.status_code}</code></dd></>)}
                        {err.provider && (<><dt>Provider</dt><dd><code>{err.provider}</code></dd></>)}
                        {err.model && (<><dt>Model</dt><dd><code>{err.model}</code></dd></>)}
                        {err.event_id && (<><dt>Event</dt><dd><code>{err.event_id}</code></dd></>)}
                        <dt>Retryable</dt>
                        <dd className={err.retryable ? styles.retryableYes : styles.retryableNo}>
                          {err.retryable ? 'YES' : 'NO'}
                        </dd>
                        <dt>Trace</dt>
                        <dd><code>{err.trace_id ?? '—'}</code></dd>
                      </dl>
                    </div>
                    <span className={`${styles.badge} ${err.retryable ? styles.danger : styles.muted}`}>
                      {causeLabel(err.code)}
                    </span>
                  </div>
                ))}
              </div>

              {/* Retry policy — only retryable errors are retried. */}
              <div className={styles.traceBar}>
                <span>
                  Retryable: <strong>{retryableErrors.length}</strong> · Tidak retryable:{' '}
                  <strong>{nonRetryableErrors.length}</strong>
                </span>
                <button
                  type="button"
                  className={styles.retryButton}
                  disabled={!canRetry}
                  title={
                    canRetry
                      ? 'Coba ulang error yang retryable'
                      : 'Tidak ada error retryable (auth/4xx/data-guard/model tidak di-retry)'
                  }
                  onClick={onRetry}
                >
                  {retryBusy ? 'Mencoba…' : 'Retry error retryable'}
                </button>
              </div>
            </section>
          )}

          {/* LLM Advisor (ide #1) — advisory-only, guardrail fail-closed */}
          <section className={styles.card}>
            <h2>Penasihat LLM (9Router)</h2>
            {advisorStatus ? (
              <div className={styles.modelSummary}>
                <div>
                  <small>Status</small>
                  <strong className={advisorStatus.enabled ? styles.statusActive : undefined}>
                    {advisorStatus.enabled ? 'Aktif' : 'Nonaktif (opt-in)'}
                  </strong>
                </div>
                <div><small>Panggilan</small><strong>{advisorStatus.calls}</strong></div>
                <div><small>Ditolak guardrail</small><strong>{advisorStatus.refusals}</strong></div>
                <div>
                  <small>Budget token</small>
                  <strong>
                    {advisorStatus.budget.available
                      ? `${advisorStatus.budget.token_used ?? 0} / ${advisorStatus.budget.token_budget ?? 0}`
                      : '—'}
                  </strong>
                </div>
                <div><small>Batas per panggilan</small><strong>{advisorStatus.limits.max_tokens} token · {advisorStatus.limits.timeout_s}s</strong></div>
              </div>
            ) : (
              <div className={styles.empty}>
                Status penasihat tidak tersedia — API belum mengembalikan data. Cek token lalu muat ulang.
              </div>
            )}

            <div className={styles.advisorForm}>
              <label>
                Peran
                <select value={advisorRole} onChange={(e) => setAdvisorRole(e.target.value)}>
                  <option value="market">market</option>
                  <option value="risk">risk</option>
                  <option value="research">research</option>
                </select>
              </label>
              <label>
                Simbol
                <input value={advisorSymbol} onChange={(e) => setAdvisorSymbol(e.target.value)} />
              </label>
              <button
                type="button"
                className={styles.advisorRun}
                disabled={advisorBusy}
                onClick={async () => {
                  setAdvisorBusy(true);
                  setAdvisorResult(null);
                  try {
                    // Ambil harga nyata dulu (read-only) supaya prompt berisi data
                    // pasar sungguhan; bila tidak ada, guardrail data menolak.
                    let market: Record<string, unknown> = { symbol: advisorSymbol.trim().toUpperCase() };
                    try {
                      const tickRes = await apiFetch(`/mt5/market/tick?symbol=${encodeURIComponent(advisorSymbol.trim().toUpperCase())}`);
                      if (tickRes.ok) {
                        const data = await tickRes.json();
                        const d = data?.data;
                        if (d && typeof d.bid === 'number' && typeof d.ask === 'number') {
                          market = { symbol: advisorSymbol.trim().toUpperCase(), bid: d.bid, ask: d.ask, timeframe: 'H1' };
                        }
                      }
                    } catch {
                      // tetap lanjut — guardrail data akan menolak bila kosong
                    }
                    const res = await apiFetch(`/ai/advisor/advise`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ role: advisorRole, ...market }),
                    });
                    setAdvisorResult((await res.json()) as AdvisorResult);
                  } catch {
                    setAdvisorResult({ ok: false, reason: 'Permintaan gagal — API tidak terjangkau.' });
                  } finally {
                    setAdvisorBusy(false);
                  }
                }}
              >
                {advisorBusy ? 'Meminta…' : 'Minta analisis'}
              </button>
            </div>

            {advisorResult && (
              advisorResult.ok ? (
                <div className={styles.advisorOutput}>
                  <div className={styles.advisorMeta}>
                    <span>Model: <code>{advisorResult.model || '—'}</code></span>
                    {advisorResult.is_fallback && (
                      <span className={styles.badge + ' ' + styles.warning}>
                        Fallback rule-based — bukan keluaran model
                      </span>
                    )}
                    <span>{advisorResult.usage?.total_tokens ?? 0} token · ${(advisorResult.usage?.cost_usd ?? 0).toFixed(4)} · {(advisorResult.usage?.latency_s ?? 0).toFixed(2)}s</span>
                  </div>
                  <pre className={styles.advisorText}>{advisorResult.content}</pre>
                  <p className={styles.advisorNote}>
                    Saran untuk manusia — tidak ada order yang dibuat dan tidak ada yang mengonsumsi keluaran ini secara otomatis.
                  </p>
                </div>
              ) : (
                <div className={styles.empty}>
                  Ditolak: {advisorResult.reason}
                  {advisorResult.classified_error && (
                    <small>
                      {' '}Penyebab: <span className={styles.causeChip}>{advisorResult.classified_error.code}</span>{' '}
                      ({advisorResult.classified_error.layer}) ·{' '}
                      {advisorResult.classified_error.provider ?? '—'}/{advisorResult.classified_error.model ?? '—'} ·{' '}
                      retryable={advisorResult.classified_error.retryable ? 'YES' : 'NO'}
                    </small>
                  )}
                  {advisorResult.guardrails && (
                    <small>
                      {' '}Guardrail: aktif={String(advisorResult.guardrails.enabled)} · budget={String(advisorResult.guardrails.budget_ok)} · data={String(advisorResult.guardrails.data_ok)}
                    </small>
                  )}
                </div>
              )
            )}
          </section>

          {/* Model Usage */}
          <section className={styles.card}>
            <h2>Penggunaan model LLM (panggilan nyata)</h2>
            <div className={styles.modelSummary}>
              <div><small>Total token</small><strong>{totalCalls > 0 ? totalTokens.toLocaleString() : '—'}</strong></div>
              <div><small>Total cost</small><strong>{totalCalls > 0 ? `$${totalCost.toFixed(3)}` : '—'}</strong></div>
              <div><small>Avg per call</small><strong>{totalCalls > 0 ? `${Math.round(totalTokens / totalCalls)} token` : '—'}</strong></div>
            </div>
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Provider</th>
                    <th>Panggilan</th>
                    <th>Prompt tokens</th>
                    <th>Completion tokens</th>
                    <th>Biaya (USD)</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleModels.map((model) => (
                    <tr key={model.model}>
                      <td><strong>{model.model}</strong></td>
                      <td>{model.provider}</td>
                      <td>{model.calls}</td>
                      <td>{model.promptTokens.toLocaleString()}</td>
                      <td>{model.completionTokens.toLocaleString()}</td>
                      <td className={model.cost > 0 ? styles.costPaid : styles.costFree}>
                        {model.calls === 0
                          ? '—'
                          : model.cost > 0
                            ? `$${model.cost.toFixed(3)}`
                            : model.isFree
                              ? 'Gratis'
                              : '$0.000'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {models.length > 0 && (
                <Pagination
                  page={safeModelPage}
                  pageSize={modelPageSize}
                  total={models.length}
                  onPageChange={setModelPage}
                  onPageSizeChange={setModelPageSize}
                  unitLabel="models"
                />
              )}
              {models.length === 0 && (
                <div className={styles.empty}>
                  {source === 'live'
                    ? 'Belum ada panggilan LLM — tabel ini hanya menampilkan model yang benar-benar dipanggil (bukan daftar model).'
                    : 'Data penggunaan tidak tersedia — API belum mengembalikan data. Cek token lalu muat ulang.'}
                </div>
              )}
            </div>
          </section>
        </div>
    </AppShell>
  );
}
