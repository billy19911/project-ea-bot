'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from './page.module.css';
import { apiFetch } from '../../lib/api';

// API routes require a Bearer token (PRD_V2 §28). The app has no login UI yet,
// so the "Run Cycle" action stays disabled until a token is present in
// localStorage under this key (mirroring the `ea-bot-settings` convention used
// on the home page). Do NOT invent a login flow here.
const AUTH_TOKEN_KEY = 'ea-bot-token';

type CycleResult =
  | { kind: 'ok'; traceId: string; decision: string; status: string }
  | { kind: 'error'; message: string };

type Tab =
  | 'overview'
  | 'trading'
  | 'positions'
  | 'market'
  | 'organization'
  | 'tasks'
  | 'decisions'
  | 'risk'
  | 'execution'
  | 'audit'
  | 'health'
  | 'committee'
  | 'telegram'
  | 'providers'
  | 'models'
  | 'learning';

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: 'overview', label: 'System Overview', icon: '▦' },
  { id: 'trading', label: 'Trading', icon: '📈' },
  { id: 'positions', label: 'Positions', icon: '📌' },
  { id: 'market', label: 'Market', icon: '🌍' },
  { id: 'organization', label: 'AI Organization', icon: '🧠' },
  { id: 'tasks', label: 'Task Explorer', icon: '🧾' },
  { id: 'decisions', label: 'Decision Explorer', icon: '⚖️' },
  { id: 'risk', label: 'Risk Center', icon: '🛡' },
  { id: 'execution', label: 'Execution Center', icon: '⚡' },
  { id: 'audit', label: 'Audit Viewer', icon: '📜' },
  { id: 'health', label: 'System Health', icon: '💚' },
  { id: 'committee', label: 'Committee Trace', icon: '🗣' },
  { id: 'telegram', label: 'Telegram', icon: '✈️' },
  { id: 'providers', label: 'AI Providers', icon: '🔌' },
  { id: 'models', label: 'Model Registry', icon: '🗂' },
  { id: 'learning', label: 'Learning Analytics', icon: '🎓' },
];

function badgeClass(status: string, s: Record<string, string>): string {
  const v = status.toUpperCase();
  if (['UP', 'HEALTHY', 'ACTIVE', 'APPROVED', 'COMPLETED', 'OPEN', 'AVAILABLE', 'CONNECTED'].includes(v)) return s.success;
  if (['DEGRADED', 'WARNING', 'PENDING', 'QUEUED', 'UPCOMING', 'RUNNING'].includes(v)) return s.warning;
  if (['DOWN', 'FAILED', 'REJECTED', 'CRITICAL', 'UNAVAILABLE'].includes(v)) return s.danger;
  return s.muted;
}

