'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import AppShell from '@/components/AppShell';
import { apiFetch } from '@/lib/api';
import { useLiveQuotes } from '@/lib/useLiveQuotes';
import Pagination from '@/components/ui/pagination';
import styles from '../overview.module.css';

type Account = {
  login: number | null;
  server: string;
  balance: number;
  equity: number;
  margin: number;
  free_margin: number;
  margin_level: number;
  currency: string;
  name: string;
};

type Trade = {
  id: number;
  symbol: string;
  side: string;
  volume: number;
  pnl: number;
  status: string;
};

type Overview = {
  account: Account | null;
  open_positions: number;
  recent_trades: Trade[];
};

type Decision = { decision: string; status: string; symbol?: string; confidence?: number };

function fmtMoney(v: number | null | undefined, currency = ''): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const abs = Math.abs(v);
  const compact = abs >= 1_000_000 ? `${(v / 1_000_000).toFixed(2)}M` : abs >= 1000 ? `${(v / 1000).toFixed(1)}K` : v.toFixed(2);
  return `${compact} ${currency}`.trim();
}

function pnlClass(v: number): string {
  return v > 0 ? styles.pos : v < 0 ? styles.neg : '';
}

// A numeric value that briefly flashes when it changes — gives the "angka
// bergerak" feel for live equity / PnL without re-rendering the whole page.
function LiveValue({ value, format, className }: { value: number; format: (v: number) => string; className?: string }) {
  const [flash, setFlash] = useState(false);
  const prev = useRef<number>(value);
  useEffect(() => {
    if (prev.current !== value) {
      prev.current = value;
      setFlash(true);
      const t = setTimeout(() => setFlash(false), 900);
      return () => clearTimeout(t);
    }
  }, [value]);
  return <span className={`${flash ? 'liveFlash ' : ''}${className ?? ''}`.trim()}>{format(value)}</span>;
}

