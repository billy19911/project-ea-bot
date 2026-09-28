'use client';

import { useCallback, useMemo, useState } from 'react';
import AppShell from '../../components/AppShell';
import { apiFetch } from '../../lib/api';
import { fmtDateTime, formatDetails } from '../../lib/useApiData';
import { useAutoRefresh } from '../../lib/useAutoRefresh';
import Pagination from '../../components/ui/pagination';
import styles from '../../components/ops.module.css';

/**
 * System Readiness — real component certification (`/certify`).
 *
 * Shows the newest-first component list from the certification runner. A fetch
 * failure is surfaced honestly (never silently swallowed as "no components").
 */

type Component = {
  component?: string;
  status?: string;
  version?: string;
  verified_at?: string;
  details?: unknown;
};

// Status → pill class (shared ops vocabulary: PASS/OK = ok, NOT_*/FAIL = danger).
function statusClass(status: string): string {
  const v = String(status || '').toUpperCase();
  if (['PASS', 'OK', 'HEALTHY', 'UP', 'RUNNING', 'CONNECTED'].includes(v))
    return styles.pillOk;
  if (['WARN', 'WARNING', 'DEGRADED', 'PENDING'].includes(v)) return styles.pillWarn;
  if (['FAIL', 'DOWN', 'ERROR', 'CRITICAL'].includes(v)) return styles.pillDanger;
  if (v.startsWith('NOT_')) return styles.pillDanger;
  return styles.pillNeutral;
}

export default function SystemReadinessPage() {
  const [components, setComponents] = useState<Array<Component>>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const load = useCallback(async () => {
    const res = await apiFetch('/certify');
    if (res.ok) {
      const data = await res.json();
      setComponents(Array.isArray(data.components) ? data.components : []);
      setError(null);
    } else {
      // Surface the failure instead of pretending there are no components.
      setError(
        res.status === 503
          ? 'Service certification tidak tersedia — engine Python kemungkinan tidak berjalan.'
          : `Gagal memuat sertifikasi (HTTP ${res.status}).`,
      );
    }
    setLoaded(true);
  }, []);

  useAutoRefresh(load);

  const pageCount = Math.max(1, Math.ceil(components.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const visible = useMemo(
    () => components.slice((safePage - 1) * pageSize, safePage * pageSize),
    [components, safePage, pageSize],
  );

  return (
    <AppShell activeKey="system-readiness" eyebrow="Xynn / Sistem" title="Kesiapan Sistem">
      <div className={styles.wrap}>
        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Component certification</span>
            <button type="button" className={styles.btn} onClick={() => void load()}>
              Refresh
            </button>
          </div>
          <div className={styles.panelBody}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Component</th>
                  <th>Status</th>
                  <th>Version</th>
                  <th>Verified</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((c, i) => (
                  <tr key={i}>
                    <td>{c.component}</td>
                    <td>
                      <span className={`${styles.pill} ${statusClass(c.status ?? '')}`}>
                        {c.status ?? '—'}
                      </span>
                    </td>
                    <td>{c.version || '—'}</td>
                    <td>{fmtDateTime(c.verified_at)}</td>
                    <td>{formatDetails(c.details)}</td>
                  </tr>
                ))}
                {visible.length === 0 && (
                  <tr>
                    <td colSpan={5} className={styles.empty}>
                      {loaded ? 'Tidak ada komponen.' : 'Memuat…'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {components.length > 0 && (
            <Pagination
              page={safePage}
              pageSize={pageSize}
              total={components.length}
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
              unitLabel="components"
            />
          )}
        </div>
      </div>
    </AppShell>
  );
}