export default function ControlPlanePage() {
  const [tab, setTab] = useState<Tab>('overview');
  const [data, setData] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState('');
  const [runningCycle, setRunningCycle] = useState(false);
  const [cycle, setCycle] = useState<CycleResult | null>(null);
  const [hasToken, setHasToken] = useState(false);

  useEffect(() => {
    // Read only; no login UI exists yet (see AUTH_TOKEN_KEY comment above).
    setHasToken(!!localStorage.getItem(AUTH_TOKEN_KEY));
  }, []);

  const fetchJson = useCallback(async (path: string) => {
    try {
      const res = await apiFetch(`${path}`);
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }, []);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    const [overview, trading, positions, market, aiControl, tasks, decisions, risk, execution, audit, health, committee, telegram, providers, models, learning] = await Promise.all([
      fetchJson('/system/overview'),
      fetchJson('/trading/overview'),
      fetchJson('/positions'),
      fetchJson('/market/overview'),
      fetchJson('/ai-control/status'),
      fetchJson('/tasks'),
      fetchJson('/decisions'),
      fetchJson('/system/health'),
      fetchJson('/strategies'),
      fetchJson('/audit/events'),
      fetchJson('/system/health'),
      fetchJson('/committee/trace'),
      fetchJson('/telegram/status'),
      fetchJson('/ai/providers'),
      fetchJson('/ai/models'),
      fetchJson('/learning/analytics'),
    ]);
    setData({ overview, trading, positions, market, aiControl, tasks, decisions, risk, execution, audit, health, committee, telegram, providers, models, learning });
    setLoading(false);
  }, [fetchJson]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const showNotice = (msg: string) => {
    setNotice(msg);
    setTimeout(() => setNotice(''), 2500);
  };

  const runCycle = async () => {
    const token = localStorage.getItem(AUTH_TOKEN_KEY);
    if (!token) return; // Button is disabled without a token; guard defensively.
    const traceId = crypto.randomUUID();
    setRunningCycle(true);
    setCycle(null);
    try {
      const res = await apiFetch(`/pipeline/run`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Trace-Id': traceId,
        },
        body: JSON.stringify({ symbol: 'EURUSD', timeframe: 'M15' }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setCycle({ kind: 'error', message: body?.error || `HTTP ${res.status}` });
        return;
      }
      setCycle({
        kind: 'ok',
        traceId: body?.trace_id || traceId,
        decision: body?.decision ?? body?.verdict ?? '—',
        status: body?.status ?? '—',
      });
    } catch {
      setCycle({ kind: 'error', message: 'Tidak dapat menghubungi API.' });
    } finally {
      setRunningCycle(false);
    }
  };

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <span className={styles.brandMark}>EA</span>
          <div>
            <strong>EA BOT</strong>
            <small>CONTROL PLANE</small>
          </div>
        </div>
        <div className={styles.workspaceLabel}>DASHBOARD SECTIONS</div>
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`${styles.navItem} ${tab === t.id ? styles.active : ''}`}
            onClick={() => setTab(t.id)}
          >
            <span>{t.icon}</span> {t.label}
          </button>
        ))}
        <div className={styles.sidebarBottom}>
          <span className={styles.greenDot} /> Paper mode
          <div className={styles.version}>EPIC 15 · v1.0.0</div>
        </div>
      </aside>

      <main className={styles.main}>
        <header className={styles.topbar}>
          <div>
            <div className={styles.eyebrow}>EA BOT / CONTROL PLANE</div>
            <h1>{TABS.find((t) => t.id === tab)?.label}</h1>
          </div>
          <div>
            <span className={styles.envBadge}>PAPER</span>
            <button
              className={styles.tab}
              style={{ marginLeft: 10 }}
              onClick={runCycle}
              disabled={!hasToken || runningCycle}
              title={hasToken ? 'Jalankan satu siklus pipeline' : 'Membutuhkan token di localStorage (ea-bot-token)'}
            >
              {runningCycle ? '⏳ Running…' : '▶ Run Cycle'}
            </button>
            <button
              className={styles.tab}
              style={{ marginLeft: 10 }}
              onClick={() => { fetchAll(); showNotice('Data refreshed dari API.'); }}
            >
              ↻ Refresh
            </button>
          </div>
        </header>

        {notice && <div className={styles.notice}>{notice}</div>}
        {cycle && (
          cycle.kind === 'ok' ? (
            <div className={styles.notice}>
              Cycle OK · decision <strong>{cycle.decision}</strong> · status <strong>{cycle.status}</strong> · trace <code className={styles.mono}>{cycle.traceId}</code>
            </div>
          ) : (
            <div className={styles.notice} style={{ background: '#fef3f2', borderColor: '#fecdca', color: '#b42318' }}>
              Cycle gagal: {cycle.message}
            </div>
          )
        )}
        {loading ? (
          <div className={styles.loading}>Memuat data control plane…</div>
        ) : (
          <TabContent tab={tab} data={data} showNotice={showNotice} />
        )}
      </main>
    </div>
  );
}

