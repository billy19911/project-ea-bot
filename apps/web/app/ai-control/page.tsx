'use client';

import { useEffect, useState } from 'react';
import styles from './page.module.css';
import { apiFetch } from '../../lib/api';
import AppShell from '../../components/AppShell';

type AgentStatus = 'active' | 'idle' | 'error';
type AgentNode = { 
  name: string; 
  type: string; 
  status: AgentStatus; 
  priority: number;
  lastActive?: string;
  errorCount: number;
};
type ActivityLog = { 
  id: string; 
  timestamp: string; 
  agent: string; 
  action: string; 
  status: 'success' | 'warning' | 'error';
  duration?: number;
};
type AgentError = { 
  id: string; 
  timestamp: string; 
  agent: string; 
  message: string; 
  severity: 'low' | 'medium' | 'high';
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
  errors: AgentError[];
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

function SourceBadge({ source }: { source: SourceState | undefined }) {
  const live = source === 'live';
  return (
    <span className={`${styles.badge} ${live ? styles.success : styles.muted}`}>
      {live ? 'LIVE' : 'UNAVAILABLE'}
    </span>
  );
}

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
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number; cost_usd: number; latency_s: number };
  guardrails?: Record<string, unknown>;
};

export default function AIControlPage() {
  const [agents, setAgents] = useState<AgentNode[]>([]);
  const activity: ActivityLog[] = [];
  const [errors, setErrors] = useState<AgentError[]>([]);
  const [models, setModels] = useState<ModelUsage[]>([]);
  const [reasoning, setReasoning] = useState('');
  const [supervisorStatus, setSupervisorStatus] = useState<SupervisorStatus | null>(null);
  const [source, setSource] = useState<SourceState>('unavailable');
  const [loading, setLoading] = useState(true);
  // LLM Advisor (ide #1) — advisory-only, guardrail fail-closed.
  const [advisorStatus, setAdvisorStatus] = useState<AdvisorStatus | null>(null);
  const [advisorRole, setAdvisorRole] = useState('market');
  const [advisorSymbol, setAdvisorSymbol] = useState('XAUUSD');
  const [advisorBusy, setAdvisorBusy] = useState(false);
  const [advisorResult, setAdvisorResult] = useState<AdvisorResult | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await apiFetch(`/ai-control/status`);
        if (!res.ok) {
          setSource('unavailable');
        } else {
          const data = (await res.json()) as SupervisorStatus;
          setSupervisorStatus(data);
          setAgents(Array.isArray(data.agents) ? data.agents : []);
          setModels(Array.isArray(data.models) ? data.models : []);
          setErrors(Array.isArray(data.errors) ? data.errors : []);
          setSource(data.source === 'live' ? 'live' : 'unavailable');
        }
      } catch (err) {
        console.error('Failed to fetch supervisor status:', err);
        setSource('unavailable');
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
    };
    load();

    // Polling is not yet scheduled here; the page fetches on mount. WebSocket
    // streaming from the Python service is a future enhancement.
  }, []);

  const totalTokens = models.reduce((sum, m) => sum + m.promptTokens + m.completionTokens, 0);
  const totalCost = models.reduce((sum, m) => sum + m.cost, 0);
  const totalCalls = models.reduce((sum, m) => sum + m.calls, 0);

  return (
    <AppShell
      activeKey="ai-control"
      eyebrow="EA BOT / PUSAT KONTROL AI"
      title="Pusat Kontrol AI"
      actions={<SourceBadge source={source} />}
    >

        <div className={styles.pageBody}>
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
                      <strong>{agent.name}</strong>
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
                    <span>Priority: {agent.priority}</span>
                    {agent.lastActive && <span>Last: {agent.lastActive}</span>}
                    {agent.errorCount > 0 && <span className={styles.errorBadge}>{agent.errorCount} error</span>}
                  </div>
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
                      <td><code>{log.timestamp}</code></td>
                      <td><strong>{log.agent}</strong></td>
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

          {/* Agent Errors */}
          {errors.length > 0 && (
            <section className={styles.card}>
              <h2>Error agent</h2>
              <div className={styles.errorList}>
                {errors.map((err) => (
                  <div key={err.id} className={styles.errorItem}>
                    <div className={styles.errorIcon}>!</div>
                    <div className={styles.errorContent}>
                      <div className={styles.errorHeader}>
                        <strong>{err.agent}</strong>
                        <code>{err.timestamp}</code>
                      </div>
                      <p>{err.message}</p>
                    </div>
                    <span className={`${styles.badge} ${
                      err.severity === 'high' ? styles.danger : 
                      err.severity === 'medium' ? styles.warning : styles.muted
                    }`}>
                      {err.severity}
                    </span>
                  </div>
                ))}
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
                      const symRes = await apiFetch(`/market/overview`);
                      if (symRes.ok) {
                        const data = await symRes.json();
                        const row = Array.isArray(data.symbols)
                          ? data.symbols.find((s: { symbol?: string }) => s.symbol === advisorSymbol.trim().toUpperCase())
                          : null;
                        if (row) market = { ...market, bid: row.bid, ask: row.ask, spread_pips: row.spread, trend: row.trend, timeframe: 'H1' };
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
                  {models.map((model) => (
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
