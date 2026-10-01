'use client';

import AppShell from '@/components/AppShell';
import { useApiData, fmtPct } from '@/lib/useApiData';
import { RISK_LABELS, labelFor } from '@/lib/labels';
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

// TASK 11: the real, pipeline-fed execution guard (kill switch + per-dependency
// breakers). This is the state that actually blocks orders.
type ExecutionGuard = {
  kill_switch?: { state?: string; is_blocked?: boolean; locked?: boolean };
  breakers?: Record<string, { state?: string; allow_trading?: boolean }>;
};

type BreakerBody = {
  value?: BreakerValue | null;
  execution_guard?: ExecutionGuard | null;
  value_wired?: boolean;
  source?: string;
};

type CapitalValue = {
  total_capital?: number;
  allocated?: number;
  available?: number;
  utilization?: number;
  allocations_configured?: boolean;
  equity_bound?: boolean;
};

type CapitalBody = { value?: CapitalValue | null; source?: string };

// The API returns risk_limits as `{ available, limits: {...} }` — NOT a flat
// map. Binding to the flat shape rendered "[object Object]" (TASK 11).
type RiskLimits = { available?: boolean; limits?: Record<string, number> };

type SettingsBody = {
  settings?: Record<string, unknown>;
  risk_limits?: RiskLimits;
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
  const guard = breaker.data?.execution_guard ?? null;
  const cap = capital.data?.value ?? null;
  // TASK 11: risk_limits is `{ available, limits }`; render the real limits map.
  const riskLimits = settings.data?.risk_limits?.limits ?? {};
  const riskLimitsAvailable = settings.data?.risk_limits?.available ?? false;

  // Real enforcement state: any open dependency breaker or an engaged kill
  // switch blocks new orders. Unknown → not claimed healthy.
  const guardBlocked = guard
    ? guard.kill_switch?.is_blocked === true ||
      Object.values(guard.breakers ?? {}).some((br) => br.state === 'open')
    : null;
  const guardState =
    guard == null ? '—' : guardBlocked ? 'BLOCKED' : 'NOMINAL';

  const util =
    typeof cap?.utilization === 'number'
      ? cap.utilization
      : typeof cap?.total_capital === 'number' && cap.total_capital > 0 && typeof cap.allocated === 'number'
        ? cap.allocated / cap.total_capital
        : null;

  return (
    <AppShell activeKey="risk-center" eyebrow="Xynn / Risiko" title="Pusat Risiko">
      <div className={styles.wrap}>
        {breaker.error && <div className={styles.error}>{breaker.error}</div>}
        {capital.error && <div className={styles.error}>{capital.error}</div>}
        {settings.error && <div className={styles.error}>{settings.error}</div>}

        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Execution enforcement</span>
            <span className={`${styles.cardValue} ${styles.cardValueMd}`}>{guardState}</span>
            <span className={styles.cardHint}>
              {guard == null
                ? 'execution guard unavailable'
                : guardBlocked
                  ? 'new orders fail-closed'
                  : 'kill switch + breakers nominal'}
            </span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Circuit breaker (manual)</span>
            <span className={`${styles.cardValue} ${styles.cardValueMd}`}>
              {b?.level ?? '—'}
            </span>
            <span className={styles.cardHint}>
              {b == null
                ? 'unavailable'
                : `manual breaker · ${b.is_triggered ? 'TRIGGERED' : 'nominal'} · not auto-fed`}
            </span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Total capital</span>
            <span className={styles.cardValue}>
              {typeof cap?.total_capital === 'number' ? cap.total_capital.toFixed(2) : '—'}
            </span>
            <span className={styles.cardHint}>
              {cap?.equity_bound ? 'account currency (live equity)' : 'account currency'}
            </span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Allocated / Utilization</span>
            <span className={styles.cardValue}>
              {typeof cap?.allocated === 'number' ? cap.allocated.toFixed(2) : '—'} · {fmtPct(util, 1)}
            </span>
            <span className={styles.bar} style={{ marginTop: 6 }}>
              <span
                className={`${styles.barFill} ${
                  util != null && util > 0.6 ? styles.barFillDanger : styles.barFillOk
                }`}
                style={{ width: `${util != null ? Math.min(100, util * 100) : 0}%` }}
              />
            </span>
            <span className={styles.cardHint}>
              {cap?.allocations_configured ? 'in open risk' : 'no per-strategy allocation configured'}
            </span>
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Execution guard (real enforcement)</span>
            <span className={levelPill(guardBlocked ? 'BLOCKED' : guard == null ? '' : 'NOMINAL')}>
              {guardState}
            </span>
          </div>
          <div className={styles.panelBody}>
            {guard == null ? (
              <p className={styles.empty}>
                Execution guard state unavailable — the API did not return it. This is the
                state that actually blocks new orders (kill switch + per-dependency breakers).
              </p>
            ) : (
              <div className={styles.kv}>
                <span className={styles.kvKey}>Kill switch</span>
                <span className={styles.kvVal}>
                  {guard.kill_switch?.state ?? '—'}
                  {guard.kill_switch?.is_blocked ? ' · BLOCKED' : ''}
                </span>
                {Object.entries(guard.breakers ?? {}).map(([name, br]) => (
                  <span key={name} style={{ display: 'contents' }}>
                    <span className={styles.kvKey}>{name} breaker</span>
                    <span className={`${styles.kvVal} ${styles.mono}`}>
                      {br.state ?? '—'}
                    </span>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Multi-level breaker (manual)</span>
            <span className={levelPill(String(b?.level ?? ''))}>{b?.level ?? 'unknown'}</span>
          </div>
          <div className={styles.panelBody}>
            <p className={styles.cardHint} style={{ marginBottom: 8 }}>
              Manually controlled breaker — it is not automatically fed by the pipeline.
              The Execution guard above is the state that actually gates orders.
            </p>
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
            {!riskLimitsAvailable || Object.keys(riskLimits).length === 0 ? (
              <p className={styles.empty}>
                {settings.error
                  ? 'Risk limits unavailable — see the error above.'
                  : 'No risk limits reported. These come from the live RiskGate — they are enforced by deterministic code and can never be edited from the dashboard.'}
              </p>
            ) : (
              <div className={styles.kv}>
                {Object.entries(riskLimits).map(([k, v]) => (
                  <span key={k} style={{ display: 'contents' }}>
                    <span className={styles.kvKey} title={k}>
                      {labelFor(RISK_LABELS, k)}
                    </span>
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
