'use client';

import AppShell from '@/components/AppShell';
import { useApiData, fmtPct } from '@/lib/useApiData';
import styles from '@/components/ops.module.css';

/**
 * Risk Center — the deterministic safety picture in one place.
 *
 * Composes three real read-only sources:
 *   - `/v2/circuit-breaker`  multi-level breaker state (Phase 36)
 *   - `/v2/capital`          capital-allocation snapshot (Phase 52)
 *   - `/settings`            live risk limits (read-only here — never editable)
 *
 * Nothing on this page can change a risk limit; it only reflects state.
 */

type BreakerValue = {
  level?: string;
  is_triggered?: boolean;
  reason?: string;
  updated_at?: string;
  history?: Array<Record<string, unknown>>;
};

type BreakerBody = { value?: BreakerValue | null; source?: string };

type CapitalValue = {
  total_capital?: number;
  allocated?: number;
  available?: number;
  utilization?: number;
};

type CapitalBody = { value?: CapitalValue | null; source?: string };

type SettingsBody = {
  settings?: Record<string, unknown>;
  risk_limits?: Record<string, number>;
  read_only?: Record<string, unknown>;
};

function levelPill(level: string): string {
  const l = level.toUpperCase();
  if (l.includes('HALT') || l.includes('CRITICAL') || l.includes('LOCK'))
    return `${styles.pill} ${styles.pillDanger}`;
  if (l.includes('WARN') || l.includes('THROTTLE') || l.includes('CAUTION'))
    return `${styles.pill} ${styles.pillWarn}`;
  return `${styles.pill} ${styles.pillOk}`;
}

export default function RiskCenterPage() {
  const breaker = useApiData<BreakerBody>('/v2/circuit-breaker');
  const capital = useApiData<CapitalBody>('/v2/capital');
  const settings = useApiData<SettingsBody>('/settings', {
    pick: (body) => (body as SettingsBody) ?? null,
  });

  const b = breaker.data?.value ?? null;
  const cap = capital.data?.value ?? null;
  const riskLimits = settings.data?.risk_limits ?? {};

  const util =
    typeof cap?.utilization === 'number'
      ? cap.utilization
      : typeof cap?.total_capital === 'number' && cap.total_capital > 0 && typeof cap.allocated === 'number'
        ? cap.allocated / cap.total_capital
        : null;

  return (
    <AppShell activeKey="risk-center" eyebrow="Xynn / Risk" title="Risk Center">
      <div className={styles.wrap}>
        {breaker.error && <div className={styles.error}>{breaker.error}</div>}
        {capital.error && <div className={styles.error}>{capital.error}</div>}
        {settings.error && <div className={styles.error}>{settings.error}</div>}

        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Circuit breaker</span>
            <span className={styles.cardValue} style={{ fontSize: 'var(--fs-xl)' }}>
              {b?.level ?? '—'}
            </span>
            <span className={styles.cardHint}>
              {b == null ? 'unavailable' : b.is_triggered ? 'TRIGGERED' : 'nominal'}
            </span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Total capital</span>
            <span className={styles.cardValue}>
              {typeof cap?.total_capital === 'number' ? cap.total_capital.toFixed(2) : '—'}
            </span>
            <span className={styles.cardHint}>account currency</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Allocated</span>
            <span className={styles.cardValue}>
              {typeof cap?.allocated === 'number' ? cap.allocated.toFixed(2) : '—'}
            </span>
            <span className={styles.cardHint}>in open risk</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Utilization</span>
            <span className={styles.cardValue}>{fmtPct(util, 1)}</span>
            <span className={styles.bar} style={{ marginTop: 6 }}>
              <span
                className={`${styles.barFill} ${
                  util != null && util > 0.6 ? styles.barFillDanger : styles.barFillOk
                }`}
                style={{ width: `${util != null ? Math.min(100, util * 100) : 0}%` }}
              />
            </span>
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Breaker state</span>
            <span className={levelPill(String(b?.level ?? ''))}>{b?.level ?? 'unknown'}</span>
          </div>
          <div className={styles.panelBody}>
            <div className={styles.kv}>
              <span className={styles.kvKey}>Triggered</span>
              <span className={styles.kvVal}>{b == null ? '—' : b.is_triggered ? 'yes' : 'no'}</span>
              <span className={styles.kvKey}>Reason</span>
              <span className={styles.kvVal}>{b?.reason || '—'}</span>
              <span className={styles.kvKey}>Source</span>
              <span className={styles.kvVal}>{breaker.data?.source ?? '—'}</span>
            </div>
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Risk limits (read-only)</span>
            <button
              type="button"
              className={styles.btn}
              onClick={() => {
                void breaker.refresh();
                void capital.refresh();
                void settings.refresh();
              }}
            >
              Refresh
            </button>
          </div>
          <div className={styles.panelBody}>
            {Object.keys(riskLimits).length === 0 ? (
              <p className={styles.empty}>
                No risk limits reported. These come from the live RiskGate — they are enforced by
                deterministic code and can never be edited from the dashboard.
              </p>
            ) : (
              <div className={styles.kv}>
                {Object.entries(riskLimits).map(([k, v]) => (
                  <span key={k} style={{ display: 'contents' }}>
                    <span className={styles.kvKey}>{k.replace(/_/g, ' ')}</span>
                    <span className={`${styles.kvVal} ${styles.mono}`}>{String(v)}</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
