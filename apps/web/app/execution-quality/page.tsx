'use client';

import { useCallback, useState } from 'react';
import { useAutoRefresh } from '@/lib/useAutoRefresh';
import AppShell from '@/components/AppShell';
import { apiFetch } from '@/lib/api';
import styles from '@/components/ops.module.css';

type Summary = {
  metrics: Record<string, number>;
  alerts: string[];
};

export default function ExecutionQualityPage() {
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch('/v2/execution-quality');
      if (!res.ok) {
        setError(res.status === 503 ? 'Python service unavailable.' : `Request failed (${res.status})`);
        return;
      }
      const body = await res.json();
      setData(body.value ?? null);
      setError(null);
    } catch {
      setError('Could not reach the API.');
    }
  }, []);

  useAutoRefresh(load);

  const metrics = data?.metrics ?? {};
  const num = (k: string) => (typeof metrics[k] === 'number' ? Number(metrics[k]) : null);

  const cards: Array<{ label: string; value: string; hint: string }> = [
    { label: 'Average Slippage', value: num('average_slippage')?.toFixed(6) ?? '—', hint: 'price units' },
    { label: 'p95 Slippage', value: num('p95_slippage')?.toFixed(6) ?? '—', hint: 'tail risk' },
    { label: 'Fill Delay', value: num('fill_delay')?.toFixed(1) ?? '—', hint: 'ms average' },
    { label: 'Rejection Rate', value: num('rejection_rate') != null ? `${(num('rejection_rate')! * 100).toFixed(2)}%` : '—', hint: '' },
    { label: 'Partial Fill Rate', value: num('partial_fill_rate') != null ? `${(num('partial_fill_rate')! * 100).toFixed(2)}%` : '—', hint: '' },
  ];

  return (
    <AppShell activeKey="execution-quality" eyebrow="Xynn / Execution" title="Execution Quality">
      <div className={styles.wrap}>
        {error && <div className={styles.error}>{error}</div>}

        {data?.alerts && data.alerts.length > 0 && (
          <div className={styles.error}>
            {data.alerts.map((a, i) => (
              <div key={i}>{a}</div>
            ))}
          </div>
        )}

        <div className={styles.grid}>
          {cards.map(c => (
            <div key={c.label} className={styles.card}>
              <span className={styles.cardLabel}>{c.label}</span>
              <span className={`${styles.cardValue} ${styles.mono}`}>{c.value}</span>
              {c.hint && <span className={styles.cardHint}>{c.hint}</span>}
            </div>
          ))}
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Execution by Session / Volatility</span>
            <button type="button" className={styles.btn} onClick={load}>
              Refresh
            </button>
          </div>
          <div className={styles.panelBody}>
            <p className={styles.cardHint}>
              Insights here inform the <strong>execution policy</strong> only — they never change a
              strategy signal without separate validation.
            </p>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
