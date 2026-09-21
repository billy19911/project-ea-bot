'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from './page.module.css';
import { apiFetch } from '../../lib/api';
import AppShell from '../../components/AppShell';
import Pagination from '../../components/ui/pagination';

// View model: camelCase performance fields for rendering. Mapped from the
// Node API's StrategyRecord (snake_case) in `mapStrategy`.
type Strategy = {
  id: string;
  name: string;
  version: string;
  active: boolean;
  performance: {
    winRate: number;
    profitFactor: number;
    sharpe: number;
    maxDD: number;
  };
  parameters: Record<string, string | number>;
  versions: { version: string; date: string; changes: string }[];
};

// Shape returned by GET /strategies (see apps/api/src/index.ts).
type ApiStrategy = {
  id: string;
  name: string;
  version: string;
  active: boolean;
  performance: { win_rate: number; profit_factor: number; sharpe: number; max_dd: number };
  parameters: Record<string, string | number>;
  versions: { version: string; date: string; changes: string }[];
};

function mapStrategy(record: ApiStrategy): Strategy {
  return {
    id: record.id,
    name: record.name,
    version: record.version,
    active: record.active,
    performance: {
      winRate: record.performance?.win_rate ?? 0,
      profitFactor: record.performance?.profit_factor ?? 0,
      sharpe: record.performance?.sharpe ?? 0,
      maxDD: record.performance?.max_dd ?? 0,
    },
    parameters: record.parameters ?? {},
    versions: Array.isArray(record.versions) ? record.versions : [],
  };
}