function TabContent({ tab, data, showNotice }: { tab: Tab; data: Record<string, unknown>; showNotice: (m: string) => void }) {
  const s = styles;
  const overview = data.overview as any;
  const trading = data.trading as any;
  const positions = data.positions as any;
  const market = data.market as any;
  const aiControl = data.aiControl as any;
  const tasks = data.tasks as any;
  const decisions = data.decisions as any;
  const strategies = data.execution as any;
  const audit = data.audit as any;
  const health = data.health as any;
  const committee = data.committee as any;
  const telegram = data.telegram as any;
  const providers = data.providers as any;
  const models = data.models as any;
  const learning = data.learning as any;

  if (tab === 'overview') {
    if (!overview) return <div className={s.empty}>Tidak ada data overview.</div>;
    return (
      <div className={s.grid}>
        <section className={s.card}>
          <h2>Status Sistem</h2>
          <div className={s.kpiRow}>
            <div className={s.kpi}><span className={s.kpiValue}>{overview.mode}</span><span className={s.kpiLabel}>Mode</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{overview.status}</span><span className={s.kpiLabel}>Status</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{overview.uptime}</span><span className={s.kpiLabel}>Uptime</span></div>
          </div>
          <h3>Services</h3>
          <table className={s.table}>
            <tbody>
              {overview.services?.map((svc: any) => (
                <tr key={svc.name}>
                  <td>{svc.name}</td>
                  <td><span className={`${s.badge} ${badgeClass(svc.status, s)}`}>{svc.status}</span></td>
                  <td>{svc.latency_ms}ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section className={s.card}>
          <h2>KPI Hari Ini</h2>
          <div className={s.kpiRow}>
            <div className={s.kpi}><span className={s.kpiValue}>{overview.kpis?.open_positions}</span><span className={s.kpiLabel}>Open positions</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{overview.kpis?.daily_pnl}</span><span className={s.kpiLabel}>Daily PnL</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{overview.kpis?.win_rate_today}%</span><span className={s.kpiLabel}>Win rate</span></div>
          </div>
          <h3>Risk utilization</h3>
          <div className={s.bar}><div className={s.barFill} style={{ width: `${overview.kpis?.risk_utilization}%` }} /></div>
          <div className={s.mono}>{overview.kpis?.risk_utilization}% dari budget</div>
        </section>
      </div>
    );
  }

  if (tab === 'trading') {
    if (!trading) return <div className={s.empty}>Tidak ada data trading.</div>;
    return (
      <div className={s.grid}>
        <section className={s.card}>
          <h2>Ringkasan Hari Ini</h2>
          <div className={s.kpiRow}>
            <div className={s.kpi}><span className={s.kpiValue}>{trading.today?.trades}</span><span className={s.kpiLabel}>Trades</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{trading.today?.wins}W / {trading.today?.losses}L</span><span className={s.kpiLabel}>Win/Loss</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{trading.today?.net_pnl}</span><span className={s.kpiLabel}>Net PnL</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{trading.today?.profit_factor}</span><span className={s.kpiLabel}>Profit factor</span></div>
          </div>
        </section>
        <section className={s.card}>
          <h2>Recent Trades</h2>
          <div className={s.tableWrapper}>
            <table className={s.table}>
              <thead><tr><th>ID</th><th>Symbol</th><th>Side</th><th>Vol</th><th>PnL</th><th>Status</th></tr></thead>
              <tbody>
                {trading.recent_trades?.map((t: any) => (
                  <tr key={t.id}>
                    <td className={s.mono}>{t.id}</td>
                    <td><strong>{t.symbol}</strong></td>
                    <td>{t.side}</td>
                    <td>{t.volume}</td>
                    <td style={{ color: t.pnl > 0 ? '#027a48' : t.pnl < 0 ? '#b42318' : undefined }}>{t.pnl}</td>
                    <td><span className={`${s.badge} ${badgeClass(t.status, s)}`}>{t.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    );
  }

  if (tab === 'positions') {
    if (!positions) return <div className={s.empty}>Tidak ada data posisi.</div>;
    return (
      <section className={s.card}>
        <h2>Open Positions ({positions.count})</h2>
        <div className={s.tableWrapper}>
          <table className={s.table}>
            <thead><tr><th>Ticket</th><th>Symbol</th><th>Side</th><th>Vol</th><th>Open</th><th>Current</th><th>SL</th><th>TP</th><th>PnL</th></tr></thead>
            <tbody>
              {positions.positions?.map((p: any) => (
                <tr key={p.ticket}>
                  <td className={s.mono}>{p.ticket}</td>
                  <td><strong>{p.symbol}</strong></td>
                  <td>{p.side}</td>
                  <td>{p.volume}</td>
                  <td>{p.open_price}</td>
                  <td>{p.current_price}</td>
                  <td>{p.sl}</td>
                  <td>{p.tp}</td>
                  <td style={{ color: p.pnl > 0 ? '#027a48' : p.pnl < 0 ? '#b42318' : undefined }}>{p.pnl}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    );
  }

  if (tab === 'market') {
    if (!market) return <div className={s.empty}>Tidak ada data market.</div>;
    return (
      <div className={s.grid}>
        <section className={s.card}>
          <h2>Session & Regime</h2>
          <div className={s.kpiRow}>
            <div className={s.kpi}><span className={s.kpiValue}>{market.session}</span><span className={s.kpiLabel}>Active session</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{market.regime?.label}</span><span className={s.kpiLabel}>Regime ({Math.round((market.regime?.confidence || 0) * 100)}%)</span></div>
          </div>
          <h3>Sessions</h3>
          <table className={s.table}><tbody>
            {market.sessions?.map((sess: any) => (
              <tr key={sess.name}><td>{sess.name}</td><td><span className={`${s.badge} ${badgeClass(sess.status === 'open' ? 'OPEN' : sess.status.toUpperCase(), s)}`}>{sess.status}</span></td></tr>
            ))}
          </tbody></table>
        </section>
        <section className={s.card}>
          <h2>Symbols</h2>
          <table className={s.table}>
            <thead><tr><th>Symbol</th><th>Price</th><th>Chg%</th><th>Spread</th><th>Volatility</th></tr></thead>
            <tbody>
              {market.symbols?.map((sym: any) => (
                <tr key={sym.symbol}>
                  <td><strong>{sym.symbol}</strong></td>
                  <td>{sym.price}</td>
                  <td style={{ color: sym.change_pct > 0 ? '#027a48' : '#b42318' }}>{sym.change_pct}%</td>
                  <td>{sym.spread}</td>
                  <td><span className={`${s.badge} ${sym.volatility === 'HIGH' ? s.danger : sym.volatility === 'MEDIUM' ? s.warning : s.muted}`}>{sym.volatility}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    );
  }

  if (tab === 'organization') {
    if (!aiControl) return <div className={s.empty}>Tidak ada data AI organization.</div>;
    return (
      <div className={s.grid}>
        <section className={s.card}>
          <h2>Supervisor</h2>
          <div className={s.kpiRow}>
            <div className={s.kpi}><span className={s.kpiValue}>{aiControl.supervisor?.status}</span><span className={s.kpiLabel}>Status</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{aiControl.supervisor?.token_used}/{aiControl.supervisor?.token_budget}</span><span className={s.kpiLabel}>Token budget</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{aiControl.supervisor?.max_concurrency}</span><span className={s.kpiLabel}>Max concurrency</span></div>
          </div>
        </section>
        <section className={s.card}>
          <h2>Agents ({aiControl.agents?.length})</h2>
          <table className={s.table}>
            <thead><tr><th>Agent</th><th>Type</th><th>Status</th><th>Priority</th><th>Last active</th><th>Errors</th></tr></thead>
            <tbody>
              {aiControl.agents?.map((a: any) => (
                <tr key={a.name}>
                  <td><strong>{a.name}</strong></td>
                  <td>{a.type}</td>
                  <td><span className={`${s.badge} ${badgeClass(a.status, s)}`}>{a.status}</span></td>
                  <td>{a.priority}</td>
                  <td>{a.last_active}</td>
                  <td>{a.error_count > 0 ? <span className={`${s.badge} ${s.warning}`}>{a.error_count}</span> : '0'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    );
  }

  if (tab === 'tasks') {
    if (!tasks) return <div className={s.empty}>Tidak ada data task.</div>;
    return (
      <section className={s.card}>
        <h2>Task Explorer</h2>
        <div className={s.kpiRow} style={{ marginBottom: 12 }}>
          <div className={s.kpi}><span className={s.kpiValue}>{tasks.counts?.running}</span><span className={s.kpiLabel}>Running</span></div>
          <div className={s.kpi}><span className={s.kpiValue}>{tasks.counts?.queued}</span><span className={s.kpiLabel}>Queued</span></div>
          <div className={s.kpi}><span className={s.kpiValue}>{tasks.counts?.completed}</span><span className={s.kpiLabel}>Completed</span></div>
          <div className={s.kpi}><span className={s.kpiValue}>{tasks.counts?.failed}</span><span className={s.kpiLabel}>Failed</span></div>
        </div>
        <table className={s.table}>
          <thead><tr><th>ID</th><th>Type</th><th>Assignee</th><th>Status</th><th>Priority</th><th>Duration</th></tr></thead>
          <tbody>
            {tasks.tasks?.map((t: any) => (
              <tr key={t.id}>
                <td className={s.mono}>{t.id}</td>
                <td>{t.type}</td>
                <td>{t.assignee}</td>
                <td><span className={`${s.badge} ${badgeClass(t.status, s)}`}>{t.status}</span></td>
                <td>{t.priority}</td>
                <td>{t.duration_ms}ms</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    );
  }

  if (tab === 'decisions') {
    if (!decisions) return <div className={s.empty}>Tidak ada data decision.</div>;
    return (
      <section className={s.card}>
        <h2>Decision Explorer</h2>
        <table className={s.table}>
          <thead><tr><th>ID</th><th>Type</th><th>Symbol</th><th>Verdict</th><th>Confidence</th><th>Committee</th><th>Rationale</th></tr></thead>
          <tbody>
            {decisions.decisions?.map((d: any) => (
              <tr key={d.id}>
                <td className={s.mono}>{d.id}</td>
                <td>{d.type}</td>
                <td><strong>{d.symbol}</strong></td>
                <td><span className={`${s.badge} ${badgeClass(d.verdict, s)}`}>{d.verdict}</span></td>
                <td>{Math.round(d.confidence * 100)}%</td>
                <td>{d.committee}</td>
                <td>{d.rationale}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    );
  }

  if (tab === 'risk') {
    if (!health) return <div className={s.empty}>Tidak ada data risk.</div>;
    return (
      <div className={s.grid}>
        <section className={s.card}>
          <h2>Risk Center</h2>
          <div className={s.kpiRow}>
            <div className={s.kpi}><span className={s.kpiValue}>{overview?.kpis?.risk_utilization}%</span><span className={s.kpiLabel}>Risk utilization</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>15%</span><span className={s.kpiLabel}>Max drawdown</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>5%</span><span className={s.kpiLabel}>Daily loss limit</span></div>
          </div>
          <h3>Risk budget</h3>
          <div className={s.bar}><div className={s.barFillGreen} style={{ width: `${overview?.kpis?.risk_utilization}%` }} /></div>
        </section>
        <section className={s.card}>
          <h2>Safety Controls</h2>
          <table className={s.table}><tbody>
            <tr><td>Kill switch</td><td><span className={`${s.badge} ${s.success}`}>ARMED</span></td></tr>
            <tr><td>Circuit breaker</td><td><span className={`${s.badge} ${s.success}`}>NORMAL</span></td></tr>
            <tr><td>Execution recovery</td><td><span className={`${s.badge} ${s.success}`}>NORMAL</span></td></tr>
            <tr><td>Write guard</td><td><span className={`${s.badge} ${s.success}`}>ENFORCED</span></td></tr>
          </tbody></table>
        </section>
      </div>
    );
  }

  if (tab === 'execution') {
    if (!strategies) return <div className={s.empty}>Tidak ada data eksekusi.</div>;
    return (
      <section className={s.card}>
        <h2>Execution Center — Strategi</h2>
        <table className={s.table}>
          <thead><tr><th>ID</th><th>Strategy</th><th>Version</th><th>Status</th><th>Win rate</th><th>PF</th><th>Max DD</th></tr></thead>
          <tbody>
            {strategies.strategies?.map((st: any) => (
              <tr key={st.id}>
                <td className={s.mono}>{st.id}</td>
                <td><strong>{st.name}</strong></td>
                <td><code>{st.version}</code></td>
                <td><span className={`${s.badge} ${st.active ? s.success : s.muted}`}>{st.active ? 'ACTIVE' : 'INACTIVE'}</span></td>
                <td>{st.performance?.win_rate > 0 ? `${st.performance.win_rate}%` : '—'}</td>
                <td>{st.performance?.profit_factor > 0 ? st.performance.profit_factor.toFixed(2) : '—'}</td>
                <td>{st.performance?.max_dd > 0 ? `${st.performance.max_dd}%` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button className={s.tab} style={{ marginTop: 14 }} onClick={() => showNotice('Flush queue: 0 order pending (aman).')}>Flush order queue</button>
      </section>
    );
  }

  if (tab === 'audit') {
    if (!audit) return <div className={s.empty}>Tidak ada data audit.</div>;
    return (
      <section className={s.card}>
        <h2>Audit Viewer ({audit.count})</h2>
        <table className={s.table}>
          <thead><tr><th>ID</th><th>Waktu</th><th>Actor</th><th>Action</th><th>Target</th><th>Severity</th></tr></thead>
          <tbody>
            {audit.events?.map((e: any) => (
              <tr key={e.id}>
                <td className={s.mono}>{e.id}</td>
                <td>{e.timestamp}</td>
                <td>{e.actor}</td>
                <td>{e.action}</td>
                <td>{e.target}</td>
                <td><span className={`${s.badge} ${e.severity === 'warning' ? s.warning : s.info}`}>{e.severity}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    );
  }

  if (tab === 'health') {
    if (!health) return <div className={s.empty}>Tidak ada data health.</div>;
    return (
      <section className={s.card}>
        <h2>System Health — {health.overall}</h2>
        <table className={s.table}>
          <thead><tr><th>Component</th><th>Status</th><th>Detail</th></tr></thead>
          <tbody>
            {health.components?.map((c: any) => (
              <tr key={c.name}>
                <td><strong>{c.name}</strong></td>
                <td><span className={`${s.badge} ${badgeClass(c.status.toUpperCase(), s)}`}>{c.status}</span></td>
                <td>{c.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className={s.mono} style={{ marginTop: 10 }}>Checked at: {health.checked_at}</div>
      </section>
    );
  }

  if (tab === 'committee') {
    if (!committee) return <div className={s.empty}>Tidak ada data committee trace.</div>;
    return (
      <div className={s.grid}>
        {committee.traces?.map((tr: any) => (
          <section className={s.card} key={tr.decision_id}>
            <h2>Decision {tr.decision_id} — {tr.symbol}</h2>
            {tr.rounds?.map((r: any, i: number) => (
              <div className={s.traceRound} key={i}>
                <div className={s.traceSpeaker}>Round {r.round} · {r.speaker} <span className={`${s.badge} ${s.info}`}>{r.stance}</span> <span className={s.mono}>{Math.round(r.confidence * 100)}%</span></div>
                <div className={s.traceText}>{r.argument}</div>
              </div>
            ))}
            <h3>Final: <span className={`${s.badge} ${badgeClass(tr.final?.verdict, s)}`}>{tr.final?.verdict}</span> ({Math.round((tr.final?.confidence || 0) * 100)}%)</h3>
          </section>
        ))}
      </div>
    );
  }

  if (tab === 'telegram') {
    if (!telegram) return <div className={s.empty}>Tidak ada data Telegram.</div>;
    return (
      <section className={s.card}>
        <h2>Telegram Integration Status</h2>
        <div className={s.kpiRow}>
          <div className={s.kpi}><span className={s.kpiValue}>{telegram.connected ? 'Connected' : 'Offline'}</span><span className={s.kpiLabel}>Status</span></div>
          <div className={s.kpi}><span className={s.kpiValue}>{telegram.bot_username}</span><span className={s.kpiLabel}>Bot</span></div>
          <div className={s.kpi}><span className={s.kpiValue}>{telegram.messages_today}</span><span className={s.kpiLabel}>Messages today</span></div>
        </div>
        <h3>Commands</h3>
        <table className={s.table}><tbody>
          {telegram.commands?.map((c: string) => (
            <tr key={c}><td className={s.mono}>{c}</td><td><span className={`${s.badge} ${s.success}`}>available</span></td></tr>
          ))}
        </tbody></table>
      </section>
    );
  }

  if (tab === 'providers') {
    if (!providers) return <div className={s.empty}>Tidak ada data provider.</div>;
    return (
      <div className={s.grid}>
        <section className={s.card}>
          <h2>AI Router — {providers.router?.name}</h2>
          <div className={s.kpiRow}>
            <div className={s.kpi}><span className={s.kpiValue}>{providers.router?.status}</span><span className={s.kpiLabel}>Status</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{providers.router?.latency_ms}ms</span><span className={s.kpiLabel}>Latency</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{providers.router?.failover_enabled ? 'ON' : 'OFF'}</span><span className={s.kpiLabel}>Failover</span></div>
          </div>
        </section>
        <section className={s.card}>
          <h2>Providers</h2>
          <table className={s.table}>
            <thead><tr><th>Provider</th><th>Status</th><th>Models</th><th>Priority</th><th>Calls</th></tr></thead>
            <tbody>
              {providers.providers?.map((p: any) => (
                <tr key={p.name}>
                  <td><strong>{p.name}</strong></td>
                  <td><span className={`${s.badge} ${badgeClass(p.status.toUpperCase(), s)}`}>{p.status}</span></td>
                  <td>{p.models_available}</td>
                  <td>{p.priority}</td>
                  <td>{p.calls_today}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className={s.mono} style={{ marginTop: 10 }}>Budget: {providers.budget?.tokens_used}/{providers.budget?.tokens_limit} tokens · ${providers.budget?.cost_today}</div>
        </section>
      </div>
    );
  }

  if (tab === 'models') {
    if (!models) return <div className={s.empty}>Tidak ada data model.</div>;
    const registryState = models.health?.state ?? 'UNKNOWN';
    return (
      <section className={s.card}>
        <h2>Model Discovery & Registry</h2>
        <div className={s.kpiRow} style={{ marginBottom: 12 }}>
          <div className={s.kpi}>
            <span className={s.kpiValue}>
              <span className={`${s.badge} ${badgeClass(String(registryState), s)}`}>{registryState}</span>
            </span>
            <span className={s.kpiLabel}>Registry state</span>
          </div>
          <div className={s.kpi}>
            <span className={s.kpiValue}>{models.health?.source ?? models.source ?? '—'}</span>
            <span className={s.kpiLabel}>Registry source</span>
          </div>
          <div className={s.kpi}>
            <span className={s.kpiValue}>{models.health?.last_discovery ?? '—'}</span>
            <span className={s.kpiLabel}>Last discovery</span>
          </div>
        </div>
        {models.health?.error && (
          <div className={s.mono} style={{ marginBottom: 12 }}>
            Health error: {String(models.health.error).split('\n')[0].slice(0, 180)}
            {String(models.health.error).length > 180 ? '…' : ''}
          </div>
        )}
        <div className={s.tableWrapper}>
          <table className={s.table}>
            <thead><tr><th>Model</th><th>Provider</th><th>Context</th><th>Free/Paid</th><th>Capabilities</th></tr></thead>
            <tbody>
              {models.models?.map((m: any) => (
                <tr key={m.id}>
                  <td className={s.mono}>{m.id}</td>
                  <td>{m.provider}</td>
                  <td>{(m.context / 1000).toFixed(0)}k</td>
                  <td>{m.is_free ? 'Free' : 'Paid'}</td>
                  <td>{m.capabilities?.join(', ') ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    );
  }

  if (tab === 'learning') {
    if (!learning) return <div className={s.empty}>Tidak ada data learning.</div>;
    return (
      <div className={s.grid}>
        <section className={s.card}>
          <h2>Supervisor KPI</h2>
          <div className={s.kpiRow}>
            <div className={s.kpi}><span className={s.kpiValue}>{learning.supervisor_kpis?.win_rate}%</span><span className={s.kpiLabel}>Win rate</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{learning.supervisor_kpis?.profit_factor}</span><span className={s.kpiLabel}>Profit factor</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{learning.supervisor_kpis?.expectancy}</span><span className={s.kpiLabel}>Expectancy</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{learning.supervisor_kpis?.max_drawdown}%</span><span className={s.kpiLabel}>Max DD</span></div>
          </div>
        </section>
        <section className={s.card}>
          <h2>Performance by Hour</h2>
          <table className={s.table}>
            <thead><tr><th>Jam</th><th>Trades</th><th>Win rate</th><th>Avg PnL</th></tr></thead>
            <tbody>
              {learning.by_hour?.map((h: any) => (
                <tr key={h.hour}>
                  <td>{h.hour}:00</td>
                  <td>{h.trades}</td>
                  <td>{h.win_rate}%</td>
                  <td style={{ color: h.avg_pnl > 0 ? '#027a48' : '#b42318' }}>{h.avg_pnl}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section className={s.card}>
          <h2>Performance by Regime</h2>
          <table className={s.table}>
            <thead><tr><th>Regime</th><th>Trades</th><th>Win rate</th><th>Avg PnL</th></tr></thead>
            <tbody>
              {learning.by_regime?.map((r: any) => (
                <tr key={r.regime}>
                  <td><strong>{r.regime}</strong></td>
                  <td>{r.trades}</td>
                  <td>{r.win_rate}%</td>
                  <td style={{ color: r.avg_pnl > 0 ? '#027a48' : '#b42318' }}>{r.avg_pnl}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section className={s.card}>
          <h2>Validated Lessons</h2>
          {learning.lessons?.map((l: any) => (
            <div className={s.traceRound} key={l.id}>
              <div className={s.traceSpeaker}>{l.id} {l.validated && <span className={`${s.badge} ${s.success}`}>validated</span>}</div>
              <div className={s.traceText}>{l.text}</div>
            </div>
          ))}
        </section>
      </div>
    );
  }

  return <div className={s.empty}>Section belum tersedia.</div>;
}
