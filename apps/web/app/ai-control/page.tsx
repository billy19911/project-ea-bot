'use client';

import { useEffect, useState } from 'react';
import styles from './page.module.css';

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
};
type SupervisorStatus = {
  supervisor: { status: string; routing_policy: string; max_concurrency: number; token_budget: number; token_used: number; uptime: string };
  agents: AgentNode[];
  models: ModelUsage[];
  errors: AgentError[];
};

export default function AIControlPage() {
  const [agents, setAgents] = useState<AgentNode[]>([]);
  const [activity, setActivity] = useState<ActivityLog[]>([]);
  const [errors, setErrors] = useState<AgentError[]>([]);
  const [models, setModels] = useState<ModelUsage[]>([]);
  const [reasoning, setReasoning] = useState('');
  const [supervisorStatus, setSupervisorStatus] = useState<SupervisorStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Fetch supervisor status
    fetch('/api/ai-control/status')
      .then(res => res.json())
      .then(data => {
        setSupervisorStatus(data);
        setAgents(data.agents);
        setModels(data.models);
        setErrors(data.errors);
      })
      .catch(err => console.error('Failed to fetch supervisor status:', err));

    // Fetch current reasoning
    fetch('/api/ai-control/reasoning')
      .then(res => res.json())
      .then(data => setReasoning(data.reasoning))
      .catch(err => console.error('Failed to fetch reasoning:', err));

    // TODO: WebSocket connection to Python service for real-time updates
  }, []);

  const totalTokens = models.reduce((sum, m) => sum + m.promptTokens + m.completionTokens, 0);
  const totalCost = models.reduce((sum, m) => sum + m.cost, 0);

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <span className={styles.brandMark}>EA</span>
          <div><strong>EA BOT</strong><small>AI CONTROL</small></div>
        </div>
        <div className={styles.workspaceLabel}>KONTROL</div>
        <a href="/" className={styles.navItem}><span>←</span> Kembali</a>
        <a href="/control-plane" className={styles.navItem}><span>▦</span> Control Plane</a>
        <a href="/observability" className={styles.navItem}><span>📊</span> Observability</a>
        <div className={styles.sidebarBottom}>
          <span className={styles.greenDot} /> Supervisor aktif
          <div className={styles.version}>Phase 23 · Live</div>
        </div>
      </aside>

      <main className={styles.main}>
        <header className={styles.topbar}>
          <div>
            <div className={styles.eyebrow}>EA BOT / AI CONTROL CENTER</div>
            <h1>AI Control Center</h1>
          </div>
          <div className={styles.topActions}>
            <span className={styles.envBadge}>LIVE</span>
          </div>
        </header>

        <div className={styles.pageBody}>
          {/* Supervisor Status */}
          {supervisorStatus && (
            <section className={styles.card}>
              <h2>Status supervisor</h2>
              <div className={styles.supervisorGrid}>
                <div><small>Status</small><strong className={styles.statusActive}>Aktif</strong></div>
                <div><small>Routing policy</small><strong>{supervisorStatus.supervisor.routing_policy}</strong></div>
                <div><small>Max concurrency</small><strong>{supervisorStatus.supervisor.max_concurrency}</strong></div>
                <div><small>Token budget</small><strong>{supervisorStatus.supervisor.token_budget}</strong></div>
                <div><small>Token used</small><strong>{supervisorStatus.supervisor.token_used}</strong></div>
                <div><small>Uptime</small><strong>{supervisorStatus.supervisor.uptime}</strong></div>
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
                    <span>Last: {agent.lastActive}</span>
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

          {/* Activity Log (placeholder - would connect to real logs in production) */}
          <section className={styles.card}>
            <h2>Log aktivitas agent</h2>
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Waktu</th>
                    <th>Agent</th>
                    <th>Action</th>
                    <th>Status</th>
                    <th>Durasi (ms)</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { id: 'A1', timestamp: '13:34:58', agent: 'supervisor', action: 'Route TREND_BULLISH → structure_analyst', status: 'success', duration: 12 },
                    { id: 'A2', timestamp: '13:34:56', agent: 'volatility_analyst', action: 'Analyze ATR + Bollinger bands', status: 'success', duration: 234 },
                    { id: 'A3', timestamp: '13:34:52', agent: 'structure_analyst', action: 'Detect support @ 2610.40', status: 'success', duration: 189 },
                    { id: 'A4', timestamp: '13:34:48', agent: 'supervisor', action: 'Aggregate 3 agent results', status: 'success', duration: 45 },
                    { id: 'A5', timestamp: '13:34:42', agent: 'news_sentiment', action: 'Fetch news failed (timeout)', status: 'error', duration: 5000 },
                  ].map((log) => (
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
              <div><small>Total token</small><strong>{totalTokens.toLocaleString()}</strong></div>
              <div><small>Total cost</small><strong>${totalCost.toFixed(3)}</strong></div>
              <div><small>Avg per call</small><strong>{Math.round(totalTokens / models.reduce((s, m) => s + m.calls, 0))} token</strong></div>
            </div>
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Provider</th>
                    <th>Calls</th>
                    <th>Prompt tokens</th>
                    <th>Completion tokens</th>
                    <th>Cost (USD)</th>
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
                        {model.cost > 0 ? `$${model.cost.toFixed(3)}` : 'Gratis'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}
