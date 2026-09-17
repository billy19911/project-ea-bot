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

export default function AIControlPage() {
  const [agents, setAgents] = useState<AgentNode[]>([]);
  const activity: ActivityLog[] = [];
  const [errors, setErrors] = useState<AgentError[]>([]);
  const [models, setModels] = useState<ModelUsage[]>([]);
  const [reasoning, setReasoning] = useState('');
  const [supervisorStatus, setSupervisorStatus] = useState<SupervisorStatus | null>(null);
  const [source, setSource] = useState<SourceState>('unavailable');
  const [loading, setLoading] = useState(true);

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

          {/* Model Usage */}
          <section className={styles.card}>
            <h2>Penggunaan model LLM</h2>
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
                  {source === 'live' ? 'Tidak ada model tersedia.' : 'Data model tidak tersedia — API belum mengembalikan data. Cek token lalu muat ulang.'}
                </div>
              )}
            </div>
          </section>
        </div>
    </AppShell>
  );
}
