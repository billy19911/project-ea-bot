'use client';

import AppShell from '@/components/AppShell';
import Pagination, { usePagination } from '@/components/ui/pagination';
import { useApiData } from '@/lib/useApiData';
import styles from '@/components/ops.module.css';

/**
 * Learning — real lesson-store analytics (`/learning/analytics`).
 *
 * The store is the single sink both review paths write to. An empty store
 * reports `available:false` honestly (never a fabricated breakdown); hour /
 * regime breakdowns stay empty until a performance tracker is wired, and we
 * show that truth rather than inventing buckets.
 */

type Lesson = {
  id?: string;
  category?: string;
  outcome?: string;
  symbol?: string;
  text?: string;
};

type LearningBody = {
  available?: boolean;
  source?: string;
  total?: number;
  by_outcome?: Record<string, number>;
  lessons?: Lesson[];
  supervisor_kpis?: unknown;
};

function outcomePill(outcome: string): string {
  const o = outcome.toLowerCase();
  if (o === 'win' || o === 'profit') return `${styles.pill} ${styles.pillOk}`;
  if (o === 'loss') return `${styles.pill} ${styles.pillDanger}`;
  return `${styles.pill} ${styles.pillNeutral}`;
}

export default function LearningPage() {
  const { data, error, loading, refresh } = useApiData<LearningBody>('/learning/analytics');
  // The store is append-only (oldest first), so reverse to show the NEWEST
  // lessons first — consistent with the /agents page.
  const lessons = Array.isArray(data?.lessons) ? [...data!.lessons!].reverse() : [];
  const byOutcome = data?.by_outcome ?? {};
  const total = data?.total ?? 0;

  const { page, pageSize, setPage, setPageSize, slice } = usePagination(lessons.length, 25);
  const pageItems = slice(lessons);

  return (
    <AppShell activeKey="learning" eyebrow="Xynn / Learning" title="Learning">
      <div className={styles.wrap}>
        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Lessons stored</span>
            <span className={styles.cardValue}>{data == null ? '—' : total}</span>
            <span className={styles.cardHint}>persistent JSONL store</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Wins</span>
            <span className={styles.cardValue}>{byOutcome['win'] ?? 0}</span>
            <span className={styles.cardHint}>review outcome</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Losses</span>
            <span className={styles.cardValue}>{byOutcome['loss'] ?? 0}</span>
            <span className={styles.cardHint}>review outcome</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Source</span>
            <span className={`${styles.cardValue} ${styles.cardValueSm}`}>
              {data?.available ? 'available' : 'empty'}
            </span>
            <span className={styles.cardHint}>{data?.source ?? '—'}</span>
          </div>
        </div>

        {data && !data.available && (
          <div className={styles.notice}>
            The lesson store is empty. Lessons accumulate once trades close and the review
            auto-trigger fires (close → review → lesson). Hour/regime breakdowns stay empty until a
            performance tracker is wired — they are not fabricated.
          </div>
        )}

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Lessons</span>
            <button type="button" className={styles.btn} onClick={refresh}>
              Refresh
            </button>
          </div>
          <div className={styles.panelBody}>
            {loading && lessons.length === 0 ? (
              <p className={styles.empty}>Loading…</p>
            ) : lessons.length === 0 ? (
              <p className={styles.empty}>No lessons recorded yet.</p>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Category</th>
                    <th>Outcome</th>
                    <th>Symbol</th>
                    <th>Lesson</th>
                  </tr>
                </thead>
                <tbody>
                  {pageItems.map((l, i) => (
                    <tr key={`${String(l.id ?? 'lesson')}-${i}`}>
                      <td className={styles.mono}>{l.id ?? '—'}</td>
                      <td>{l.category || '—'}</td>
                      <td>
                        <span className={outcomePill(String(l.outcome ?? ''))}>
                          {l.outcome || '—'}
                        </span>
                      </td>
                      <td>{l.symbol || '—'}</td>
                      <td>{l.text || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          {lessons.length > 0 && (
            <Pagination
              page={page}
              pageSize={pageSize}
              total={lessons.length}
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
            />
          )}
        </div>
      </div>
    </AppShell>
  );
}
