'use client';

import { useEffect, useState } from 'react';
import styles from './page.module.css';

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

const mockStrategies: Strategy[] = [
  {
    id: 'STR-001',
    name: 'EMA Crossover Gold',
    version: 'v1.4',
    active: true,
    performance: { winRate: 57.1, profitFactor: 1.86, sharpe: 1.42, maxDD: 8.2 },
    parameters: { ema_fast: 12, ema_slow: 26, atr_period: 14, risk_percent: 1.5 },
    versions: [
      { version: 'v1.4', date: '2026-09-10', changes: 'Tambah filter ATR minimum' },
      { version: 'v1.3', date: '2026-08-28', changes: 'Optimasi exit timing' },
      { version: 'v1.2', date: '2026-08-15', changes: 'Initial release' },
    ],
  },
  {
    id: 'STR-002',
    name: 'Momentum London Open',
    version: 'v2.1',
    active: true,
    performance: { winRate: 53.8, profitFactor: 1.54, sharpe: 1.16, maxDD: 11.4 },
    parameters: { rsi_period: 14, rsi_threshold: 65, volume_min: 1000, spread_max: 25 },
    versions: [
      { version: 'v2.1', date: '2026-09-08', changes: 'Tambah filter spread' },
      { version: 'v2.0', date: '2026-08-20', changes: 'Refactor logic entry' },
    ],
  },
  {
    id: 'STR-003',
    name: 'Volatility Filter',
    version: 'v0.9',
    active: false,
    performance: { winRate: 0, profitFactor: 0, sharpe: 0, maxDD: 0 },
    parameters: { bb_period: 20, bb_std: 2, atr_multiplier: 1.5 },
    versions: [
      { version: 'v0.9', date: '2026-09-05', changes: 'Beta testing' },
    ],
  },
  {
    id: 'STR-004',
    name: 'Structure Breakout',
    version: 'v3.0',
    active: false,
    performance: { winRate: 0, profitFactor: 0, sharpe: 0, maxDD: 0 },
    parameters: { lookback: 50, threshold: 0.002, confirmation_bars: 2 },
    versions: [
      { version: 'v3.0', date: '2026-09-01', changes: 'Menunggu validasi' },
    ],
  },
];

export default function StrategyCenterPage() {
  const [strategies, setStrategies] = useState<Strategy[]>(mockStrategies);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [notice, setNotice] = useState('');

  const selected = selectedId ? strategies.find((s) => s.id === selectedId) : null;

  const toggleActive = (id: string) => {
    setStrategies((items) =>
      items.map((item) =>
        item.id === id ? { ...item, active: !item.active } : item
      )
    );
    const strat = strategies.find((s) => s.id === id);
    const newState = !strat?.active;
    setNotice(
      `Strategi ${strat?.name} ${newState ? 'diaktifkan' : 'dinonaktifkan'}`
    );
    setTimeout(() => setNotice(''), 2500);
  };

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <span className={styles.brandMark}>EA</span>
          <div>
            <strong>EA BOT</strong>
            <small>STRATEGY CENTER</small>
          </div>
        </div>
        <div className={styles.workspaceLabel}>MANAJEMEN</div>
        <a href="/" className={styles.navItem}>
          <span>←</span> Kembali
        </a>
        <a href="/control-plane" className={styles.navItem}>
          <span>▦</span> Control Plane
        </a>
        <div className={styles.sidebarBottom}>
          <span className={styles.greenDot} /> {strategies.filter((s) => s.active).length} strategi aktif
          <div className={styles.version}>Phase 24 · Live</div>
        </div>
      </aside>

      <main className={styles.main}>
        <header className={styles.topbar}>
          <div>
            <div className={styles.eyebrow}>EA BOT / STRATEGY CENTER</div>
            <h1>Strategy Center</h1>
          </div>
          <div className={styles.topActions}>
            <span className={styles.envBadge}>LIVE</span>
          </div>
        </header>

        {notice && <div className={styles.notice}>{notice}</div>}

        <div className={styles.pageBody}>
          {/* Strategies List */}
          <section className={styles.card}>
            <h2>Daftar strategi</h2>
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Strategi</th>
                    <th>Version</th>
                    <th>Win rate</th>
                    <th>Profit factor</th>
                    <th>Sharpe</th>
                    <th>Max DD</th>
                    <th>Status</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {strategies.map((strat) => (
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
            </div>
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
      </main>
    </div>
  );
}
