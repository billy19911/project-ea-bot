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

// R-multiple performance by period (`/v2/r-performance`).
type RBucket = {
  key: string;
  count: number;
  win_rate: number;
  avg_r: number;
  total_r: number;
  profit_factor: number;
};

type RBody = {
  value?: RBucket[] | null;
  period?: string;
  trade_count?: number;
  reviews_total?: number;
  r_unavailable?: number;
  overall?: {
    count: number;
    win_rate: number;
    avg_r: number;
    total_r: number;
    profit_factor: number;
  };
  source?: string;
  status?: string;
};

const DIMENSIONS = ['hour', 'session', 'regime'];
const R_PERIODS = ['day', 'week', 'month'] as const;
type RPeriod = (typeof R_PERIODS)[number];

export default function PerformancePage() {
  const [dimension, setDimension] = useState('hour');
  const [period, setPeriod] = useState<RPeriod>('day');
  const { data, error, loading, refresh } = useApiData<PerfBody>(
    `/v2/performance-intelligence?dimension=${dimension}`
  );
  const {
    data: rData,
    error: rError,
    loading: rLoading,
    refresh: rRefresh,
  } = useApiData<RBody>(`/v2/r-performance?period=${period}`);

  const rows = Array.isArray(data?.value) ? data!.value! : [];
  const count = data?.trade_count ?? 0;
  const rRows = Array.isArray(rData?.value) ? rData!.value! : [];
  const overall = rData?.overall;
  const rCount = overall?.count ?? rData?.trade_count ?? 0;

  const fmtR = (v?: number) => (typeof v === 'number' ? `${v > 0 ? '+' : ''}${v.toFixed(2)}R` : '—');
  const fmtPct = (v?: number) => (typeof v === 'number' ? `${v.toFixed(1)}%` : '—');

  return (
    <AppShell activeKey="performance" eyebrow="Xynn / Performa" title="Performa">
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
          <div className={styles.card}>
            <span className={styles.cardLabel}>Avg R (all)</span>
            <span className={styles.cardValue}>{fmtR(overall?.avg_r)}</span>
            <span className={styles.cardHint}>per trade, initial risk</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Total R (all)</span>
            <span className={styles.cardValue}>{fmtR(overall?.total_r)}</span>
            <span className={styles.cardHint}>{rCount} trades with R</span>
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

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>R-multiple by period (avg / total)</span>
            <div className={styles.row}>
              {R_PERIODS.map((p) => (
                <button
                  key={p}
                  type="button"
                  className={`${styles.chip} ${period === p ? styles.chipActive : ''}`}
                  onClick={() => setPeriod(p)}
                >
                  {p}
                </button>
              ))}
              <button type="button" className={styles.btn} onClick={rRefresh}>
                Refresh
              </button>
            </div>
          </div>
          <div className={styles.panelBody}>
            {rError && <div className={styles.error}>{rError}</div>}
            {rLoading && rRows.length === 0 ? (
              <p className={styles.empty}>Loading…</p>
            ) : rRows.length === 0 ? (
              <p className={styles.empty}>
                Belum ada trade dengan R. R dihitung saat posisi ditutup (butuh stop-loss awal
                tersimpan).
                {(rData?.r_unavailable ?? 0) > 0 &&
                  ` ${rData!.r_unavailable} trade ditutup tapi R belum bisa dihitung (dibuka sebelum fitur R aktif).`}
              </p>
            ) : (
              <>
                {(rData?.r_unavailable ?? 0) > 0 && (
                  <p className={styles.empty}>
                    Catatan: {rData!.r_unavailable} dari {rData?.reviews_total ?? '?'} trade yang
                    ditutup belum punya R (dibuka sebelum tracking R aktif) dan tidak dihitung.
                  </p>
                )}
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Periode</th>
                      <th>Trades</th>
                      <th>Win rate</th>
                      <th>Avg R</th>
                      <th>Total R</th>
                      <th>Profit factor</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rRows.map((r) => (
                      <tr key={r.key}>
                        <td className={styles.mono}>{r.key}</td>
                        <td className={styles.mono}>{r.count}</td>
                        <td className={styles.mono}>{fmtPct(r.win_rate)}</td>
                        <td className={styles.mono}>{fmtR(r.avg_r)}</td>
                        <td className={styles.mono}>{fmtR(r.total_r)}</td>
                        <td className={styles.mono}>
                          {Number.isFinite(r.profit_factor) ? r.profit_factor.toFixed(2) : '∞'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
