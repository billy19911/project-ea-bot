'use client';

import { useMemo, useState } from 'react';
import AppShell from '@/components/AppShell';
import Pagination, { usePagination } from '@/components/ui/pagination';
import { EmptyState } from '@/components/ui/empty-state';
import { LoadingState } from '@/components/ui/loading-state';
import { useApiData, fmtDate, formatDetails } from '@/lib/useApiData';
import styles from '@/components/ops.module.css';

/**
 * Audit — the tamper-evident in-process audit trail (`/audit/events`).
 *
 * Each entry carries a hash chained to the previous one, so the list is
 * verifiable rather than decorative. An empty log is honest: no demo events
 * are ever fabricated.
 */

type AuditEvent = {
  index?: number;
  timestamp?: string;
  actor?: string;
  action?: string;
  target?: string;
  details?: unknown;
  hash?: string;
};

type AuditBody = { events?: AuditEvent[]; count?: number; source?: string };

export default function AuditPage() {
  const { data, error, loading, refresh } = useApiData<AuditBody>('/audit/events');
  const [filter, setFilter] = useState('');

  const all = useMemo(() => (Array.isArray(data?.events) ? data!.events! : []), [data]);

  const rows = useMemo(() => {
    // Show the NEWEST events first (the chain order is preserved on each row's
    // # index). The API returns them oldest-first.
    const ordered = [...all].reverse();
    const q = filter.trim().toLowerCase();
    if (!q) return ordered;
    return ordered.filter(
      (e) =>
        String(e.actor ?? '').toLowerCase().includes(q) ||
        String(e.action ?? '').toLowerCase().includes(q) ||
        String(e.target ?? '').toLowerCase().includes(q)
    );
  }, [all, filter]);

  const { page, pageSize, setPage, setPageSize, slice } = usePagination(rows.length, 10);
  const pageRows = slice(rows);

  return (
    <AppShell activeKey="audit" eyebrow="Xynn / Audit" title="Jejak Audit">
      <div className={styles.wrap}>
        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Audit events</span>
            <span className={styles.cardValue}>{data?.count ?? '—'}</span>
            <span className={styles.cardHint}>hash-chained log</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Source</span>
            <span className={`${styles.cardValue} ${styles.cardValueSm}`}>
              {data?.source ?? '—'}
            </span>
            <span className={styles.cardHint}>in-process</span>
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Audit events</span>
            <div className={styles.row}>
              <input
                className={styles.input}
                placeholder="Filter actor / action / target…"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                aria-label="Filter audit events"
              />
              <button type="button" className={styles.btn} onClick={refresh}>
                Refresh
              </button>
            </div>
          </div>
          <div className={styles.panelBody}>
            {loading && rows.length === 0 ? (
              <LoadingState rows={6} />
            ) : rows.length === 0 ? (
              <EmptyState
                title={filter ? 'Tidak ada event cocok' : 'Belum ada event audit'}
                description={
                  filter
                    ? 'Coba ubah kata kunci filter.'
                    : 'Event audit muncul di sini saat sistem mencatat aksi.'
                }
              />
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Time</th>
                    <th>Actor</th>
                    <th>Action</th>
                    <th>Target</th>
                    <th>Details</th>
                    <th>Hash</th>
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((e, i) => (
                    <tr key={String(e.index ?? i)}>
                      <td className={styles.mono}>{e.index ?? '—'}</td>
                      <td className={styles.mono}>{fmtDate(e.timestamp)}</td>
                      <td>{e.actor ?? '—'}</td>
                      <td>{e.action ?? '—'}</td>
                      <td>{e.target ?? '—'}</td>
                      <td className={styles.mono}>
                        {formatDetails(e.details)}
                      </td>
                      <td className={styles.mono} title={e.hash || ''}>
                        {e.hash ? `${String(e.hash).slice(0, 12)}…` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          {rows.length > 0 && (
            <Pagination
              page={page}
              pageSize={pageSize}
              total={rows.length}
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
            />
          )}
        </div>
      </div>
    </AppShell>
  );
}
