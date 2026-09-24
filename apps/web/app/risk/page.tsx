'use client';

import { useCallback, useState } from 'react';
import AppShell from '@/components/AppShell';
import { RiskBadge, type RiskLevel } from '@/components/ui/risk-badge';
import { apiFetch } from '@/lib/api';
import { useAutoRefresh } from '@/lib/useAutoRefresh';

type BreakerValue = {
  level?: string;
  latched?: boolean;
  trigger?: string | null;
  reason?: string | null;
  since?: string | null;
} | null;

type ReconciliationReport = {
  matched?: number[];
  orphan_orders?: number[];
  total_mismatches?: number;
  critical?: boolean;
} | null;

function mapBreakerLevel(level: unknown): RiskLevel {
  if (level === 'normal') return 'OK';
  if (level === 'caution' || level === 'risk_reduced') return 'WARN';
  if (level === 'entry_blocked' || level === 'emergency_flatten' || level === 'halted') return 'BLOCK';
  return 'UNKNOWN';
}

function mapReconLevel(report: ReconciliationReport): RiskLevel {
  if (!report) return 'UNKNOWN';
  if (report.critical === true) return 'BLOCK';
  if ((report.total_mismatches ?? 0) > 0) return 'WARN';
  return 'OK';
}

const LEVEL_LABEL: Record<string, string> = {
  normal: 'NORMAL',
  caution: 'CAUTION',
  risk_reduced: 'RISK_REDUCED',
  entry_blocked: 'ENTRY_BLOCKED',
  emergency_flatten: 'EMERGENCY_FLATTEN',
  halted: 'HALTED',
};

export default function RiskPage() {
  const [breaker, setBreaker] = useState<BreakerValue>(null);
  const [breakerError, setBreakerError] = useState<string | null>(null);
  const [breakerLoaded, setBreakerLoaded] = useState(false);
  const [recon, setRecon] = useState<ReconciliationReport>(null);
  const [reconHistoryCount, setReconHistoryCount] = useState<number | null>(null);
  const [reconError, setReconError] = useState<string | null>(null);
  const [reconLoaded, setReconLoaded] = useState(false);

  const load = useCallback(async () => {
    const [cbRes, rcRes] = await Promise.allSettled([
      apiFetch('/v2/circuit-breaker'),
      apiFetch('/reconciliation/status'),
    ]);

    if (cbRes.status === 'fulfilled' && cbRes.value.ok) {
      try {
        const data = await cbRes.value.json();
        const v = data?.value ?? data;
        setBreaker(typeof v === 'object' && v !== null ? v : null);
        setBreakerError(null);
      } catch {
        setBreakerError('Invalid circuit-breaker payload.');
      }
    } else if (cbRes.status === 'fulfilled') {
      setBreakerError(
        cbRes.value.status === 503
          ? 'Python service unavailable.'
          : `Circuit breaker request failed (${cbRes.value.status})`
      );
    } else {
      setBreakerError('Could not reach the API.');
    }
    setBreakerLoaded(true);

    if (rcRes.status === 'fulfilled' && rcRes.value.ok) {
      try {
        const data = await rcRes.value.json();
        setRecon(data?.last_report ?? null);
        setReconHistoryCount(typeof data?.history_count === 'number' ? data.history_count : null);
        setReconError(null);
      } catch {
        setReconError('Invalid reconciliation payload.');
      }
    } else if (rcRes.status === 'fulfilled') {
      setReconError(
        rcRes.value.status === 503
          ? 'Python service unavailable.'
          : `Reconciliation request failed (${rcRes.value.status})`
      );
    } else {
      setReconError('Could not reach the API.');
    }
    setReconLoaded(true);
  }, []);

  useAutoRefresh(load);

  const breakerLevel: RiskLevel = breakerError && !breaker ? 'UNKNOWN' : mapBreakerLevel(breaker?.level);
  const reconLevel: RiskLevel = reconError && !recon ? 'UNKNOWN' : mapReconLevel(recon);

  return (
    <AppShell
      activeKey="overview"
      eyebrow="Xynn / Risk"
      title="Risk Center"
      actions={<RiskBadge level={breakerLevel} />}
    >
      <div className="grid gap-4">
        <section className="p-4 bg-[var(--surface-muted)] rounded-md">
          <h2 className="text-lg font-semibold mb-2">Circuit Breaker</h2>
          {breakerError && <p style={{ color: 'var(--danger)', marginBottom: 8 }}>{breakerError}</p>}
          <div className="flex items-center gap-2 mb-2">
            <RiskBadge level={breakerLevel} />
            <span className="text-sm font-medium">
              {breaker?.level ? LEVEL_LABEL[breaker.level] ?? breaker.level : '—'}
            </span>
          </div>
          {breaker?.reason && <p className="text-sm text-[var(--text-secondary)]">Reason: {breaker.reason}</p>}
          {breaker?.trigger && <p className="text-sm text-[var(--text-secondary)]">Trigger: {breaker.trigger}</p>}
          {typeof breaker?.latched === 'boolean' && (
            <p className="text-sm text-[var(--text-secondary)]">Latched: {breaker.latched ? 'yes' : 'no'}</p>
          )}
          {breaker?.since && <p className="text-sm text-[var(--text-secondary)]">Since: {new Date(breaker.since).toLocaleString()}</p>}
          {!breakerLoaded && !breakerError && <p className="text-sm text-[var(--text-muted)]">Loading…</p>}
        </section>

        <section className="p-4 bg-[var(--surface-muted)] rounded-md">
          <h2 className="text-lg font-semibold mb-2">Reconciliation</h2>
          {reconError && <p style={{ color: 'var(--danger)', marginBottom: 8 }}>{reconError}</p>}
          <div className="flex items-center gap-2 mb-2">
            <RiskBadge level={reconLevel} />
            <span className="text-sm font-medium">
              {recon
                ? `${recon.matched?.length ?? 0} matched / ${recon.total_mismatches ?? 0} mismatches`
                : reconLoaded && !reconError
                  ? 'No report yet'
                  : '—'}
            </span>
          </div>
          {recon && (
            <>
              <p className="text-sm text-[var(--text-secondary)]">Critical: {recon.critical ? 'yes' : 'no'}</p>
              <p className="text-sm text-[var(--text-secondary)]">Orphan orders: {recon.orphan_orders?.length ?? 0}</p>
            </>
          )}
          {reconHistoryCount !== null && (
            <p className="text-sm text-[var(--text-secondary)]">History: {reconHistoryCount}</p>
          )}
          {!reconLoaded && !reconError && <p className="text-sm text-[var(--text-muted)]">Loading…</p>}
        </section>
      </div>
    </AppShell>
  );
}
