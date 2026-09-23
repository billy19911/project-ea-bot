'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from './page.module.css';
import { apiFetch, generateTraceId, getAuthToken } from '../../lib/api';
import AppShell from '../../components/AppShell';
import DailyReport from '../../components/DailyReport';
import Pagination from '../../components/ui/pagination';

// Client-side pagination hook for long server-returned lists. The full array
// stays in memory; only the visible window is rendered. Page resets to 1 when
// the list length changes (e.g. after a refresh) so we never land on an empty
// page. Returns the slice to render plus a ready-to-drop-in <Pagination>.
function usePagedRows<T>(rows: T[] | undefined, initialSize = 25) {
  const data = rows ?? [];
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(initialSize);
  const pageCount = Math.max(1, Math.ceil(data.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const slice = data.slice((safePage - 1) * pageSize, safePage * pageSize);
  const pager = data.length > pageSize ? (
    <Pagination
      page={safePage}
      pageSize={pageSize}
      total={data.length}
      onPageChange={setPage}
      onPageSizeChange={setPageSize}
    />
  ) : null;
  return { rows: slice, pager };
}

// Agent routing priority is an enum tier (100/75/50/25/10) shared by all
// analysts, so a bare "75" reads like a dummy column. Show the tier label
// next to the number to make the meaning explicit.
const PRIORITY_TIERS: Record<number, string> = {
  100: 'CRITICAL',
  75: 'HIGH',
  50: 'NORMAL',
  25: 'LOW',
  10: 'BACKGROUND',
};

function priorityLabel(value: number | null | undefined): string {
  if (value == null) return '—';
  const tier = PRIORITY_TIERS[value];
  return tier ? `${tier} (${value})` : String(value);
}

// Activity timestamps arrive as ISO strings; show a compact local time and
// fall back to the raw value when it cannot be parsed.
function formatLastActive(value: string | null | undefined): string {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleTimeString();
}

// API routes require a Bearer token (PRD_V2 §28). The /login page mints and
// stores the token in localStorage under this key; the "Run Cycle" action
// tells the operator how to get one when it is missing.
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
  | 'learning'
  | 'daily';

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Ringkasan Sistem' },
  { id: 'trading', label: 'Trading' },
  { id: 'positions', label: 'Posisi' },
  { id: 'market', label: 'Pasar' },
  { id: 'organization', label: 'Organisasi AI' },
  { id: 'tasks', label: 'Penjelajah Task' },
  { id: 'decisions', label: 'Penjelajah Keputusan' },
  { id: 'risk', label: 'Pusat Risiko' },
  { id: 'execution', label: 'Pusat Eksekusi' },
  { id: 'audit', label: 'Audit' },
  { id: 'health', label: 'Kesehatan Sistem' },
  { id: 'committee', label: 'Jejak Komite' },
  { id: 'telegram', label: 'Telegram' },
  { id: 'providers', label: 'Provider AI' },
  { id: 'models', label: 'Registry Model' },
  { id: 'learning', label: 'Analitik Learning' },
  { id: 'daily', label: 'Laporan Harian' },
];

// Tab dikelompokkan (UI/UX ide #4): 16 tab datar terlalu bising. Grup
// mengurangi beban visual tanpa menghapus satu pun tab — semua tetap
// dapat dijangkau dalam dua klik. Label memakai istilah yang dipakai
// operator sehari-hari.
const TAB_GROUPS: { label: string; tabs: Tab[] }[] = [
  { label: 'Ringkasan', tabs: ['overview', 'health', 'audit'] },
  { label: 'Trading', tabs: ['trading', 'positions', 'market', 'daily'] },
  { label: 'Organisasi AI', tabs: ['organization', 'tasks', 'decisions', 'committee'] },
  { label: 'Risiko & Eksekusi', tabs: ['risk', 'execution'] },
  { label: 'Sistem', tabs: ['telegram', 'providers', 'models', 'learning'] },
];

const TAB_LABEL: Record<Tab, string> = TABS.reduce(
  (acc, t) => ({ ...acc, [t.id]: t.label }),
  {} as Record<Tab, string>,
);

const GROUP_OF: Record<Tab, string> = TAB_GROUPS.reduce(
  (acc, g) => {
    g.tabs.forEach((id) => {
      acc[id] = g.label;
    });
    return acc;
  },
  {} as Record<Tab, string>,
);

// Accepts anything: a missing/unknown status must never crash the page.
function badgeClass(status: unknown, s: Record<string, string>): string {
  const v = String(status ?? '').toUpperCase();
  if (['UP', 'HEALTHY', 'ACTIVE', 'APPROVED', 'COMPLETED', 'OPEN', 'AVAILABLE', 'CONNECTED'].includes(v)) return s.success;
  if (['DEGRADED', 'WARNING', 'PENDING', 'QUEUED', 'UPCOMING', 'RUNNING'].includes(v)) return s.warning;
  if (['DOWN', 'FAILED', 'REJECTED', 'CRITICAL', 'UNAVAILABLE'].includes(v)) return s.danger;
  return s.muted;
}

// Epoch seconds (e.g. 1789511131.4758043) → localized string. Anything that is
// missing, non-finite, or unparseable renders as an em dash — never a raw float
// and never the literal "Invalid Date".
function formatDiscoveryTime(ts: unknown): string {
  if (ts === null || ts === undefined || ts === '') return '—';
  const n = typeof ts === 'number' ? ts : Number(ts);
  if (!Number.isFinite(n) || n <= 0) return '—';
  const d = new Date(n * 1000);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString();
}

// Context window (tokens) → humanized "1.0M" / "128k". Invalid → em dash.
function formatContext(v: unknown): string {
  const n = typeof v === 'number' ? v : Number(v);
  if (!Number.isFinite(n) || n <= 0) return '—';
  if (n >= 1048576) return `${(n / 1048576).toFixed(1)}M`;
  return `${(n / 1024).toFixed(0)}k`;
}

// Service uptime in seconds → "3h 12m 40s". Missing/invalid → em dash.
// Never prints a raw float and never invents a value when uptime is unknown.
function nullableValue(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return '—';
    // Round to at most 2 decimals so binary float noise (-120.70000000000002)
    // never leaks into the UI. Integers stay integers.
    return Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100);
  }
  return String(v);
}

