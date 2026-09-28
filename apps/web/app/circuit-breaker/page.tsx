'use client';

import { useCallback, useState } from 'react';
import { useAutoRefresh } from '@/lib/useAutoRefresh';
import AppShell from '@/components/AppShell';
import { apiFetch } from '@/lib/api';
import { fmtDateTime } from '@/lib/useApiData';
import Pagination from '@/components/ui/pagination';
import { BREAKER_LEVEL_LABELS, BREAKER_TRIGGER_LABELS, labelFor } from '@/lib/labels';
import styles from '@/components/ops.module.css';

type BreakerState = {
  level: string;
  latched: boolean;
  trigger: string | null;
  reason: string;
  since: string;
  allows_new_entries: boolean;
  must_flatten: boolean;
  size_multiplier: number;
  history_count: number;
  recent: Array<{ from: string; to: string; trigger: string; reason: string; timestamp: string }>;
};

const LEVELS: Record<string, { label: string; cls: string }> = {
  normal: { label: 'NORMAL', cls: 'pillOk' },
  caution: { label: 'WASPADA', cls: 'pillWarn' },
  risk_reduced: { label: 'RISIKO DIKURANGI', cls: 'pillWarn' },
  entry_blocked: { label: 'ENTRY DIBLOKIR', cls: 'pillDanger' },
  emergency_flatten: { label: 'TUTUP DARURAT', cls: 'pillDanger' },
  halted: { label: 'DIHENTIKAN', cls: 'pillDanger' },
};

const TRIGGERS: Array<{ key: string; label: string }> = [
  { key: 'spread_spike', label: 'Lonjakan spread' },
  { key: 'feed_stale', label: 'Feed data basi' },
  { key: 'mt5_disconnected', label: 'MT5 terputus' },
  { key: 'daily_loss', label: 'Rugi harian' },
  { key: 'drawdown', label: 'Drawdown' },
  { key: 'reconciliation_mismatch', label: 'Rekonsiliasi tidak cocok' },
  { key: 'execution_rejection_spike', label: 'Lonjakan penolakan eksekusi' },
  { key: 'database_unavailable', label: 'Database tidak tersedia' },
];

export default function CircuitBreakerPage() {
  const [state, setState] = useState<BreakerState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch('/v2/circuit-breaker');
      if (!res.ok) {
        setError(res.status === 503 ? 'Python service unavailable.' : `Request failed (${res.status})`);
        return;
      }
      const data = await res.json();
      setState(data.value ?? null);
      setError(null);
    } catch {
      setError('Could not reach the API.');
    }
  }, []);

  useAutoRefresh(load);

  const transitions = state?.recent ?? [];
  const pageCount = Math.max(1, Math.ceil(transitions.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const visibleTransitions = transitions.slice((safePage - 1) * pageSize, safePage * pageSize);

  const trigger = async (key: string) => {
    setBusy(true);
    try {
      await apiFetch('/v2/circuit-breaker/trigger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trigger: key, source: 'dashboard' }),
      });
      await load();
    } finally {
      setBusy(false);
    }
  };

  const recover = async () => {
    setBusy(true);
    try {
      await apiFetch('/v2/circuit-breaker/recover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ condition_ok: true, target: 'NORMAL', reason: 'operator recovery' }),
      });
      await load();
    } finally {
      setBusy(false);
    }
  };

  const levelInfo = state ? LEVELS[state.level] ?? { label: state.level.toUpperCase(), cls: 'pillNeutral' } : null;

  return (
    <AppShell activeKey="circuit-breaker" eyebrow="Xynn / Risiko" title="Circuit Breaker">
      <div className={styles.wrap}>
        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Level saat ini</span>
            <span className={styles.cardValue}>
              {levelInfo ? (
                <span className={`${styles.pill} ${styles[levelInfo.cls as keyof typeof styles]}`}>
                  {levelInfo.label}
                </span>
              ) : (
                '—'
              )}
            </span>
            {state?.latched && <span className={styles.cardHint}>Terkunci — butuh pemulihan</span>}
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Entry baru</span>
            <span className={styles.cardValue}>
              {state ? (
                <span className={`${styles.pill} ${state.allows_new_entries ? styles.pillOk : styles.pillDanger}`}>
                  {state.allows_new_entries ? 'DIIZINKAN' : 'DIBLOKIR'}
                </span>
              ) : (
                '—'
              )}
            </span>
            <span className={styles.cardHint}>Pengali ukuran: {state ? state.size_multiplier : '—'}</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Pemicu</span>
            <span className={`${styles.cardValue} ${styles.cardValueMd}`} title={state?.trigger ?? ''}>
              {state?.trigger ? labelFor(BREAKER_TRIGGER_LABELS, state.trigger) : '-'}
            </span>
            <span className={styles.cardHint}>{state?.reason || 'Tidak ada pemicu aktif'}</span>
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Simulasi Pemicu (deterministik)</span>
          </div>
          <div className={styles.panelBody}>
            <div className={styles.row}>
              {TRIGGERS.map(t => (
                <button
                  key={t.key}
                  type="button"
                  className={`${styles.btn} ${styles.btnDanger}`}
                  onClick={() => trigger(t.key)}
                  disabled={busy}
                >
                  {t.label}
                </button>
              ))}
              <button
                type="button"
                className={`${styles.btn} ${styles.btnPrimary}`}
                onClick={recover}
                disabled={busy}
              >
                Pulihkan ke NORMAL
              </button>
            </div>
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Transisi Terbaru</span>
          </div>
          {state && state.recent.length > 0 ? (
            <>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Dari</th>
                  <th>Ke</th>
                  <th>Pemicu</th>
                  <th>Alasan</th>
                  <th>Waktu</th>
                </tr>
              </thead>
              <tbody>
                {visibleTransitions.map((r, i) => (
                  <tr key={i}>
                    <td title={r.from}>{labelFor(BREAKER_LEVEL_LABELS, String(r.from ?? ''))}</td>
                    <td title={r.to}>{labelFor(BREAKER_LEVEL_LABELS, String(r.to ?? ''))}</td>
                    <td title={r.trigger}>{labelFor(BREAKER_TRIGGER_LABELS, String(r.trigger ?? ''))}</td>
                    <td>{r.reason}</td>
                    <td className={styles.mono}>{fmtDateTime(r.timestamp)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination
              page={safePage}
              pageSize={pageSize}
              total={transitions.length}
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
              unitLabel="transisi"
            />
            </>
          ) : (
            <div className={styles.empty}>Belum ada transisi tercatat.</div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
