'use client';

import { useCallback, useEffect, useState } from 'react';
import AppShell from '@/components/AppShell';
import { apiFetch } from '@/lib/api';
import styles from '@/components/ops.module.css';

type Evaluation = {
  sli: string;
  status: string;
  breach: boolean;
  observed?: number;
  target?: number;
  stats?: { count: number; p50: number; p95: number; p99: number; average: number };
};

type Report = {
  slos: Array<{ sli: string; target: number; percentile: number; kind: string }>;
  evaluations: Evaluation[];
  breaching: string[];
};

function statusPill(status: string): string {
  if (status === 'OK') return styles.pillOk;
  if (status === 'BREACH') return styles.pillDanger;
  return styles.pillNeutral;
}

export default function SloPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch('/v2/slo');
      if (!res.ok) {
        setError(res.status === 503 ? 'Python service unavailable.' : `Request failed (${res.status})`);
        return;
      }
      const body = await res.json();
      setReport(body.value ?? null);
      setError(null);
    } catch {
      setError('Could not reach the API.');
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <AppShell activeKey="slo" eyebrow="Xynn / Observability" title="System SLO">
      <div className={styles.wrap}>
        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Objectives</span>
            <span className={styles.cardValue}>{report?.slos.length ?? '—'}</span>
            <span className={styles.cardHint}>p50 / p95 / p99 tracked</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Breaching</span>
            <span className={styles.cardValue}>
              {report ? report.breaching.length : '—'}
            </span>
            <span className={styles.cardHint}>
              {report && report.breaching.length === 0 ? 'All within target' : 'Needs attention'}
            </span>
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>SLI Evaluation</span>
            <button type="button" className={styles.btn} onClick={load}>
              Refresh
            </button>
          </div>
          {report && report.evaluations.length > 0 ? (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>SLI</th>
                  <th>Status</th>
                  <th>Target</th>
                  <th>Observed</th>
                  <th>p50</th>
                  <th>p95</th>
                  <th>p99</th>
                  <th>Samples</th>
                </tr>
              </thead>
              <tbody>
                {report.evaluations.map(e => (
                  <tr key={e.sli}>
                    <td className={styles.mono}>{e.sli}</td>
                    <td>
                      <span className={`${styles.pill} ${statusPill(e.status)}`}>{e.status}</span>
                    </td>
                    <td className={styles.mono}>{e.target ?? '—'}</td>
                    <td className={styles.mono}>
                      {typeof e.observed === 'number' ? e.observed.toFixed(4) : '—'}
                    </td>
                    <td className={styles.mono}>{e.stats ? e.stats.p50.toFixed(3) : '—'}</td>
                    <td className={styles.mono}>{e.stats ? e.stats.p95.toFixed(3) : '—'}</td>
                    <td className={styles.mono}>{e.stats ? e.stats.p99.toFixed(3) : '—'}</td>
                    <td className={styles.mono}>{e.stats ? e.stats.count : 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className={styles.empty}>No SLO data available.</div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