function nullablePercent(v: unknown): string {
  if (v === null || v === undefined) return '—';
  return `${v}%`;
}

function flagBadge(v: unknown, s: Record<string, string>, okText: string, badText: string) {
  if (v === true) return <span className={`${s.badge} ${s.success}`}>{okText}</span>;
  if (v === false) return <span className={`${s.badge} ${s.danger}`}>{badText}</span>;
  return <span className={`${s.badge} ${s.muted}`}>—</span>;
}

function invertedFlagBadge(v: unknown, s: Record<string, string>, okText: string, badText: string) {
  if (v === false) return <span className={`${s.badge} ${s.success}`}>{okText}</span>;
  if (v === true) return <span className={`${s.badge} ${s.danger}`}>{badText}</span>;
  return <span className={`${s.badge} ${s.muted}`}>—</span>;
}

function formatUptimeSeconds(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  const n = typeof v === 'number' ? v : Number(v);
  if (!Number.isFinite(n) || n < 0) return '—';
  const h = Math.floor(n / 3600);
  const m = Math.floor((n % 3600) / 60);
  const s = Math.floor(n % 60);
  return `${h}h ${m}m ${s}s`;
}

// Jam lokal singkat untuk timestamp dari API (ISO). Kembalikan '—' bila
// nilainya tidak bisa diparse — tidak pernah menebak waktu.
function formatClock(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  const d = new Date(String(v));
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
}

// Epoch seconds (from the API) → local clock string. Invalid → em dash.
function formatEpoch(v: unknown): string {
  const n = typeof v === 'number' ? v : Number(v);
  if (!Number.isFinite(n) || n <= 0) return '—';
  return formatClock(new Date(n * 1000).toISOString());
}

// Money/number display: thousands separators, at most 2 decimals.
function formatAmount(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  const n = typeof v === 'number' ? v : Number(v);
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString('id-ID', { maximumFractionDigits: 2 });
}

