'use client';

import { useCallback, useEffect, useState } from 'react';
import AppShell from '@/components/AppShell';
import { apiFetch } from '@/lib/api';
import styles from '@/components/ops.module.css';

type Gate = {
  gate: string;
  passed: boolean;
  failed: string[];
  checks: Record<string, boolean>;
};
type Report = { status: string; gates: Gate[]; reasons: string[] };

const GATE_LABELS: Record<string, string> = {
  A: 'Gate A — Engineering',
  B: 'Gate B — Trading Safety',
  C: 'Gate C — Research',
  D: 'Gate D — Operational',
  E: 'Gate E — Forward Validation',
};

function statusClass(status: string): string {
  if (status === 'PRODUCTION') return styles.pillOk;
  if (status === 'HALTED') return styles.pillDanger;
  if (status === 'READY_FOR_SMALL_LIVE' || status === 'READY_FOR_DEMO') return styles.pillWarn;
  if (status === 'READY_FOR_PAPER') return styles.pillWarn;
  return styles.pillNeutral;
}

export default function CertificationPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch('/v2/certification/gate');
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
    <AppShell activeKey="certification" eyebrow="Xynn / System" title="Production Certification">
      <div className={styles.wrap}>
        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Production Status</span>
            <span className={styles.cardValue}>
              {report ? (
                <span className={`${styles.pill} ${statusClass(report.status)}`}>{report.status}</span>
              ) : (
                '—'
              )}
            </span>
            <span className={styles.cardHint}>Deterministic checklist — no LLM opinion</span>
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Certification Gates</span>
            <button type="button" className={styles.btn} onClick={load}>
              Refresh
            </button>
          </div>
          {report ? (
            <div className={styles.panelBody}>
              {report.gates.map(g => {
                const failed = g.failed ?? [];
                return (
                  <div key={g.gate} className={styles.gateBlock}>
                    <div className={styles.gateHead}>
                      <strong className={styles.gateTitle}>{GATE_LABELS[g.gate] ?? g.gate}</strong>
                      <span className={`${styles.pill} ${g.passed ? styles.pillOk : styles.pillDanger}`}>
                        {g.passed ? 'PASS' : 'FAIL'}
                      </span>
                    </div>
                    <div className={styles.checkGrid}>
                      {Object.entries(g.checks).map(([name, ok]) => (
                        <div
                          key={name}
                          className={`${styles.check} ${ok ? styles.checkOk : styles.checkMiss}`}
                          title={ok ? 'Passed' : 'Not passing'}
                        >
                          <span className={styles.checkIcon} aria-hidden>{ok ? '✓' : '✕'}</span>
                          <span className={styles.checkLabel}>{name.replace(/_/g, ' ')}</span>
                        </div>
                      ))}
                    </div>
                    {failed.length > 0 && (
                      <div className={styles.gateFailed}>
                        Failing: {failed.map(f => f.replace(/_/g, ' ')).join(', ')}
                      </div>
                    )}
                  </div>
                );
              })}
              {report.reasons.length > 0 && (
                <div className={styles.cardHint} style={{ marginTop: 8 }}>
                  {report.reasons.join(' · ')}
                </div>
              )}
            </div>
          ) : (
            <div className={styles.empty}>Loading certification gate…</div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
