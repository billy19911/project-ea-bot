'use client';

import AppShell from '@/components/AppShell';
import { useApiData } from '@/lib/useApiData';
import styles from '@/components/ops.module.css';

/**
 * System Health — environment preconditions + service health roll-up.
 *
 * Composed from real read-only sources:
 *   - `/v2/environment`  live preconditions (arm, risk gate, reconciliation, strategy)
 *   - `/system/health`   per-component status (Node returns `status` strings)
 */

type Preconditions = {
  terminal_armed?: boolean;
  risk_gate_healthy?: boolean;
  reconciliation_healthy?: boolean;
  production_strategy?: boolean;
};

type EnvValue = {
  environment?: string;
  is_live?: boolean;
  live_allowed?: boolean;
  reason?: string;
  preconditions?: Preconditions;
};

type EnvBody = { value?: EnvValue | null; source?: string };

// `/system/health` returns `status` as a string ("healthy"/"down"/...), NOT an
// `ok` boolean — reading `.ok` left every component shown as failing.
type HealthComponent = { name?: string; status?: string; detail?: string };
type HealthBody = {
  overall?: string;
  components?: HealthComponent[];
  checked_at?: string;
  source?: string;
};

function statusOk(status: string | undefined): boolean | undefined {
  if (status == null || status === '') return undefined;
  const s = status.toLowerCase();
  if (['healthy', 'ok', 'up', 'running', 'pass', 'connected'].includes(s)) return true;
  if (['degraded', 'warn', 'warning'].includes(s)) return undefined;
  return false;
}

function OkPill({ ok, label }: { ok: boolean | undefined; label: string }) {
  const cls =
    ok === true
      ? `${styles.pill} ${styles.pillOk}`
      : ok === false
        ? `${styles.pill} ${styles.pillDanger}`
        : `${styles.pill} ${styles.pillNeutral}`;
  return <span className={cls}>{label}</span>;
}

export default function SystemHealthPage() {
  const env = useApiData<EnvBody>('/v2/environment');
  const health = useApiData<HealthBody>('/system/health', {
    pick: (body) => (body as HealthBody) ?? null,
  });

  const pre = env.data?.value?.preconditions;
  const components = Array.isArray(health.data?.components) ? health.data!.components! : [];

  const checks: Array<{ key: string; label: string; ok?: boolean }> = [
    { key: 'arm', label: 'Terminal armed', ok: pre?.terminal_armed },
    { key: 'risk', label: 'Risk gate healthy', ok: pre?.risk_gate_healthy },
    { key: 'recon', label: 'Reconciliation healthy', ok: pre?.reconciliation_healthy },
    { key: 'strat', label: 'Production strategy', ok: pre?.production_strategy },
  ];

  return (
    <AppShell activeKey="system-health" eyebrow="Xynn / Sistem" title="Kesehatan Sistem">
      <div className={styles.wrap}>
        {env.error && <div className={styles.error}>{env.error}</div>}
        {health.error && <div className={styles.error}>{health.error}</div>}

        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Environment</span>
            <span className={styles.cardValue}>{env.data?.value?.environment ?? '—'}</span>
            <span className={styles.cardHint}>{env.data?.value?.is_live ? 'live' : 'not live'}</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Live allowed</span>
            <span className={styles.cardValue}>
              {env.data?.value == null ? '—' : env.data.value.live_allowed ? 'YES' : 'NO'}
            </span>
            <span className={styles.cardHint}>all preconditions</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Overall</span>
            <span className={styles.cardValue}>{health.data?.overall ?? '—'}</span>
            <span className={styles.cardHint}>service roll-up</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Components OK</span>
            <span className={styles.cardValue}>
              {components.length === 0
                ? '—'
                : `${components.filter((c) => statusOk(c.status) === true).length}/${components.length}`}
            </span>
            <span className={styles.cardHint}>certification</span>
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Live preconditions</span>
            <button
              type="button"
              className={styles.btn}
              onClick={() => {
                void env.refresh();
                void health.refresh();
              }}
            >
              Refresh
            </button>
          </div>
          <div className={styles.panelBody}>
            <div className={styles.row}>
              {checks.map((c) => (
                <OkPill
                  key={c.key}
                  ok={c.ok}
                  label={`${c.label}: ${c.ok === true ? 'met' : c.ok === false ? 'missing' : 'unknown'}`}
                />
              ))}
            </div>
            {env.data?.value?.reason && (
              <p className={styles.cardHint} style={{ marginTop: 'var(--sp-3)' }}>
                {env.data.value.reason}
              </p>
            )}
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Component certification</span>
          </div>
          <div className={styles.panelBody}>
            {components.length === 0 ? (
              <p className={styles.empty}>No component health reported.</p>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Component</th>
                    <th>Status</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {components.map((c, i) => (
                    <tr key={String(c.name ?? i)}>
                      <td>{c.name ?? '—'}</td>
                      <td>
                        <OkPill ok={statusOk(c.status)} label={c.status ?? '—'} />
                      </td>
                      <td>{c.detail ?? '—'}</td>
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
