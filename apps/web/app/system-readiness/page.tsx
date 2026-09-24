'use client';

import { useCallback, useMemo, useState } from 'react';
import AppShell from '../../components/AppShell';
import { apiFetch } from '../../lib/api';
import { useAutoRefresh } from '../../lib/useAutoRefresh';
import Pagination from '../../components/ui/pagination';
import styles from './page.module.css';

type Component = {
  component?: string;
  status?: string;
  version?: string;
  verified_at?: string;
  details?: string[] | string;
};

// Status → pill class. Colour follows the same semantic vocabulary used
// elsewhere (PASS = ok, NOT_* / *_MISSING = danger, else neutral/warn).
function statusClass(status: string): string {
  const v = String(status || '').toUpperCase();
  if (['PASS', 'OK', 'HEALTHY', 'UP', 'RUNNING', 'CONNECTED'].includes(v)) return styles.pillOk;
  if (['WARN', 'WARNING', 'DEGRADED', 'PENDING'].includes(v)) return styles.pillWarn;
  if (['FAIL', 'DOWN', 'ERROR', 'CRITICAL'].includes(v)) return styles.pillDanger;
  if (v.startsWith('NOT_')) return styles.pillDanger;
  return styles.pillNeutral;
}

export default function SystemReadinessPage() {
  const [components, setComponents] = useState<Array<Component>>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const load = useCallback(async () => {
    const res = await apiFetch('/certify');
    if (res.ok) {
      const data = await res.json();
      setComponents(data.components || []);
    }
  }, []);

  useAutoRefresh(load);

  const pageCount = Math.max(1, Math.ceil(components.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const visible = useMemo(
    () => components.slice((safePage - 1) * pageSize, safePage * pageSize),
    [components, safePage, pageSize],
  );

  return (
    <AppShell activeKey="system-readiness" eyebrow="EA BOT / SYSTEM" title="System Readiness">
      <section className={styles.tableWrapper}>
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
                <td>{c.version || '-'} </td>
                <td>{c.verified_at ? c.verified_at.slice(0, 19).replace('T', ' ') : '—'}</td>
                <td>{Array.isArray(c.details) ? c.details.join(', ') : c.details || '—'}</td>
              </tr>
            ))}
            {visible.length === 0 && (
              <tr>
                <td colSpan={5} className={styles.empty}>
                  Tidak ada komponen.
                </td>
              </tr>
            )}
          </tbody>
        </table>
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
      </section>
    </AppShell>
  );
}