export default function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [live, setLive] = useState(true);

  const { positions: livePositions, account: liveAccount, status: liveStatus, lastUpdate } =
    useLiveQuotes({ positions: true, enabled: live });

  const load = useCallback(async () => {
    try {
      const [ovRes, decRes] = await Promise.all([
        apiFetch('/trading/overview'),
        apiFetch('/decisions?limit=1'),
      ]);
      if (ovRes.ok) setData(await ovRes.json());
      if (decRes.ok) {
        const d = await decRes.json();
        const list = Array.isArray(d.decisions) ? d.decisions : [];
        setDecision(list[0] ?? null);
      }
      setError(null);
    } catch {
      setError('Could not reach the API.');
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const acct = data?.account ?? null;

  // ── Merge REST snapshot with the live stream ──────────────────────────────
  // Live values win when present; otherwise we keep the last REST value. Never
  // fabricate a number — a missing field stays null and renders as "—".
  const liveEquity = typeof liveAccount?.equity === 'number' ? liveAccount.equity : null;
  const liveBalance = typeof liveAccount?.balance === 'number' ? liveAccount.balance : null;
  const liveFreeMargin = typeof liveAccount?.free_margin === 'number' ? liveAccount.free_margin : null;
  const liveMarginLevel = typeof liveAccount?.margin_level === 'number' ? liveAccount.margin_level : null;
  const currency = liveAccount?.currency ?? acct?.currency ?? '';

  const equity = liveEquity ?? acct?.equity ?? null;
  const balance = liveBalance ?? acct?.balance ?? null;
  const freeMargin = liveFreeMargin ?? acct?.free_margin ?? null;
  const marginLevel = liveMarginLevel ?? acct?.margin_level ?? null;

  // Positions: prefer the live stream (has moving profit); fall back to REST.
  const baseTrades = data?.recent_trades ?? [];
  const livePosRows: Trade[] = (livePositions ?? [])
    .filter((p) => p && p.ticket != null)
    .map((p) => {
      const pnl = typeof p.profit === 'number' ? p.profit : (typeof p.unrealized_pnl === 'number' ? p.unrealized_pnl : 0);
      return {
        id: Number(p.ticket) || 0,
        symbol: String(p.symbol ?? ''),
        side: String(p.side ?? ''),
        volume: Number(p.volume ?? 0),
        pnl,
        status: 'OPEN',
      };
    });

  const usingLive = liveStatus === 'live' && livePositions !== null && livePositions.length > 0;
  const trades: Trade[] = usingLive ? livePosRows : baseTrades;
  const totalPnl = trades.reduce((s, t) => s + (t.pnl || 0), 0);
  const openPositions = usingLive ? livePositions!.length : (data?.open_positions ?? 0);

  const pageCount = Math.max(1, Math.ceil(trades.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const visible = trades.slice((safePage - 1) * pageSize, safePage * pageSize);

  return (
    <AppShell
      activeKey="overview"
      eyebrow="Xynn / Overview"
      title="Command Center"
      actions={
        <label className="liveToggle" title="Streaming via WebSocket">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
          <span className={`liveDot ${live ? (liveStatus === 'live' ? 'liveOn' : 'liveOff') : 'liveOff'}`} />
          Live
          {live && liveStatus !== 'live' ? ` · ${liveStatus}` : ''}
          {lastUpdate ? ` · ${lastUpdate.toLocaleTimeString('id-ID')}` : ''}
        </label>
      }
    >
      <div className={styles.wrap}>
        {error && <div className={styles.error}>{error}</div>}

        {/* KPI row */}
        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Equity</span>
            <span className={`${styles.cardValue} ${styles.mono}`}>
              {equity !== null ? (
                <LiveValue value={equity} format={(v) => fmtMoney(v, currency)} />
              ) : '—'}
            </span>
            <span className={styles.cardHint}>
              Balance {balance !== null ? fmtMoney(balance, currency) : '—'}
            </span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Open PnL</span>
            <span className={`${styles.cardValue} ${styles.mono} ${pnlClass(totalPnl)}`}>
              {data || usingLive ? (
                <LiveValue value={totalPnl} format={(v) => fmtMoney(v, currency)} />
              ) : '—'}
            </span>
            <span className={styles.cardHint}>{openPositions} open positions</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Free Margin</span>
            <span className={`${styles.cardValue} ${styles.mono}`}>
              {freeMargin !== null ? (
                <LiveValue value={freeMargin} format={(v) => fmtMoney(v, currency)} />
              ) : '—'}
            </span>
            <span className={styles.cardHint}>
              Margin level {marginLevel !== null ? Math.round(marginLevel) : '—'}%
            </span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Last Decision</span>
            <span className={styles.cardValue}>
              {decision ? (
                <span
                  className={`${styles.pill} ${
                    decision.decision === 'WAIT' ? styles.pillNeutral : styles.pillOk
                  }`}
                >
                  {decision.decision}
                </span>
              ) : (
                '—'
              )}
            </span>
            <span className={styles.cardHint}>
              {decision?.symbol || 'no recent cycle'}
            </span>
          </div>
        </div>

        {/* Account strip */}
        <div className={styles.strip}>
          <div className={styles.stripItem}>
            <span className={styles.stripLabel}>Account</span>
            <span className={styles.stripValue}>{liveAccount?.login ?? acct?.login ?? '—'}</span>
          </div>
          <div className={styles.stripItem}>
            <span className={styles.stripLabel}>Server</span>
            <span className={styles.stripValue}>{liveAccount?.server ?? acct?.server ?? '—'}</span>
          </div>
          <div className={styles.stripItem}>
            <span className={styles.stripLabel}>Name</span>
            <span className={styles.stripValue}>{liveAccount?.name ?? acct?.name ?? '—'}</span>
          </div>
          <div className={styles.stripItem}>
            <span className={styles.stripLabel}>Currency</span>
            <span className={styles.stripValue}>{currency || '—'}</span>
          </div>
        </div>

        {/* Positions table */}
        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>
              Open Positions
              {usingLive ? <span className="posLiveTag"><span className="liveDot liveOn" />live</span> : null}
            </span>
            <button type="button" className={styles.btn} onClick={load}>
              Refresh
            </button>
          </div>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Ticket</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Volume</th>
                <th>PnL</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((t) => (
                <tr key={t.id}>
                  <td className={styles.mono}>{t.id}</td>
                  <td>{t.symbol}</td>
                  <td className={t.side === 'BUY' ? styles.pos : styles.neg}>{t.side}</td>
                  <td className={styles.mono}>{t.volume}</td>
                  <td className={`${styles.mono} ${pnlClass(t.pnl)}`}>
                    <LiveValue value={t.pnl} format={(v) => fmtMoney(v, currency)} />
                  </td>
                  <td>{t.status}</td>
                </tr>
              ))}
              {visible.length === 0 && (
                <tr>
                  <td colSpan={6} className={styles.empty}>
                    No open positions.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          {trades.length > 0 && (
            <Pagination
              page={safePage}
              pageSize={pageSize}
              total={trades.length}
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
              unitLabel="positions"
            />
          )}
        </div>
      </div>
    </AppShell>
  );
}
