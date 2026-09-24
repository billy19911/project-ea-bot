'use client';

import { useCallback, useState } from 'react';
import { useAutoRefresh } from '@/lib/useAutoRefresh';
import AppShell from '@/components/AppShell';
import { apiFetch } from '@/lib/api';
import styles from '@/components/ops.module.css';

type EnvState = {
  environment: string;
  is_live: boolean;
  live_allowed: boolean;
  reason: string;
  preconditions: Record<string, boolean>;
};

const PRECONDITION_LABELS: Record<string, string> = {
  terminal_armed: 'Terminal armed',
  risk_gate_healthy: 'Risk gate healthy',
  reconciliation_healthy: 'Reconciliation healthy',
  production_strategy: 'Production strategy',
};

export default function EnvironmentPage() {
  const [state, setState] = useState<EnvState | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch('/v2/environment');
      if (!res.ok) {
        setError(res.status === 503 ? 'Python service unavailable.' : `Request failed (${res.status})`);
        return;
      }
      const body = await res.json();
      setState(body.value ?? null);
      setError(null);
    } catch {
      setError('Could not reach the API.');
    }
  }, []);

  useAutoRefresh(load);

  return (
    <AppShell activeKey="environment" eyebrow="Xynn / Safety" title="Environment">
      <div className={styles.wrap}>
        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Current Environment</span>
            <span className={`${styles.cardValue}`}>{state?.environment ?? '—'}</span>
            <span className={styles.cardHint}>Set via EA_ENVIRONMENT</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Live Execution</span>
            <span className={styles.cardValue}>
              {state ? (
                <span className={`${styles.pill} ${state.live_allowed ? styles.pillOk : styles.pillDanger}`}>
                  {state.live_allowed ? 'ALLOWED' : 'REJECTED'}
                </span>
              ) : (
                '—'
              )}
            </span>
            <span className={styles.cardHint}>{state?.reason || ''}</span>
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Live Preconditions</span>
            <button type="button" className={styles.btn} onClick={load}>
              Refresh
            </button>
          </div>
          <div className={styles.panelBody}>
            <div className={styles.grid}>
              {state &&
                Object.entries(state.preconditions).map(([key, ok]) => (
                  <div key={key} className={styles.card}>
                    <span className={styles.cardLabel}>{PRECONDITION_LABELS[key] ?? key}</span>
                    <span className={styles.cardValue}>
                      <span className={`${styles.pill} ${ok ? styles.pillOk : styles.pillDanger}`}>
                        {ok ? 'MET' : 'MISSING'}
                      </span>
                    </span>
                  </div>
                ))}
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