// Gateway errors often carry raw HTML (e.g. an upstream 404 page). Strip tags,
// collapse whitespace, and cap the length so the UI never dumps markup.
function shortError(raw: unknown): string {
  const s = String(raw ?? '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
  return s.length > 160 ? s.slice(0, 160) + '…' : s;
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
    // Read-only presence check; /login owns minting/storing the token.
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
    const [overview, trading, positions, market, aiControl, tasks, decisions, execution, audit, health, committee, telegram, providers, models, learning, reconciliation, mt5Mode, mt5Terminals] = await Promise.all([
      fetchJson('/system/overview'),
      fetchJson('/trading/overview'),
      fetchJson('/positions'),
      fetchJson('/market/overview'),
      fetchJson('/ai-control/status'),
      fetchJson('/tasks'),
      fetchJson('/decisions'),
      fetchJson('/strategies'),
      fetchJson('/audit/events'),
      fetchJson('/system/health'),
      fetchJson('/committee/trace'),
      fetchJson('/telegram/status'),
      fetchJson('/ai/providers'),
      fetchJson('/ai/models'),
      fetchJson('/learning/analytics'),
      fetchJson('/reconciliation/status'),
      fetchJson('/mt5/mode'),
      fetchJson('/mt5/terminals'),
    ]);
    setData({ overview, trading, positions, market, aiControl, tasks, decisions, execution, audit, health, committee, telegram, providers, models, learning, reconciliation, mt5Mode, mt5Terminals });
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
    const token = getAuthToken();
    if (!token) {
      setCycle({
        kind: 'error',
        message: 'Belum ada token. Buka halaman Masuk untuk membuat token dev, lalu klik lagi.',
      });
      return;
    }
    const traceId = generateTraceId();
    setRunningCycle(true);
    setCycle(null);
    try {
      const res = await apiFetch(`/pipeline/run`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Trace-Id': traceId,
        },
        // Kirim event eksplisit: payload datar {symbol, timeframe} membuat
        // pipeline memakai event_type UNKNOWN. MARKET_SCAN = scan manual dan
        // dirutekan ke komite MarketLead (prefix MARKET_).
        body: JSON.stringify({
          event: { event_type: 'MARKET_SCAN', symbol: 'EURUSD', timeframe: 'M15' },
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setCycle({
          kind: 'error',
          message:
            res.status === 401
              ? 'Token ditolak atau kedaluwarsa (401). Buka halaman Masuk untuk membuat token baru.'
              : body?.error || `HTTP ${res.status}`,
        });
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

  const mt5Mode = data.mt5Mode as { live_data?: boolean; execution?: string } | undefined;

  return (
    <AppShell
      activeKey="control-plane"
      eyebrow="EA BOT / CONTROL PLANE"
      title={TAB_LABEL[tab] ?? 'Control Plane'}
      actions={
        <>
          <span className={styles.envBadge}>{mt5Mode?.live_data ? 'LIVE DATA · READ-ONLY' : 'PAPER'}</span>
          <button
            className={styles.tab}
            onClick={runCycle}
            disabled={runningCycle}
            title={hasToken ? 'Jalankan satu siklus pipeline' : 'Membutuhkan token — buka halaman Masuk dulu'}
          >
            {runningCycle ? '⏳ Menjalankan…' : '▶ Jalankan Siklus'}
          </button>
          <button
            className={styles.tab}
            onClick={() => { fetchAll(); showNotice('Data refreshed dari API.'); }}
          >
            ↻ Muat ulang
          </button>
        </>
      }
    >
      {/* Section navigasi pindah dari sidebar ke tab strip in-page: sidebar
          sekarang milik AppShell (navigasi antar-halaman), bukan per-section.
          Ide #4: 16 tab dikelompokkan — baris grup di atas, tab grup terpilih
          di bawah. Semua tab tetap terjangkau, dua klik maksimal. */}
      <div className={styles.groupBar} role="tablist" aria-label="Grup Control Plane">
        {TAB_GROUPS.map((g) => (
          <button
            key={g.label}
            className={`${styles.groupBtn} ${GROUP_OF[tab] === g.label ? styles.groupActive : ''}`}
            onClick={() => setTab(g.tabs[0])}
            aria-pressed={GROUP_OF[tab] === g.label}
          >
            {g.label}
            <span className={styles.groupCount}>{g.tabs.length}</span>
          </button>
        ))}
      </div>
      <div className={styles.tabs} role="tablist" aria-label="Section Control Plane">
        {(TAB_GROUPS.find((g) => g.label === GROUP_OF[tab])?.tabs ?? []).map((id) => (
          <button
            key={id}
            className={`${styles.tab} ${tab === id ? styles.tabActive : ''}`}
            onClick={() => setTab(id)}
            aria-pressed={tab === id}
          >
            {TAB_LABEL[id]}
          </button>
        ))}
      </div>

      {notice && <div className={styles.notice}>{notice}</div>}
        {!hasToken && (
          <div className={styles.notice} style={{ background: 'var(--warning-soft)', borderColor: 'var(--warning-border)', color: 'var(--warning)' }}>
            Belum ada token — data di bawah akan kosong. Buka{' '}
            <a href="/login" style={{ color: 'inherit', fontWeight: 600 }}>halaman Masuk</a> untuk
            menyiapkan token.
          </div>
        )}
        {cycle && (
          cycle.kind === 'ok' ? (
            <div className={styles.notice}>
              Cycle OK · decision <strong>{cycle.decision}</strong> · status <strong>{cycle.status}</strong> · trace <code className={styles.mono}>{cycle.traceId}</code>
            </div>
          ) : (
            <div className={styles.notice} style={{ background: 'var(--danger-soft)', borderColor: 'var(--danger-border)', color: 'var(--danger)' }}>
              Cycle gagal: {cycle.message}
            </div>
          )
        )}
        {loading ? (
          <div className={styles.loading}>Memuat data control plane…</div>
        ) : (
          <>
            {/* Panel terminal dipromosikan ke atas (F3): aksi terminal & akun
                adalah kontrol utama, bukan detail yang terkubur di tab. */}
            <TerminalPanel terminals={data.mt5Terminals as TerminalsPayload | undefined} hasToken={hasToken} showNotice={showNotice} onRefresh={fetchAll} />
            <TabContent tab={tab} data={data} />
          </>
        )}
    </AppShell>
  );
}

function TabContent({ tab, data }: { tab: Tab; data: Record<string, unknown> }) {
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
  const reconciliation = data.reconciliation as any;

  // One paged view per long list. Hooks run unconditionally (required) — the
  // slices are only used inside the matching tab branch below.
  const tradesPage = usePagedRows<any>(trading?.recent_trades, 10);
  const positionsPage = usePagedRows<any>(positions?.positions, 25);
  const symbolsPage = usePagedRows<any>(market?.symbols, 15);
  const agentsPage = usePagedRows<any>(aiControl?.agents, 15);
  const tasksPage = usePagedRows<any>(tasks?.tasks, 25);
  const decisionsPage = usePagedRows<any>(decisions?.decisions, 25);
  const strategiesPage = usePagedRows<any>(strategies?.strategies, 25);
  const auditPage = usePagedRows<any>(audit?.events, 25);
  const healthPage = usePagedRows<any>(health?.components, 25);
  const providersPage = usePagedRows<any>(providers?.providers, 25);
  const modelsPage = usePagedRows<any>(models?.models, 50);

  if (tab === 'overview') {
    if (!overview) return <div className={s.empty}>Belum ada data ringkasan. Pastikan token aktif lalu klik Muat ulang.</div>;
    return (
      <div className={s.grid}>
        <section className={s.card}>
          <h2>Status Sistem</h2>
          <div className={s.kpiRow}>
            <div className={s.kpi}><span className={s.kpiValue}>{nullableValue(overview.mode)}</span><span className={s.kpiLabel}>Mode</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{overview.status}</span><span className={s.kpiLabel}>Status</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{formatUptimeSeconds(overview.uptime)}</span><span className={s.kpiLabel}>Uptime</span></div>
          </div>
          <h3>Services</h3>
          <table className={s.table}>
            <thead><tr><th>Service</th><th>Status</th><th>Latency</th></tr></thead>
            <tbody>
              {overview.services?.map((svc: any) => (
                <tr key={svc.name}>
                  <td>{svc.name}</td>
                  <td><span className={`${s.badge} ${badgeClass(svc.status, s)}`}>{svc.status}</span></td>
                  <td>{svc.latency_ms == null ? '—' : svc.latency_ms + 'ms'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section className={s.card}>
          <h2>KPI Hari Ini</h2>
<div className={s.kpiRow}>
              <div className={s.kpi}><span className={s.kpiValue}>{nullableValue(trading?.open_positions)}</span><span className={s.kpiLabel}>Open positions</span></div>
              <div className={s.kpi}><span className={s.kpiValue}>{formatAmount(trading?.today?.unrealized_pnl)}</span><span className={s.kpiLabel}>Unrealized PnL</span></div>
              <div className={s.kpi}><span className={s.kpiValue}>{
                (trading?.today?.wins != null && trading?.today?.losses != null && (trading?.today?.wins + trading?.today?.losses) > 0)
                  ? ((trading?.today?.wins / (trading?.today?.wins + trading?.today?.losses)) * 100).toFixed(1) + '%'
                  : '—'
              }</span><span className={s.kpiLabel}>Win rate</span></div>
            </div>
          <h3>Risk utilization</h3>
          {overview.kpis?.risk_utilization != null && (
            <div className={s.bar}><div className={s.barFill} style={{ width: `${overview.kpis.risk_utilization}%` }} /></div>
          )}
          <div className={s.mono}>{overview.kpis?.risk_utilization == null ? '—' : overview.kpis.risk_utilization + '% dari budget'}</div>
        </section>
      </div>
    );
  }

  if (tab === 'trading') {
    if (!trading) return <div className={s.empty}>Tidak ada data trading.</div>;
    return (
      <div className={s.grid}>
        {trading.account && (
          <section className={s.card}>
            <h2>Akun MT5 (Live)</h2>
            <div className={s.kpiRow}>
              <div className={s.kpi}><span className={s.kpiValue}>{nullableValue(trading.account.login)}</span><span className={s.kpiLabel}>Login</span></div>
              <div className={s.kpi}><span className={s.kpiValue}>{formatAmount(trading.account.balance)}</span><span className={s.kpiLabel}>Balance ({trading.account.currency ?? '—'})</span></div>
              <div className={s.kpi}><span className={s.kpiValue}>{formatAmount(trading.account.equity)}</span><span className={s.kpiLabel}>Equity</span></div>
              <div className={s.kpi}><span className={s.kpiValue}>{formatAmount(trading.account.free_margin)}</span><span className={s.kpiLabel}>Free margin</span></div>
            </div>
            <div className={s.mono}>{trading.account.server ?? '—'} · leverage {trading.account.leverage ?? '—'}</div>
          </section>
        )}
        <section className={s.card}>
          <h2>Ringkasan Hari Ini</h2>
          <div className={s.kpiRow}>
            <div className={s.kpi}><span className={s.kpiValue}>{nullableValue(trading.today?.trades)}</span><span className={s.kpiLabel}>Trades</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{trading.today?.wins == null || trading.today?.losses == null ? '—' : trading.today.wins + 'W / ' + trading.today.losses + 'L'}</span><span className={s.kpiLabel}>Win/Loss</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{formatAmount(trading.today?.unrealized_pnl)}</span><span className={s.kpiLabel}>Unrealized PnL</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{nullableValue(trading.today?.profit_factor)}</span><span className={s.kpiLabel}>Profit factor</span></div>
          </div>
        </section>
        <section className={s.card}>
          <h2>Recent Trades</h2>
          <div className={s.tableWrapper}>
            <table className={s.table}>
              <thead><tr><th>ID</th><th>Symbol</th><th>Side</th><th>Vol</th><th>PnL</th><th>Status</th></tr></thead>
              <tbody>
                {tradesPage.rows.map((t: any) => (
                  <tr key={t.id}>
                    <td className={s.mono}>{t.id}</td>
                    <td><strong>{t.symbol}</strong></td>
                    <td>{t.side}</td>
                    <td>{t.volume}</td>
                    <td style={{ color: t.pnl > 0 ? 'var(--success)' : t.pnl < 0 ? 'var(--danger)' : undefined }}>{formatAmount(t.pnl)}</td>
                    <td><span className={`${s.badge} ${badgeClass(t.status, s)}`}>{t.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {tradesPage.pager}
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
              {positionsPage.rows.map((p: any) => {
                const pnl = p.unrealized_pnl ?? p.profit ?? null;
                return (
                <tr key={p.ticket}>
                  <td className={s.mono}>{p.ticket}</td>
                  <td><strong>{p.symbol}</strong></td>
                  <td>{p.side}</td>
                  <td>{p.quantity ?? p.volume ?? '—'}</td>
                  <td>{p.price_open ?? p.open_price ?? '—'}</td>
                  <td>{p.price_current ?? p.current_price ?? '—'}</td>
                  <td>{p.sl ?? '—'}</td>
                  <td>{p.tp ?? '—'}</td>
                  <td style={{ color: pnl == null ? undefined : pnl > 0 ? 'var(--success)' : pnl < 0 ? 'var(--danger)' : undefined }}>{formatAmount(pnl)}</td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {positionsPage.pager}
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
            <div className={s.kpi}><span className={s.kpiValue}>{nullableValue(market.session)}</span><span className={s.kpiLabel}>Active session</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{nullableValue(market.regime?.label)}</span><span className={s.kpiLabel}>{market.regime?.confidence == null ? 'Regime' : `Regime (${Math.round(market.regime.confidence * 100)}%)`}</span></div>
          </div>
          <h3>Sessions</h3>
          <table className={s.table}>
            <thead><tr><th>Session</th><th>Status</th></tr></thead>
            <tbody>
            {market.sessions?.length ? market.sessions.map((sess: any) => (
              <tr key={sess.name}><td>{sess.name}</td><td><span className={`${s.badge} ${badgeClass(sess.status === 'open' ? 'OPEN' : sess.status, s)}`}>{sess.status ?? '—'}</span></td></tr>
            )) : (
              <tr><td>—</td><td>Tidak ada data sesi.</td></tr>
            )}
          </tbody></table>
        </section>
        <section className={s.card}>
          <h2>Symbols</h2>
          <table className={s.table}>
            <thead><tr><th>Symbol</th><th>Price</th><th>Chg%</th><th>Spread</th><th>Volatility</th></tr></thead>
            <tbody>
              {symbolsPage.rows.map((sym: any) => (
                <tr key={sym.symbol}>
                  <td><strong>{sym.symbol}</strong></td>
                  <td>{sym.price ?? '—'}</td>
                  <td style={{ color: sym.change_pct == null ? undefined : sym.change_pct > 0 ? 'var(--success)' : 'var(--danger)' }}>{sym.change_pct == null ? '—' : `${sym.change_pct}%`}</td>
                  <td>{sym.spread ?? '—'}</td>
                  <td>{sym.volatility == null ? '—' : <span className={`${s.badge} ${sym.volatility === 'HIGH' ? s.danger : sym.volatility === 'MEDIUM' ? s.warning : s.muted}`}>{sym.volatility}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {symbolsPage.pager}
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
            <div className={s.kpi}><span className={s.kpiValue}>{aiControl.supervisor?.token_used == null || aiControl.supervisor?.token_budget == null ? '—' : `${aiControl.supervisor.token_used}/${aiControl.supervisor.token_budget}`}</span><span className={s.kpiLabel}>Token budget</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{nullableValue(aiControl.supervisor?.max_concurrency)}</span><span className={s.kpiLabel}>Max concurrency</span></div>
          </div>
        </section>
        <section className={s.card}>
          <h2>Agents ({aiControl.agents?.length})</h2>
          <table className={s.table}>
            <thead><tr><th>Agent</th><th>Type</th><th>Status</th><th>Runs</th><th>Priority</th><th>Last active</th><th>Errors</th></tr></thead>
            <tbody>
              {agentsPage.rows.map((a: any) => (
                <tr key={a.name}>
                  <td><strong>{a.name}</strong></td>
                  <td>{a.type}</td>
                  <td><span className={`${s.badge} ${badgeClass(a.status, s)}`}>{a.status}</span></td>
                  <td>{a.invocations ?? 0}</td>
                  <td>{priorityLabel(a.priority)}</td>
                  <td>{formatLastActive(a.lastActive ?? a.last_active)}</td>
                  <td>{(a.error_count ?? a.errorCount ?? 0) > 0 ? <span className={`${s.badge} ${s.warning}`}>{a.error_count ?? a.errorCount}</span> : '0'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {agentsPage.pager}
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
            {tasksPage.rows.map((t: any) => (
              <tr key={t.id}>
                <td className={s.mono}>{t.id}</td>
                <td>{t.type}</td>
                <td>{t.assignee}</td>
                <td><span className={`${s.badge} ${badgeClass(t.status, s)}`}>{t.status}</span></td>
                <td>{t.priority}</td>
                <td>{t.duration_ms == null ? '—' : `${t.duration_ms}ms`}</td>
              </tr>
            ))}
            {(!tasks.tasks || tasks.tasks.length === 0) && (
              <tr><td colSpan={6}>Tidak ada task berjalan.</td></tr>
            )}
          </tbody>
        </table>
        {tasksPage.pager}
      </section>
    );
  }

  if (tab === 'decisions') {
    if (!decisions) return <div className={s.empty}>Tidak ada data decision.</div>;
    return (
      <section className={s.card}>
        <h2>Decision Explorer</h2>
        <div className={s.tableWrapper}>
          <table className={s.table}>
            <thead><tr><th>ID</th><th>Event</th><th>Verdict</th><th>Status</th><th>Risk</th><th>Confidence</th><th>Summary</th><th>Waktu</th></tr></thead>
            <tbody>
              {decisionsPage.rows.map((d: any) => (
                <tr key={d.decision_id ?? d.event_id}>
                  <td className={s.mono}>{d.decision_id ?? '—'}</td>
                  <td>{d.event_type ?? '—'}</td>
                  <td><span className={`${s.badge} ${badgeClass(d.decision, s)}`}>{d.decision ?? '—'}</span></td>
                  <td>{d.status ?? '—'}</td>
                  <td>{d.risk_approved ? <span className={`${s.badge} ${s.success}`}>APPROVED</span> : <span className={`${s.badge} ${s.muted}`}>{d.risk_reason || 'REJECTED'}</span>}</td>
                  <td>{d.confidence == null ? '—' : `${Math.round(d.confidence * 100)}%`}</td>
                  <td>{d.summary ?? '—'}</td>
                  <td>{formatEpoch(d.recorded_at)}</td>
                </tr>
              ))}
              {(!decisions.decisions || decisions.decisions.length === 0) && (
                <tr><td colSpan={8}>Tidak ada decision tercatat.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        {decisionsPage.pager}
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
            <div className={s.kpi}><span className={s.kpiValue}>{overview?.kpis?.risk_utilization == null ? '—' : `${overview.kpis.risk_utilization}%`}</span><span className={s.kpiLabel}>Risk utilization</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{health.risk_gate?.max_drawdown_pct == null ? '—' : `${health.risk_gate.max_drawdown_pct}%`}</span><span className={s.kpiLabel}>Max drawdown</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{health.risk_gate?.max_daily_loss == null ? '—' : `${health.risk_gate.max_daily_loss}`}</span><span className={s.kpiLabel}>Daily loss limit</span></div>
          </div>
          <h3>Risk budget</h3>
          {overview?.kpis?.risk_utilization != null && (
            <div className={s.bar}><div className={s.barFillGreen} style={{ width: `${overview.kpis.risk_utilization}%` }} /></div>
          )}
        </section>
        <section className={s.card}>
          <h2>Safety Controls</h2>
          <table className={s.table}>
            <thead><tr><th>Control</th><th>Status</th></tr></thead>
            <tbody>
            <tr><td>Risk gate</td><td>{flagBadge(health.risk_gate?.safe, s, 'SAFE', 'UNSAFE')}</td></tr>
            <tr><td>Daily loss limit</td><td>{flagBadge(health.risk_gate?.flags?.daily_loss_ok, s, 'OK', 'BREACH')}</td></tr>
            <tr><td>Drawdown</td><td>{flagBadge(health.risk_gate?.flags?.drawdown_ok, s, 'OK', 'BREACH')}</td></tr>
            <tr><td>Margin</td><td>{flagBadge(health.risk_gate?.flags?.margin_ok, s, 'OK', 'BREACH')}</td></tr>
            <tr><td>Equity</td><td>{flagBadge(health.risk_gate?.flags?.equity_ok, s, 'OK', 'BREACH')}</td></tr>
            <tr><td>Reconciliation</td><td>{invertedFlagBadge(reconciliation?.last_report?.critical, s, 'OK', 'CRITICAL')} <span className={s.mono}>{reconciliation?.last_report ? `${reconciliation.last_report.total_mismatches} mismatch · ${reconciliation.history_count} run` : '—'}</span></td></tr>
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
            {strategiesPage.rows.map((st: any) => (
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
        {strategiesPage.pager}
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
            {auditPage.rows.map((e: any) => (
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
        {auditPage.pager}
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
            {healthPage.rows.map((c: any) => (
              <tr key={c.name}>
                <td><strong>{c.name}</strong></td>
                <td><span className={`${s.badge} ${badgeClass(c.status, s)}`}>{c.status ?? '—'}</span></td>
                <td>{c.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {healthPage.pager}
        {health.checked_at && <div className={s.mono} style={{ marginTop: 10 }}>Checked at: {health.checked_at}</div>}
      </section>
    );
  }

  if (tab === 'committee') {
    if (!committee) return <div className={s.empty}>Tidak ada data committee trace.</div>;
    return (
      <div className={s.grid}>
        {committee.traces?.map((tr: any) => (
          <section className={s.card} key={tr.decision_id}>
            <h2>Decision {tr.decision_id}{tr.symbol ? ` — ${tr.symbol}` : ''}</h2>
            {tr.rounds?.map((r: any, i: number) => (
              <div className={s.traceRound} key={i}>
                <div className={s.traceSpeaker}>Tahap {r.stage ?? i + 1} <span className={`${s.badge} ${badgeClass(r.status, s)}`}>{r.status ?? '—'}</span></div>
                <div className={s.traceText}>{r.detail ?? '—'}</div>
              </div>
            ))}
            <h3>Final: <span className={`${s.badge} ${badgeClass(tr.final?.verdict, s)}`}>{tr.final?.verdict ?? '—'}</span>{tr.final?.confidence != null ? ` (${Math.round(tr.final.confidence * 100)}%)` : ''}</h3>
          </section>
        ))}
        {(!committee.traces || committee.traces.length === 0) && (
          <div className={s.empty}>Belum ada trace komite.</div>
        )}
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
          <div className={s.kpi}><span className={s.kpiValue}>{telegram.bot_username ?? '—'}</span><span className={s.kpiLabel}>Bot</span></div>
          <div className={s.kpi}><span className={s.kpiValue}>{telegram.allowlist_size ?? '—'}</span><span className={s.kpiLabel}>Chat diizinkan</span></div>
        </div>
        <h3>Commands</h3>
        <table className={s.table}>
          <thead><tr><th>Command</th><th>Status</th></tr></thead>
          <tbody>
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
            <div className={s.kpi}><span className={s.kpiValue}>{providers.router?.latency_ms == null ? '—' : `${providers.router.latency_ms}ms`}</span><span className={s.kpiLabel}>Latency</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{providers.router?.failover_enabled ? 'ON' : 'OFF'}</span><span className={s.kpiLabel}>Failover</span></div>
          </div>
        </section>
        <section className={s.card}>
          <h2>Providers</h2>
          <table className={s.table}>
            <thead><tr><th>Provider</th><th>Status</th><th>Models</th><th>Priority</th><th>Calls</th></tr></thead>
            <tbody>
              {providersPage.rows.map((p: any) => (
                <tr key={p.name}>
                  <td><strong>{p.name}</strong></td>
                  <td><span className={`${s.badge} ${badgeClass(p.status, s)}`}>{p.status ?? '—'}</span></td>
                  <td>{p.models_available}</td>
                  <td>{p.priority}</td>
                  <td>{p.calls_today}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {providersPage.pager}
          {providers.budget ? (
            <div className={s.mono} style={{ marginTop: 10 }}>Budget: {providers.budget.tokens_used}/{providers.budget.tokens_limit} tokens · ${providers.budget.cost_today}</div>
          ) : (
            <div className={s.mono} style={{ marginTop: 10 }}>Budget: — (belum dilaporkan router)</div>
          )}
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
            <span className={s.kpiValue}>{formatDiscoveryTime(models.health?.last_discovery)}</span>
            <span className={s.kpiLabel}>Last discovery</span>
          </div>
        </div>
        {shortError(models.health?.error) && (
          <div className={s.mono} style={{ marginBottom: 12 }}>
            Health error: {shortError(models.health?.error)}
          </div>
        )}
        <div className={s.tableWrapper}>
          <table className={s.table}>
            <thead><tr><th>Model</th><th>Provider</th><th>Context</th><th>Free/Paid</th><th>Capabilities</th></tr></thead>
            <tbody>
              {modelsPage.rows.map((m: any) => (
                <tr key={m.id}>
                  <td className={s.mono}>{m.id}</td>
                  <td>{m.provider}</td>
                  <td>{formatContext(m.context)}</td>
                  <td>{m.is_free ? 'Free' : 'Paid'}</td>
                  <td>{m.capabilities?.join(', ') ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {modelsPage.pager}
      </section>
    );
  }

  if (tab === 'daily') {
    return <DailyReport />;
  }

  if (tab === 'learning') {
    if (!learning) return <div className={s.empty}>Tidak ada data learning.</div>;
    return (
      <div className={s.grid}>
        {learning.available === false && (
          <div className={s.empty}>Analytics belum tersedia — belum ada trade tertutup untuk dianalisis.</div>
        )}
        <section className={s.card}>
          <h2>Supervisor KPI</h2>
          <div className={s.kpiRow}>
            <div className={s.kpi}><span className={s.kpiValue}>{nullablePercent(learning.supervisor_kpis?.win_rate)}</span><span className={s.kpiLabel}>Win rate</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{nullableValue(learning.supervisor_kpis?.profit_factor)}</span><span className={s.kpiLabel}>Profit factor</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{nullableValue(learning.supervisor_kpis?.expectancy)}</span><span className={s.kpiLabel}>Expectancy</span></div>
            <div className={s.kpi}><span className={s.kpiValue}>{nullablePercent(learning.supervisor_kpis?.max_drawdown)}</span><span className={s.kpiLabel}>Max DD</span></div>
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
                  <td>{nullablePercent(h.win_rate)}</td>
                  <td style={{ color: h.avg_pnl > 0 ? 'var(--success)' : 'var(--danger)' }}>{h.avg_pnl}</td>
                </tr>
              ))}
              {(!learning.by_hour || learning.by_hour.length === 0) && (
                <tr><td colSpan={4}>Tidak ada data.</td></tr>
              )}
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
                  <td>{nullablePercent(r.win_rate)}</td>
                  <td style={{ color: r.avg_pnl > 0 ? 'var(--success)' : 'var(--danger)' }}>{r.avg_pnl}</td>
                </tr>
              ))}
              {(!learning.by_regime || learning.by_regime.length === 0) && (
                <tr><td colSpan={4}>Tidak ada data.</td></tr>
              )}
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
          {(!learning.lessons || learning.lessons.length === 0) && (
            <div>Tidak ada lessons tervalidasi.</div>
          )}
        </section>
      </div>
    );
  }

  return <div className={s.empty}>Section belum tersedia.</div>;
}

// ---------------------------------------------------------------------------
// Multi-terminal MT5 panel (Run 24)
// ---------------------------------------------------------------------------
// Lists configured + auto-detected terminals, lets the operator select the
// active one and arm/disarm real execution for it. Honesty rules: statuses
// come straight from the API (running/attached/eligible), arming is disabled
// without a token, and the arm button never claims success when the API
// rejected the request. Accounts may be LIVE — arming stays a manual step.

type TerminalAccount = {
  login?: number | string | null;
  server?: string | null;
  mode?: string | null;
  trade_mode?: string | null;
  balance?: number | null;
  equity?: number | null;
  currency?: string | null;
};

type TerminalEntry = {
  id: string;
  label?: string;
  folder?: string;
  execution_allowed?: boolean;
  source?: string;
  running?: boolean;
  pid?: number | null;
  attached?: boolean;
  selected?: boolean;
  account?: TerminalAccount | null;
};

type TerminalsPayload = {
  terminals?: TerminalEntry[];
  selected_id?: string | null;
  execution_armed?: boolean;
  attached_path?: string | null;
  accounts_probed_at?: string | null;
};

function TerminalPanel({
  terminals,
  hasToken,
  showNotice,
  onRefresh,
}: {
  terminals: TerminalsPayload | undefined;
  hasToken: boolean;
  showNotice: (m: string) => void;
  onRefresh: () => void;
}) {
  const s = styles;
  const [busy, setBusy] = useState(false);
  const [probing, setProbing] = useState(false);
  // Ide #5: sembunyikan terminal STOPPED secara default (biasanya 7 dari 9
  // entri hanya noise). Pilihan disimpan di localStorage agar tidak reset
  // setiap muat ulang. Terminal terpilih selalu tampil apa pun filternya.
  const [showStopped, setShowStopped] = useState(false);

  useEffect(() => {
    try {
      setShowStopped(localStorage.getItem('ea-bot-show-stopped') === '1');
    } catch {
      // localStorage tidak tersedia — tetap default tersembunyi.
    }
  }, []);

  const toggleStopped = () => {
    setShowStopped((prev) => {
      const next = !prev;
      try {
        localStorage.setItem('ea-bot-show-stopped', next ? '1' : '0');
      } catch {
        // abaikan
      }
      return next;
    });
  };

  const all = terminals?.terminals ?? [];
  const list = showStopped ? all : all.filter((t) => t.running || t.selected);
  const hiddenCount = all.length - list.length;
  const armed = terminals?.execution_armed === true;
  const selected = all.find((t) => t.selected);
  const probedAt = terminals?.accounts_probed_at ?? null;

  const [termPage, setTermPage] = useState(1);
  const [termPageSize, setTermPageSize] = useState(25);
  const termPageCount = Math.max(1, Math.ceil(list.length / termPageSize));
  const safeTermPage = Math.min(termPage, termPageCount);
  const visibleTerminals = list.slice((safeTermPage - 1) * termPageSize, safeTermPage * termPageSize);

  const post = async (path: string, body: Record<string, unknown>, okMsg: string) => {
    if (!hasToken) return;
    setBusy(true);
    try {
      const res = await apiFetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      // Never claim success on a rejection — show the API's own message.
      if (!res.ok) {
        showNotice(data?.message || `Gagal (HTTP ${res.status})`);
      } else {
        showNotice(data?.message || okMsg);
      }
      onRefresh();
    } catch {
      showNotice('Tidak dapat menghubungi API.');
    } finally {
      setBusy(false);
    }
  };

  // Probe akun: read-only, tapi memindahkan binding sementara — backend
  // menolak saat armed dan selalu memulihkan binding di finally. Pesannya
  // diambil apa adanya dari API (tidak pernah diklaim sukses palsu).
  const probe = async () => {
    if (!hasToken || probing) return;
    setProbing(true);
    try {
      const res = await apiFetch('/mt5/terminals/probe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const data = await res.json().catch(() => ({}));
      showNotice(data?.message || (res.ok ? 'Cek akun selesai.' : `Gagal (HTTP ${res.status})`));
      onRefresh();
    } catch {
      showNotice('Tidak dapat menghubungi API.');
    } finally {
      setProbing(false);
    }
  };

  const fmtBalance = (t: TerminalEntry) => {
    const acc = t.account;
    if (!acc || acc.balance == null) return '—';
    const n = typeof acc.balance === 'number' ? acc.balance.toLocaleString('id-ID') : acc.balance;
    return acc.currency ? `${n} ${acc.currency}` : String(n);
  };

  return (
    <section className={s.card} style={{ gridColumn: '1 / -1' }}>
      <h2>
        Terminal MT5{' '}
        {armed ? (
          <span className={`${s.badge} ${s.danger}`}>EXECUTION ARMED</span>
        ) : (
          <span className={`${s.badge} ${s.muted}`}>eksekusi OFF</span>
        )}
        <button
          className={s.tab}
          style={{ marginLeft: 'auto' }}
          onClick={toggleStopped}
          title={
            showStopped
              ? 'Sembunyikan terminal yang tidak berjalan'
              : 'Tampilkan juga terminal yang tidak berjalan'
          }
        >
          {showStopped ? 'Sembunyikan nonaktif' : `Tampilkan nonaktif${hiddenCount ? ` (${hiddenCount})` : ''}`}
        </button>
      </h2>
      {list.length === 0 ? (
        <div className={s.empty}>
          Tidak ada terminal terdeteksi. Jalankan terminal64.exe lalu klik Muat ulang.
        </div>
      ) : (
        <div className={s.tableWrapper}>
          <table className={s.table}>
            <thead>
              <tr>
                <th>Terminal</th>
                <th>Status</th>
                <th>Akun</th>
                <th>Server</th>
                <th>Mode</th>
                <th>Balance</th>
                <th>Eksekusi</th>
                <th>Aksi</th>
              </tr>
            </thead>
            <tbody>
              {visibleTerminals.map((t) => (
                <tr key={t.id}>
                  <td>
                    <strong>{t.label || t.id}</strong>
                    <small>{t.id}{t.source === 'auto' ? ' · auto-detected' : ''}</small>
                  </td>
                  <td>
                    <span className={`${s.badge} ${t.running ? s.success : s.muted}`}>
                      {t.running ? 'RUNNING' : 'STOPPED'}
                    </span>{' '}
                    {t.selected && <span className={`${s.badge} ${s.info}`}>SELECTED</span>}
                    {t.running && t.pid ? <small>PID {t.pid}</small> : null}
                  </td>
                  <td className={s.mono}>{t.account?.login != null ? String(t.account.login) : '—'}</td>
                  <td className={s.mono}>{t.account?.server ?? '—'}</td>
                  <td>
                    {t.account?.mode ? (
                      <span className={`${s.badge} ${t.account.mode === 'LIVE' ? s.danger : t.account.mode === 'DEMO' ? s.success : s.warning}`}>
                        {t.account.mode}
                      </span>
                    ) : (
                      <span className={`${s.badge} ${s.muted}`}>—</span>
                    )}
                  </td>
                  <td className={s.mono}>{fmtBalance(t)}</td>
                  <td>
                    {t.execution_allowed ? (
                      <span className={`${s.badge} ${s.warning}`}>eligible</span>
                    ) : (
                      <span className={`${s.badge} ${s.muted}`}>data-only</span>
                    )}
                  </td>
                  <td>
                    <button
                      className={s.tab}
                      disabled={busy || !hasToken || !t.running || t.selected}
                      title={!hasToken ? 'Membutuhkan token di localStorage (ea-bot-token)' : t.selected ? 'Terminal sudah terpilih' : t.running ? 'Pilih terminal ini (binding di-attach ulang, arm di-reset)' : 'Terminal tidak berjalan'}
                      onClick={() => post('/mt5/terminals/select', { terminal_id: t.id }, `Terminal ${t.id} dipilih.`)}
                    >
                      Pilih
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {list.length > termPageSize && (
        <Pagination
          page={safeTermPage}
          pageSize={termPageSize}
          total={list.length}
          onPageChange={setTermPage}
          onPageSizeChange={setTermPageSize}
          unitLabel="terminals"
        />
      )}
      <div className={s.actions}>
        <button
          className={s.tab}
          disabled={!hasToken || probing || list.length === 0}
          title={!hasToken ? 'Membutuhkan token di localStorage (ea-bot-token)' : 'Baca akun tiap terminal yang berjalan (read-only, binding dipulihkan otomatis)'}
          onClick={probe}
        >
          {probing ? '⏳ Mengecek…' : 'Cek akun'}
        </button>
        <span className={s.mono}>
          {selected ? `Terpilih: ${selected.label || selected.id}` : 'Belum ada terminal terpilih'}
          {' · '}
          {probedAt ? `akun dicek ${formatClock(probedAt)}` : 'akun belum dicek'}
        </span>
      </div>
      {list.some((t) => t.running && t.account == null) && (
        <div className={s.mono} style={{ marginTop: 8, color: 'var(--text-muted)' }}>
          Terminal yang berjalan tapi kolom akun masih —: klik <strong>Cek akun</strong> untuk membacanya (read-only).
        </div>
      )}

      {/* Zona berbahaya: hanya aksi yang mengizinkan eksekusi order nyata. */}
      {selected?.execution_allowed && (
        <div className={s.dangerZone}>
          <strong>Zona berbahaya</strong>
          <button
            className={s.tab}
            disabled={busy || !hasToken || armed}
            title={
              !hasToken
                ? 'Membutuhkan token di localStorage (ea-bot-token)'
                : armed
                  ? 'Sudah armed'
                  : 'Izinkan eksekusi order nyata untuk terminal terpilih'
            }
            onClick={() => post('/mt5/terminals/arm', { armed: true }, 'Execution ARMED.')}
          >
            🔓 Arm Execution
          </button>
          <button
            className={s.tab}
            disabled={busy || !hasToken || !armed}
            title={armed ? 'Matikan izin eksekusi sekarang' : 'Tidak sedang armed'}
            onClick={() => post('/mt5/terminals/arm', { armed: false }, 'Execution disarmed.')}
          >
            🔒 Disarm
          </button>
          <span className={s.mono}>
            Arm hanya mengizinkan eksekusi lewat jalur yang sudah di-guard; order nyata tetap butuh aksi manual. Ganti terminal selalu me-reset arm ke OFF.
          </span>
        </div>
      )}
    </section>
  );
}