export default function StrategyCenterPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const selected = selectedId ? strategies.find((s) => s.id === selectedId) : null;

  const loadStrategies = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch('/strategies');
      if (!res.ok) {
        throw new Error(`Gagal memuat strategi (HTTP ${res.status})`);
      }
      const data = await res.json();
      const records: ApiStrategy[] = Array.isArray(data.strategies) ? data.strategies : [];
      setStrategies(records.map(mapStrategy));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Gagal memuat strategi dari API.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStrategies();
  }, [loadStrategies]);

  const toggleActive = async (id: string) => {
    const strat = strategies.find((s) => s.id === id);
    if (!strat) return;
    try {
      const res = await apiFetch(`/strategies/${id}/active`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active: !strat.active }),
      });
      if (!res.ok) {
        throw new Error(`Gagal mengubah status (HTTP ${res.status})`);
      }
      const data = await res.json();
      const updated = mapStrategy(data.strategy as ApiStrategy);
      // Update from the server response, not optimistically.
      setStrategies((items) => items.map((item) => (item.id === id ? updated : item)));
      setNotice(data.message || `Strategi ${updated.name} diperbarui`);
      setTimeout(() => setNotice(''), 2500);
    } catch (err) {
      // Do NOT flip UI state on failure.
      setError(err instanceof Error ? err.message : 'Gagal mengubah status strategi.');
      setTimeout(() => setError(''), 4000);
    }
  };

  const pageCount = Math.max(1, Math.ceil(strategies.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const visibleStrategies = strategies.slice((safePage - 1) * pageSize, safePage * pageSize);

  return (
    <AppShell
      activeKey="strategy"
      eyebrow="EA BOT / PUSAT STRATEGI"
      title="Pusat Strategi"

    >

        {notice && <div className={styles.notice}>{notice}</div>}
        {error && (
          <div className={styles.errorCard}>
            <span>{error}</span>
            <button className={styles.retryBtn} onClick={loadStrategies}>Coba lagi</button>
          </div>
        )}

        <div className={styles.pageBody}>
          {/* Strategies List */}
          <section className={styles.card}>
            <h2>Daftar strategi</h2>
            {loading ? (
              <div className={styles.empty}>Memuat…</div>
            ) : error && strategies.length === 0 ? (
              <div className={styles.empty}>Data strategi tidak tersedia — cek token lalu muat ulang.</div>
            ) : strategies.length === 0 ? (
              <div className={styles.empty}>Belum ada strategi terdaftar.</div>
            ) : (
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Strategi</th>
                    <th>Versi</th>
                    <th>Win rate</th>
                    <th>Profit factor</th>
                    <th>Sharpe</th>
                    <th>Max DD</th>
                    <th>Status</th>
                    <th>Aksi</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleStrategies.map((strat) => (
                    <tr key={strat.id} onClick={() => setSelectedId(strat.id)} className={styles.clickableRow}>
                      <td>
                        <strong>{strat.name}</strong>
                        <small>{strat.id}</small>
                      </td>
                      <td><code>{strat.version}</code></td>
                      <td>{strat.performance.winRate > 0 ? `${strat.performance.winRate}%` : '—'}</td>
                      <td>{strat.performance.profitFactor > 0 ? strat.performance.profitFactor.toFixed(2) : '—'}</td>
                      <td>{strat.performance.sharpe > 0 ? strat.performance.sharpe.toFixed(2) : '—'}</td>
                      <td>{strat.performance.maxDD > 0 ? `${strat.performance.maxDD}%` : '—'}</td>
                      <td>
                        <span className={`${styles.badge} ${strat.active ? styles.success : styles.muted}`}>
                          {strat.active ? 'Aktif' : 'Nonaktif'}
                        </span>
                      </td>
                      <td>
                        <button
                          className={strat.active ? styles.btnDeactivate : styles.btnActivate}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleActive(strat.id);
                          }}
                        >
                          {strat.active ? 'Nonaktifkan' : 'Aktifkan'}
                        </button>
                      </td>
                    </tr>
                  ))}
                 </tbody>
               </table>
               <Pagination
                 page={safePage}
                 pageSize={pageSize}
                 total={strategies.length}
                 onPageChange={setPage}
                 onPageSizeChange={setPageSize}
                 unitLabel="strategies"
               />
             </div>
            )}
           </section>

          {/* Detail Panel */}
          {selected && (
            <>
              <section className={styles.card}>
                <h2>Detail: {selected.name}</h2>
                <div className={styles.detailGrid}>
                  <div>
                    <small>ID</small>
                    <strong>{selected.id}</strong>
                  </div>
                  <div>
                    <small>Version</small>
                    <strong>{selected.version}</strong>
                  </div>
                  <div>
                    <small>Status</small>
                    <strong className={selected.active ? styles.statusActive : styles.statusInactive}>
                      {selected.active ? 'Aktif' : 'Nonaktif'}
                    </strong>
                  </div>
                </div>
              </section>

              <section className={styles.card}>
                <h3>Parameter</h3>
                <div className={styles.paramGrid}>
                  {Object.entries(selected.parameters).map(([key, value]) => (
                    <div key={key} className={styles.paramItem}>
                      <code>{key}</code>
                      <span>{value}</span>
                    </div>
                  ))}
                </div>
              </section>

              <section className={styles.card}>
                <h3>Performa</h3>
                <div className={styles.perfGrid}>
                  <div>
                    <small>Win rate</small>
                    <strong>{selected.performance.winRate > 0 ? `${selected.performance.winRate}%` : '—'}</strong>
                  </div>
                  <div>
                    <small>Profit factor</small>
                    <strong>{selected.performance.profitFactor > 0 ? selected.performance.profitFactor.toFixed(2) : '—'}</strong>
                  </div>
                  <div>
                    <small>Sharpe ratio</small>
                    <strong>{selected.performance.sharpe > 0 ? selected.performance.sharpe.toFixed(2) : '—'}</strong>
                  </div>
                  <div>
                    <small>Max drawdown</small>
                    <strong className={styles.negative}>{selected.performance.maxDD > 0 ? `${selected.performance.maxDD}%` : '—'}</strong>
                  </div>
                </div>
              </section>

              <section className={styles.card}>
                <h3>Riwayat versi</h3>
                <div className={styles.versionList}>
                  {selected.versions.map((ver) => (
                    <div key={ver.version} className={styles.versionItem}>
                      <div className={styles.versionHeader}>
                        <code>{ver.version}</code>
                        <small>{ver.date}</small>
                      </div>
                      <p>{ver.changes}</p>
                    </div>
                  ))}
                </div>
              </section>
            </>
          )}
        </div>
    </AppShell>
  );
}
