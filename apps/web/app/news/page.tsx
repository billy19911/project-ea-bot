'use client';

import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import AppShell from '../../components/AppShell';
import { apiFetch } from '../../lib/api';
import Pagination from '../../components/ui/pagination';
import styles from './page.module.css';

type KeyPoints = {
  summary: string;
  impact: string;
  direction: string;
  drivers: string[];
  affected_instruments: string[];
  notes: string[];
};

type EconEvent = {
  title: string;
  country: string;
  date: string;
  datetime_utc?: string;
  impact: string;
  forecast?: string;
  previous?: string;
  actual?: string;
  key_points?: KeyPoints;
};

type Tab = { key: string; label: string; count: number };
type SortDir = 'asc' | 'desc';

const IMPACT_RANK: Record<string, number> = { CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1 };

function dayKey(iso?: string, fallback?: string): string {
  const src = iso || fallback;
  if (!src) return 'unknown';
  const d = new Date(src);
  if (Number.isNaN(d.getTime())) return 'unknown';
  return d.toISOString().slice(0, 10); // YYYY-MM-DD
}

function dayLabel(key: string): string {
  if (key === 'unknown') return 'Unknown';
  const d = new Date(key + 'T00:00:00Z');
  return d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
}

function fmtTime(iso?: string, fallback?: string): string {
  const src = iso || fallback;
  if (!src) return '—';
  const d = new Date(src);
  if (Number.isNaN(d.getTime())) return src;
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

function impactClass(impact: string): string {
  switch ((impact || '').toUpperCase()) {
    case 'HIGH':
    case 'CRITICAL':
      return styles.pillDanger;
    case 'MEDIUM':
      return styles.pillWarn;
    default:
      return styles.pillNeutral;
  }
}

export default function NewsPage() {
  const [events, setEvents] = useState<EconEvent[]>([]);
  const [activeDay, setActiveDay] = useState<string>('');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const load = useCallback(async () => {
    setError(null);
    try {
      // Pull the whole week of USD events once; the day tabs slice locally.
      const res = await apiFetch('/market/upcoming?currency=USD&limit=100');
      if (!res.ok) {
        setError(res.status === 503 ? 'Python service unavailable.' : `Request failed (${res.status})`);
        return;
      }
      const data = await res.json();
      const list: EconEvent[] = Array.isArray(data.events) ? data.events : [];
      setEvents(list);
    } catch {
      setError('Could not reach the API.');
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Group by day → tabs.
  const tabs: Tab[] = useMemo(() => {
    const counts = new Map<string, number>();
    for (const e of events) {
      const k = dayKey(e.datetime_utc, e.date);
      counts.set(k, (counts.get(k) ?? 0) + 1);
    }
    return Array.from(counts.entries())
      .sort(([a], [b]) => (a < b ? -1 : 1))
      .map(([key, count]) => ({ key, label: dayLabel(key), count }));
  }, [events]);

  // Default to the first day once data loads.
  useEffect(() => {
    if (!activeDay && tabs.length > 0) setActiveDay(tabs[0].key);
  }, [tabs, activeDay]);

  // Reset pagination when the day/sort changes.
  useEffect(() => {
    setPage(1);
    setExpanded(null);
  }, [activeDay, sortDir]);

  const rows = useMemo(() => {
    let list = events.filter((e) => dayKey(e.datetime_utc, e.date) === activeDay);
    list = list.slice().sort((a, b) => {
      const ra = IMPACT_RANK[(a.impact || '').toUpperCase()] ?? 0;
      const rb = IMPACT_RANK[(b.impact || '').toUpperCase()] ?? 0;
      if (ra !== rb) return sortDir === 'desc' ? rb - ra : ra - rb;
      const ta = a.datetime_utc || a.date || '';
      const tb = b.datetime_utc || b.date || '';
      return ta < tb ? -1 : 1;
    });
    return list;
  }, [events, activeDay, sortDir]);

  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const visible = rows.slice((safePage - 1) * pageSize, safePage * pageSize);

  return (
    <AppShell activeKey="news" eyebrow="EA BOT / NEWS" title="Kalender Ekonomi USD">
      <div className={styles.wrap}>
        {error && <div className={styles.error}>{error}</div>}

        {/* Day tabs */}
        <div className={styles.tabs} role="tablist" aria-label="Days">
          {tabs.length === 0 && <span className={styles.empty}>{loaded ? 'Tidak ada event USD.' : 'Memuat…'}</span>}
          {tabs.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={activeDay === t.key}
              className={`${styles.tab} ${activeDay === t.key ? styles.tabActive : ''}`}
              onClick={() => setActiveDay(t.key)}
            >
              {t.label}
              <span className={styles.tabCount}>{t.count}</span>
            </button>
          ))}
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Events · {activeDay ? dayLabel(activeDay) : '—'}</span>
            <button
              type="button"
              className={styles.sortBtn}
              onClick={() => setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))}
              title="Sort by impact"
            >
              Impact {sortDir === 'desc' ? '↓' : '↑'}
            </button>
          </div>

          <table className={styles.table}>
            <thead>
              <tr>
                <th>Time</th>
                <th>Currency</th>
                <th>Impact</th>
                <th>Event</th>
                <th>Forecast</th>
                <th>Previous</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((e, i) => {
                const key = `${e.title}-${e.datetime_utc || e.date}-${i}`;
                const isOpen = expanded === key;
                const kp = e.key_points;
                return (
                  <Fragment key={key}>
                    <tr
                      className={`${styles.row} ${isOpen ? styles.rowOpen : ''}`}
                      onClick={() => setExpanded(isOpen ? null : key)}
                    >
                      <td className={styles.mono}>{fmtTime(e.datetime_utc, e.date)}</td>
                      <td>
                        <span className={styles.countryTag}>{e.country || 'USD'}</span>
                      </td>
                      <td>
                        <span className={`${styles.pill} ${impactClass(e.impact)}`}>
                          {(e.impact || 'LOW').toUpperCase()}
                        </span>
                      </td>
                      <td className={styles.eventTitle}>
                        <span className={styles.chevron}>{isOpen ? '▾' : '▸'}</span>
                        {e.title}
                      </td>
                      <td className={styles.mono}>{e.forecast || '—'}</td>
                      <td className={styles.mono}>{e.previous || '—'}</td>
                    </tr>
                    {isOpen && (
                      <tr className={styles.detailRow}>
                        <td colSpan={6}>
                          {kp ? (
                            <div className={styles.keyPoints}>
                              <div className={styles.kpSummary}>{kp.summary}</div>
                              <div className={styles.kpGrid}>
                                <div className={styles.kpBlock}>
                                  <span className={styles.kpLabel}>Direction</span>
                                  <span
                                    className={`${styles.pill} ${
                                      kp.direction === 'BULLISH'
                                        ? styles.pillOk
                                        : kp.direction === 'BEARISH'
                                          ? styles.pillDanger
                                          : styles.pillNeutral
                                    }`}
                                  >
                                    {kp.direction}
                                  </span>
                                </div>
                                <div className={styles.kpBlock}>
                                  <span className={styles.kpLabel}>Affected</span>
                                  <span className={styles.kpValue}>
                                    {kp.affected_instruments.length
                                      ? kp.affected_instruments.join(', ')
                                      : '—'}
                                  </span>
                                </div>
                              </div>
                              {kp.drivers.length > 0 && (
                                <ul className={styles.kpList}>
                                  {kp.drivers.map((d, di) => (
                                    <li key={di}>{d}</li>
                                  ))}
                                </ul>
                              )}
                              {kp.notes.length > 0 && (
                                <ul className={styles.kpList}>
                                  {kp.notes.map((n, ni) => (
                                    <li key={ni}>{n}</li>
                                  ))}
                                </ul>
                              )}
                            </div>
                          ) : (
                            <div className={styles.kpSummary}>Tidak ada detail poin penting.</div>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
              {visible.length === 0 && (
                <tr>
                  <td colSpan={6} className={styles.empty}>
                    {loaded ? 'Tidak ada event pada hari ini.' : 'Memuat…'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>

          {rows.length > 0 && (
            <Pagination
              page={safePage}
              pageSize={pageSize}
              total={rows.length}
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
              unitLabel="events"
            />
          )}
        </div>
      </div>
    </AppShell>
  );
}
