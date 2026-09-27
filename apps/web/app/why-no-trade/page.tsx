'use client';

import { useMemo, useState } from 'react';
import AppShell from '@/components/AppShell';
import { useApiData } from '@/lib/useApiData';
import styles from '@/components/ops.module.css';

/**
 * Why No Trade — explains, from real data, why the bot is not trading.
 *
 * This page does not invent a reason. It reads the real decision ledger and
 * groups the non-executed outcomes (NO_TRADE / WAIT / BLOCKED / ERROR) so the
 * operator sees the actual distribution — e.g. "the risk gate blocked 40% of
 * cycles" or "the committee declined everything this session".
 */

type Decision = {
  decision_id?: string;
  event_type?: string;
  symbol?: string;
  decision?: string;
  status?: string;
  risk_approved?: boolean;
  risk_reason?: string;
  summary?: string;
};

type DecisionsBody = { decisions?: Decision[]; count?: number };

const NON_EXECUTED = new Set(['NO_TRADE', 'WAIT', 'BLOCKED', 'ERROR']);

function statusPill(status: string): string {
  const s = status.toUpperCase();
  if (s === 'BLOCKED' || s === 'ERROR') return `${styles.pill} ${styles.pillDanger}`;
  if (s === 'NO_TRADE' || s === 'WAIT') return `${styles.pill} ${styles.pillWarn}`;
  return `${styles.pill} ${styles.pillNeutral}`;
}

export default function WhyNoTradePage() {
  const { data, error, loading, refresh } = useApiData<DecisionsBody>('/decisions');
  const [filter, setFilter] = useState('');

  const all = useMemo(() => (Array.isArray(data?.decisions) ? data!.decisions! : []), [data]);
  const nonExecuted = useMemo(
    () => all.filter((d) => NON_EXECUTED.has(String(d.status ?? '').toUpperCase())),
    [all]
  );

  const rows = useMemo(() => {
    const q = filter.trim().toUpperCase();
    if (!q) return nonExecuted;
    return nonExecuted.filter((d) => String(d.status ?? '').toUpperCase().includes(q));
  }, [nonExecuted, filter]);

  const tally = useMemo(() => {
    const c: Record<string, number> = {};
    for (const d of nonExecuted) {
      const k = String(d.status || 'UNKNOWN').toUpperCase();
      c[k] = (c[k] ?? 0) + 1;
    }
    return c;
  }, [nonExecuted]);

  const reasons = useMemo(() => {
    // Group the real risk_reason strings — that IS the "why".
    const c: Record<string, number> = {};
    for (const d of nonExecuted) {
      const r = String(d.risk_reason || '').trim();
      if (r) c[r] = (c[r] ?? 0) + 1;
    }
    return Object.entries(c).sort((a, b) => b[1] - a[1]);
  }, [nonExecuted]);

  return (
    <AppShell activeKey="why-no-trade" eyebrow="Xynn / Ops" title="Why No Trade">
      <div className={styles.wrap}>
        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Total cycles</span>
            <span className={styles.cardValue}>{data?.count ?? '—'}</span>
            <span className={styles.cardHint}>decision ledger</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Not executed</span>
            <span className={styles.cardValue}>{nonExecuted.length}</span>
            <span className={styles.cardHint}>no trade / wait / blocked</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Blocked</span>
            <span className={styles.cardValue}>{tally['BLOCKED'] ?? 0}</span>
            <span className={styles.cardHint}>risk gate / guards</span>
          </div>
        </div>

        {all.length > 0 && nonExecuted.length === 0 && (
          <div className={styles.notice}>
            Every recorded cycle executed — nothing is being suppressed right now.
          </div>
        )}

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Why (real risk reasons)</span>
            <button type="button" className={styles.btn} onClick={refresh}>
              Refresh
            </button>
          </div>
          <div className={styles.panelBody}>
            {reasons.length === 0 ? (
              <p className={styles.empty}>
                No non-executed cycles carry a recorded reason yet.
              </p>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Reason</th>
                    <th>Count</th>
                    <th>Share</th>
                  </tr>
                </thead>
                <tbody>
                  {reasons.map(([reason, n]) => (
                    <tr key={reason}>
                      <td>{reason}</td>
                      <td className={styles.mono}>{n}</td>
                      <td className={styles.mono}>
                        {nonExecuted.length > 0
                          ? `${((n / nonExecuted.length) * 100).toFixed(0)}%`
                          : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Non-executed cycles</span>
            <div className={styles.row}>
              <input
                className={styles.input}
                placeholder="Filter status…"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                aria-label="Filter non-executed decisions"
              />
            </div>
          </div>
          <div className={styles.panelBody}>
            {loading && rows.length === 0 ? (
              <p className={styles.empty}>Loading…</p>
            ) : rows.length === 0 ? (
              <p className={styles.empty}>
                {all.length === 0
                  ? 'No decisions recorded yet — run a cycle to populate the ledger.'
                  : 'No cycles match the filter.'}
              </p>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Decision ID</th>
                    <th>Event</th>
                    <th>Symbol</th>
                    <th>Status</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((d, i) => (
                    <tr key={String(d.decision_id ?? i)}>
                      <td className={styles.mono}>{d.decision_id ?? '—'}</td>
                      <td>{d.event_type ?? '—'}</td>
                      <td>{d.symbol ?? '—'}</td>
                      <td>
                        <span className={statusPill(String(d.status ?? ''))}>
                          {d.status ?? '—'}
                        </span>
                      </td>
                      <td>{d.risk_reason || d.summary || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
