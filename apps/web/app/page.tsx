'use client';

import { useCallback, useEffect, useState } from 'react';
import AppShell from '@/components/AppShell';
import { apiFetch } from '@/lib/api';
import Pagination from '@/components/ui/pagination';
import styles from './overview.module.css';

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

export default function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const load = useCallback(async () => {
    setLoading(true);
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
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const acct = data?.account ?? null;
  const totalPnl = (data?.recent_trades ?? []).reduce((s, t) => s + (t.pnl || 0), 0);
  const trades = data?.recent_trades ?? [];
  const pageCount = Math.max(1, Math.ceil(trades.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const visible = trades.slice((safePage - 1) * pageSize, safePage * pageSize);

  return (
    <AppShell activeKey="overview" eyebrow="Xynn / Overview" title="Command Center">
      <div className={styles.wrap}>
        {error && <div className={styles.error}>{error}</div>}
        {loading && !data && <div className={styles.loading}>Loading overview…</div>}

        {/* KPI row */}
        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Equity</span>
            <span className={`${styles.cardValue} ${styles.mono}`}>
              {acct ? fmtMoney(acct.equity, acct.currency) : '—'}
            </span>
            <span className={styles.cardHint}>
              Balance {acct ? fmtMoney(acct.balance, acct.currency) : '—'}
            </span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Open PnL</span>
            <span className={`${styles.cardValue} ${styles.mono} ${pnlClass(totalPnl)}`}>
              {data ? fmtMoney(totalPnl, acct?.currency ?? '') : '—'}
            </span>
            <span className={styles.cardHint}>{data?.open_positions ?? 0} open positions</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Free Margin</span>
            <span className={`${styles.cardValue} ${styles.mono}`}>
              {acct ? fmtMoney(acct.free_margin, acct.currency) : '—'}
            </span>
            <span className={styles.cardHint}>
              Margin level {acct ? Math.round(acct.margin_level) : '—'}%
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
            <span className={styles.stripValue}>{acct?.login ?? '—'}</span>
          </div>
          <div className={styles.stripItem}>
            <span className={styles.stripLabel}>Server</span>
            <span className={styles.stripValue}>{acct?.server ?? '—'}</span>
          </div>
          <div className={styles.stripItem}>
            <span className={styles.stripLabel}>Name</span>
            <span className={styles.stripValue}>{acct?.name ?? '—'}</span>
          </div>
          <div className={styles.stripItem}>
            <span className={styles.stripLabel}>Currency</span>
            <span className={styles.stripValue}>{acct?.currency ?? '—'}</span>
          </div>
        </div>

        {/* Positions table */}
        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Open Positions</span>
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
                  <td className={`${styles.mono} ${pnlClass(t.pnl)}`}>{fmtMoney(t.pnl, acct?.currency ?? '')}</td>
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
