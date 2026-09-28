'use client';

import AppShell from '@/components/AppShell';
import { useApiData, fmtDate } from '@/lib/useApiData';
import { MISMATCH_KIND_LABELS, labelFor } from '@/lib/labels';
import styles from '@/components/ops.module.css';

/**
 * Reconciliation — the last real internal↔broker reconciliation report (PRD §14).
 *
 * `last_report` is the serialised `ReconciliationReport` from the most recent
 * run, or null when none has happened. When `has_critical` is true the guard
 * fail-closes NEW orders — surfaced here explicitly so the operator understands
 * why the bot is not trading.
 */

type Mismatch = {
  kind?: string;
  symbol?: string;
  ticket?: number | null;
  detail?: string;
};

type ReconReport = {
  checked_at?: string;
  internal_count?: number;
  broker_count?: number;
  mismatches?: Mismatch[];
  has_critical?: boolean;
};

type ReconBody = { last_report?: ReconReport | null; history_count?: number; source?: string };

export default function ReconciliationPage() {
  const { data, error, loading, refresh } = useApiData<ReconBody>('/reconciliation/status');
  const report = data?.last_report ?? null;
  const critical = Boolean(report?.has_critical);
  const mismatches = Array.isArray(report?.mismatches) ? report!.mismatches! : [];

  return (
    <AppShell
      activeKey="reconciliation"
      eyebrow="Xynn / Rekonsiliasi"
      title="Rekonsiliasi"
    >
      <div className={styles.wrap}>
        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Status</span>
            <span className={styles.cardValue}>
              {report == null ? '—' : critical ? 'CRITICAL' : 'CLEAN'}
            </span>
            <span className={styles.cardHint}>
              {report == null ? 'no run yet' : critical ? 'new orders fail-closed' : 'internal == broker'}
            </span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Internal positions</span>
            <span className={styles.cardValue}>{report?.internal_count ?? '—'}</span>
            <span className={styles.cardHint}>internal ledger</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Broker positions</span>
            <span className={styles.cardValue}>{report?.broker_count ?? '—'}</span>
            <span className={styles.cardHint}>MT5 read-only</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Mismatches</span>
            <span className={styles.cardValue}>{report == null ? '—' : mismatches.length}</span>
            <span className={styles.cardHint}>runs: {data?.history_count ?? '—'}</span>
          </div>
        </div>

        {critical && (
          <div className={styles.notice}>
            Critical mismatch detected — the <strong>ReconciliationGuard</strong> is failing closed:
            no new orders will be dispatched until the internal ledger and the broker agree.
          </div>
        )}

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Last reconciliation report</span>
            <button type="button" className={styles.btn} onClick={refresh}>
              Refresh
            </button>
          </div>
          <div className={styles.panelBody}>
            {loading && report == null ? (
              <p className={styles.empty}>Loading…</p>
            ) : report == null ? (
              <p className={styles.empty}>
                No reconciliation has run yet. The guard reports clean-vs-clean until MT5 live mode
                supplies both sides.
              </p>
            ) : (
              <>
                <div className={styles.kv} style={{ marginBottom: 'var(--sp-4)' }}>
                  <span className={styles.kvKey}>Checked at</span>
                  <span className={styles.kvVal}>{fmtDate(report.checked_at)}</span>
                  <span className={styles.kvKey}>Critical</span>
                  <span className={styles.kvVal}>{critical ? 'yes' : 'no'}</span>
                </div>
                {mismatches.length === 0 ? (
                  <p className={styles.empty}>No mismatches reported.</p>
                ) : (
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Kind</th>
                        <th>Symbol</th>
                        <th>Ticket</th>
                        <th>Detail</th>
                      </tr>
                    </thead>
                    <tbody>
                      {mismatches.map((m, i) => (
                        <tr key={`${m.kind ?? 'm'}-${i}`}>
                          <td title={m.kind ?? ''}>{labelFor(MISMATCH_KIND_LABELS, String(m.kind ?? ''))}</td>
                          <td>{m.symbol ?? '—'}</td>
                          <td className={styles.mono}>{m.ticket ?? '—'}</td>
                          <td>{m.detail ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
