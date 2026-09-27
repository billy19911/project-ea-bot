'use client';

import { useState } from 'react';
import AppShell from '@/components/AppShell';
import { useApiData } from '@/lib/useApiData';
import styles from '@/components/ops.module.css';

/**
 * Performance — outcome intelligence by dimension (`/v2/performance-intelligence`).
 *
 * Rows come from the auto-review history. When no closed trades exist yet we
 * render an honest empty state and a zero count instead of fabricating data.
 */

type Bucket = {
  name?: string;
  size?: number;
  win_rate?: number;
  avg_pnl?: number;
};

type PerfBody = {
  value?: Bucket[] | null;
  dimension?: string;
  trade_count?: number;
  source?: string;
};

const DIMENSIONS = ['hour', 'session', 'regime'];

export default function PerformancePage() {
  const [dimension, setDimension] = useState('hour');
  const { data, error, loading, refresh } = useApiData<PerfBody>(
    `/v2/performance-intelligence?dimension=${dimension}`
  );

  const rows = Array.isArray(data?.value) ? data!.value! : [];
  const count = data?.trade_count ?? 0;

  return (
    <AppShell activeKey="performance" eyebrow="Xynn / Performance" title="Performance">
      <div className={styles.wrap}>
        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Trades analysed</span>
            <span className={styles.cardValue}>{count}</span>
            <span className={styles.cardHint}>closed outcomes</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Buckets</span>
            <span className={styles.cardValue}>{rows.length}</span>
            <span className={styles.cardHint}>{dimension} dimension</span>
          </div>
        </div>

        {count === 0 && rows.length === 0 && (
          <div className={styles.notice}>
            No closed trades recorded yet. Outcome analysis appears here once trades close and the
            review auto-trigger fires.
          </div>
        )}

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Win rate / avg PnL by dimension</span>
            <div className={styles.row}>
              {DIMENSIONS.map((d) => (
                <button
                  key={d}
                  type="button"
                  className={`${styles.chip} ${dimension === d ? styles.chipActive : ''}`}
                  onClick={() => setDimension(d)}
                >
                  {d}
                </button>
              ))}
              <button type="button" className={styles.btn} onClick={refresh}>
                Refresh
              </button>
            </div>
          </div>
          <div className={styles.panelBody}>
            {loading && rows.length === 0 ? (
              <p className={styles.empty}>Loading…</p>
            ) : rows.length === 0 ? (
              <p className={styles.empty}>No buckets available for this dimension.</p>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Size</th>
                    <th>Win rate</th>
                    <th>Avg PnL</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={String(r.name ?? i)}>
                      <td>{r.name ?? '—'}</td>
                      <td className={styles.mono}>{r.size ?? '—'}</td>
                      <td className={styles.mono}>
                        {typeof r.win_rate === 'number'
                          ? `${(r.win_rate * 100).toFixed(1)}%`
                          : '—'}
                      </td>
                      <td className={styles.mono}>
                        {typeof r.avg_pnl === 'number' ? r.avg_pnl.toFixed(2) : '—'}
                      </td>
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
