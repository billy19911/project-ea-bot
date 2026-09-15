'use client';

import { useEffect, useState, useCallback } from 'react';
import styles from './page.module.css';

// ── Types ───────────────────────────────────────────────────────────────────
interface ErrorRecord {
  id: string;
  timestamp: string;
  source: string;
  message: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  path?: string;
  statusCode?: number;
  traceId?: string;
}

interface MetricsSummary {
  uptime: number;
  timestamp: string;
  requests: Record<string, Record<string, number>>;
  tokenUsage: Record<string, { prompt: number; completion: number; calls: number; cost: number }>;
  agentStats: Record<string, { count: number; sumSeconds: number }>;
  recentErrors: ErrorRecord[];
  errorCount: number;
}

interface SupervisorStatus {
  supervisor: { status: string; routing_policy: string; max_concurrency: number; token_budget: number; token_used: number; uptime: string };
  agents: { name: string; type: string; status: string; priority: number; last_active: string; error_count: number }[];
  models: { model: string; provider: string; calls: number; prompt_tokens: number; completion_tokens: number; cost: number }[];
  errors: { id: string; timestamp: string; agent: string; message: string; severity: string }[];
}

// ── Helpers ─────────────────────────────────────────────────────────────────
function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${h}h ${m}m ${s}s`;
}

function severityClass(severity: string): string {
  switch (severity) {
    case 'critical': return styles.severityCritical;
    case 'high': return styles.severityHigh;
    case 'medium': return styles.severityMedium;
    case 'low': return styles.severityLow;
    default: return styles.severityLow;
  }
}

function statusClass(status: string): string {
  switch (status) {
    case 'active': return styles.statusActive;
    case 'idle': return styles.statusIdle;
    case 'error': return styles.statusError;
    default: return styles.statusIdle;
  }
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3001';

// ── Component ───────────────────────────────────────────────────────────────
export default function ObservabilityPage() {
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [supervisor, setSupervisor] = useState<SupervisorStatus | null>(null);
  const [errors, setErrors] = useState<ErrorRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<string>('');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [tab, setTab] = useState<'overview' | 'errors' | 'agents' | 'tokens'>('overview');

  const fetchData = useCallback(async () => {
    try {
      const [metricsRes, supervisorRes, errorsRes] = await Promise.allSettled([
        fetch(`${API_BASE}/observability/metrics`).then(r => r.json()),
        fetch(`${API_BASE}/ai-control/status`).then(r => r.json()),
        fetch(`${API_BASE}/observability/errors?limit=50`).then(r => r.json()),
      ]);

      if (metricsRes.status === 'fulfilled') setMetrics(metricsRes.value);
      if (supervisorRes.status === 'fulfilled') setSupervisor(supervisorRes.value);
      if (errorsRes.status === 'fulfilled') setErrors(errorsRes.value.errors || []);

      setLastRefresh(new Date().toLocaleTimeString());
    } catch (err) {
      console.error('Failed to fetch observability data:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchData]);

  const totalRequests = metrics
    ? Object.values(metrics.requests).reduce((sum, statuses) =>
        sum + Object.values(statuses).reduce((s, v) => s + v, 0), 0)
    : 0;

  const errorRequests = metrics
    ? Object.values(metrics.requests).reduce((sum, statuses) =>
        sum + Object.entries(statuses)
          .filter(([code]) => parseInt(code) >= 400)
          .reduce((s, [, v]) => s + v, 0), 0)
    : 0;

  const totalTokens = supervisor
    ? supervisor.models.reduce((sum, m) => sum + m.prompt_tokens + m.completion_tokens, 0)
    : 0;

  const totalCost = supervisor
    ? supervisor.models.reduce((sum, m) => sum + m.cost, 0)
    : 0;

  const activeAgentCount = supervisor
    ? supervisor.agents.filter(a => a.status === 'active').length
    : 0;

  const tabs = [
    { key: 'overview', label: 'Overview' },
    { key: 'errors', label: `Errors (${errors.length})` },
    { key: 'agents', label: 'Agent Metrics' },
    { key: 'tokens', label: 'Token Usage' },
  ] as const;

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <span className={styles.brandMark}>EA</span>
          <div><strong>EA BOT</strong><small>OBSERVABILITY</small></div>
        </div>
        <div className={styles.workspaceLabel}>MONITORING</div>
        <a href="/" className={styles.navItem}><span>←</span> Dashboard</a>
        <a href="/ai-control" className={styles.navItem}><span>🧠</span> AI Control</a>
        <a href="/control-plane" className={styles.navItem}><span>▦</span> Control Plane</a>
        <a href="/strategy" className={styles.navItem}><span>📡</span> Strategy</a>
        <a href="/observability" className={`${styles.navItem} ${styles.active}`}><span>📊</span> Observability</a>
        <div className={styles.sidebarBottom}>
          <span className={styles.greenDot} /> API terhubung
          <div className={styles.version}>Phase 27 · Live</div>
        </div>
      </aside>

      <main className={styles.main}>
        <header className={styles.topbar}>
          <div>
            <div className={styles.eyebrow}>EA BOT / OBSERVABILITY</div>
            <h1>System Observability</h1>
          </div>
          <div className={styles.topActions}>
            <label className={styles.autoRefreshLabel}>
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              Auto-refresh
            </label>
            <button className={styles.refreshBtn} onClick={fetchData}>↻ Refresh</button>
            {lastRefresh && <code className={styles.lastRefresh}>{lastRefresh}</code>}
          </div>
        </header>

        <div className={styles.pageBody}>
          {/* KPI Cards */}
          <div className={styles.kpiGrid}>
            <div className={styles.kpiCard}>
              <small>Uptime</small>
              <strong>{metrics ? formatUptime(metrics.uptime) : '—'}</strong>
            </div>
            <div className={styles.kpiCard}>
              <small>Total Requests</small>
              <strong>{totalRequests.toLocaleString()}</strong>
            </div>
            <div className={styles.kpiCard}>
              <small>Error Requests</small>
              <strong className={errorRequests > 0 ? styles.textDanger : ''}>{errorRequests}</strong>
            </div>
            <div className={styles.kpiCard}>
              <small>Active Agents</small>
              <strong>{activeAgentCount}</strong>
            </div>
            <div className={styles.kpiCard}>
              <small>Total Tokens</small>
              <strong>{totalTokens.toLocaleString()}</strong>
            </div>
            <div className={styles.kpiCard}>
              <small>LLM Cost</small>
              <strong>${totalCost.toFixed(3)}</strong>
            </div>
          </div>

          {/* Tabs */}
          <nav className={styles.tabs}>
            {tabs.map((t) => (
              <button
                key={t.key}
                className={tab === t.key ? styles.tabActive : ''}
                onClick={() => setTab(t.key as any)}
              >
                {t.label}
              </button>
            ))}
          </nav>

          {/* Tab Content */}
          {tab === 'overview' && (
            <>
              {/* Request Distribution */}
              <section className={styles.card}>
                <h2>Request Distribution</h2>
                <div className={styles.tableWrapper}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Endpoint</th>
                        <th>2xx</th>
                        <th>4xx</th>
                        <th>5xx</th>
                        <th>Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {metrics && Object.entries(metrics.requests).map(([route, statuses]) => {
                        const s2 = Object.entries(statuses).filter(([c]) => c.startsWith('2')).reduce((s, [, v]) => s + v, 0);
                        const s4 = Object.entries(statuses).filter(([c]) => c.startsWith('4')).reduce((s, [, v]) => s + v, 0);
                        const s5 = Object.entries(statuses).filter(([c]) => c.startsWith('5')).reduce((s, [, v]) => s + v, 0);
                        const total = s2 + s4 + s5;
                        return (
                          <tr key={route}>
                            <td><code>{route}</code></td>
                            <td className={styles.textSuccess}>{s2}</td>
                            <td className={s4 > 0 ? styles.textWarning : ''}>{s4}</td>
                            <td className={s5 > 0 ? styles.textDanger : ''}>{s5}</td>
                            <td><strong>{total}</strong></td>
                          </tr>
                        );
                      })}
                      {(!metrics || Object.keys(metrics.requests).length === 0) && (
                        <tr><td colSpan={5} className={styles.emptyRow}>Belum ada request data</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </section>

              {/* Agent Status */}
              {supervisor && (
                <section className={styles.card}>
                  <h2>Agent Status</h2>
                  <div className={styles.agentGrid}>
                    {supervisor.agents.map((agent) => (
                      <div key={agent.name} className={styles.agentCard}>
                        <div className={styles.agentHeader}>
                          <strong>{agent.name}</strong>
                          <span className={`${styles.badge} ${statusClass(agent.status)}`}>
                            {agent.status}
                          </span>
                        </div>
                        <div className={styles.agentMeta}>
                          <span>Type: {agent.type}</span>
                          <span>Priority: {agent.priority}</span>
                          {agent.error_count > 0 && (
                            <span className={styles.textDanger}>{agent.error_count} errors</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </>
          )}

          {tab === 'errors' && (
            <section className={styles.card}>
              <div className={styles.cardHeader}>
                <h2>Recent Errors</h2>
                <span className={styles.badge}>{errors.length} total</span>
              </div>
              {errors.length === 0 ? (
                <div className={styles.emptyState}>
                  <span>✓</span>
                  <p>Tidak ada error terbaru</p>
                </div>
              ) : (
                <div className={styles.tableWrapper}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Waktu</th>
                        <th>Source</th>
                        <th>Message</th>
                        <th>Severity</th>
                        <th>Path</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {errors.map((err) => (
                        <tr key={err.id}>
                          <td><code>{new Date(err.timestamp).toLocaleTimeString()}</code></td>
                          <td><strong>{err.source}</strong></td>
                          <td className={styles.msgCell}>{err.message}</td>
                          <td>
                            <span className={`${styles.badge} ${severityClass(err.severity)}`}>
                              {err.severity}
                            </span>
                          </td>
                          <td><code>{err.path || '—'}</code></td>
                          <td>{err.statusCode || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Also show supervisor errors */}
              {supervisor && supervisor.errors.length > 0 && (
                <>
                  <h3 style={{ marginTop: 16 }}>Agent Errors (dari Supervisor)</h3>
                  <div className={styles.errorList}>
                    {supervisor.errors.map((err) => (
                      <div key={err.id} className={styles.errorItem}>
                        <div className={styles.errorIcon}>!</div>
                        <div className={styles.errorContent}>
                          <div className={styles.errorHeader}>
                            <strong>{err.agent}</strong>
                            <code>{err.timestamp}</code>
                          </div>
                          <p>{err.message}</p>
                        </div>
                        <span className={`${styles.badge} ${severityClass(err.severity)}`}>
                          {err.severity}
                        </span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </section>
          )}

          {tab === 'agents' && supervisor && (
            <section className={styles.card}>
              <h2>Agent Execution Metrics</h2>
              <div className={styles.supervisorInfo}>
                <div><small>Routing Policy</small><strong>{supervisor.supervisor.routing_policy}</strong></div>
                <div><small>Max Concurrency</small><strong>{supervisor.supervisor.max_concurrency}</strong></div>
                <div><small>Token Budget</small><strong>{supervisor.supervisor.token_budget.toLocaleString()}</strong></div>
                <div><small>Token Used</small><strong>{supervisor.supervisor.token_used.toLocaleString()}</strong></div>
                <div><small>Budget Usage</small>
                  <strong>
                    {((supervisor.supervisor.token_used / supervisor.supervisor.token_budget) * 100).toFixed(1)}%
                  </strong>
                </div>
                <div><small>Supervisor Uptime</small><strong>{supervisor.supervisor.uptime}</strong></div>
              </div>

              <h3>Agent Details</h3>
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Agent</th>
                      <th>Type</th>
                      <th>Status</th>
                      <th>Priority</th>
                      <th>Last Active</th>
                      <th>Errors</th>
                    </tr>
                  </thead>
                  <tbody>
                    {supervisor.agents.map((agent) => (
                      <tr key={agent.name}>
                        <td><strong>{agent.name}</strong></td>
                        <td>{agent.type}</td>
                        <td>
                          <span className={`${styles.badge} ${statusClass(agent.status)}`}>
                            {agent.status}
                          </span>
                        </td>
                        <td>{agent.priority}</td>
                        <td>{agent.last_active}</td>
                        <td className={agent.error_count > 0 ? styles.textDanger : ''}>
                          {agent.error_count}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {tab === 'tokens' && supervisor && (
            <section className={styles.card}>
              <h2>LLM Token Usage</h2>
              <div className={styles.tokenSummary}>
                <div><small>Total Tokens</small><strong>{totalTokens.toLocaleString()}</strong></div>
                <div><small>Total Cost</small><strong>${totalCost.toFixed(3)}</strong></div>
                <div><small>Total Calls</small><strong>{supervisor.models.reduce((s, m) => s + m.calls, 0)}</strong></div>
                <div>
                  <small>Avg Tokens/Call</small>
                  <strong>
                    {Math.round(totalTokens / Math.max(1, supervisor.models.reduce((s, m) => s + m.calls, 0)))}
                  </strong>
                </div>
              </div>

              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Model</th>
                      <th>Provider</th>
                      <th>Calls</th>
                      <th>Prompt Tokens</th>
                      <th>Completion Tokens</th>
                      <th>Total Tokens</th>
                      <th>Cost (USD)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {supervisor.models.map((model) => (
                      <tr key={model.model}>
                        <td><strong>{model.model}</strong></td>
                        <td>{model.provider}</td>
                        <td>{model.calls}</td>
                        <td>{model.prompt_tokens.toLocaleString()}</td>
                        <td>{model.completion_tokens.toLocaleString()}</td>
                        <td><strong>{(model.prompt_tokens + model.completion_tokens).toLocaleString()}</strong></td>
                        <td className={model.cost > 0 ? styles.textDanger : styles.textMuted}>
                          {model.cost > 0 ? `$${model.cost.toFixed(3)}` : 'Gratis'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      </main>
    </div>
  );
}
