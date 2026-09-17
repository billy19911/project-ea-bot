'use client';

/**
 * DailyReport — laporan trading harian dari deal NYATA MT5 (UI/UX ide #9).
 *
 * Sumber: `GET /reports/daily?days=N` (Node → Python → MT5 history, read-only).
 * Aturan jujur:
 * - `ok: false` menampilkan alasan dari backend, bukan angka nol karangan;
 * - win rate `null` ditampilkan "—" (tidak ada yang diputuskan), bukan 0%;
 * - akun yang dibaca selalu dicantumkan supaya tidak menyesatkan.
 */

import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';
import styles from './DailyReport.module.css';

type DailyBucket = {
  date: string;
  deals: number;
  closed: number;
  wins: number;
  losses: number;
  breakeven: number;
  net: number;
  win_rate: number | null;
  best: number | null;
  worst: number | null;
};

type SymbolBucket = {
  symbol: string;
  closed: number;
  wins: number;
  win_rate: number | null;
  net: number;
};

type ReportPayload = {
  ok: boolean;
  reason?: string;
  days: number;
  generated_at?: string;
  note?: string;
  account?: { login?: number; server?: string; currency?: string; balance?: number; equity?: number };
  totals?: {
    deals: number;
    closed: number;
    wins: number;
    losses: number;
    net: number;
    win_rate: number | null;
    best_day: { date: string; net: number } | null;
    worst_day: { date: string; net: number } | null;
  };
  daily?: DailyBucket[];
  symbols?: SymbolBucket[];
};

const RANGES = [7, 14, 30];

function money(v: number | null | undefined, currency?: string): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  const sign = v > 0 ? '+' : '';
  return `${sign}${v.toLocaleString('id-ID', { maximumFractionDigits: 2 })}${currency ? ' ' + currency : ''}`;
}

function percent(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  return (v * 100).toFixed(1) + '%';
}

function pnlClass(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return styles.neutral;
  return v > 0 ? styles.positive : styles.negative;
}

export default function DailyReport() {
  const [days, setDays] = useState(7);
  const [payload, setPayload] = useState<ReportPayload | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'unauthorized' | 'unreachable'>('loading');

  const load = useCallback(async (n: number) => {
    setState('loading');
    try {
      const res = await apiFetch(`/reports/daily?days=${n}`);
      if (res.status === 401) {
        setState('unauthorized');
        setPayload(null);
        return;
      }
      if (!res.ok) {
        setState('unreachable');
        setPayload(null);
        return;
      }
      setPayload(await res.json());
      setState('ready');
    } catch {
      setState('unreachable');
      setPayload(null);
    }
  }, []);

  useEffect(() => {
    load(days);
  }, [days, load]);

  return (
    <section className={styles.wrap}>
      <div className={styles.head}>
        <div>
          <h2 className={styles.title}>Laporan Harian</h2>
          <p className={styles.subtitle}>
            Deal tertutup NYATA dari terminal MT5 yang sedang terpilih (read-only).{' '}
            {payload?.note ?? ''}
          </p>
        </div>
        <div className={styles.rangeBar} role="group" aria-label="Rentang hari">
          {RANGES.map((n) => (
            <button
              key={n}
              className={`${styles.rangeBtn} ${days === n ? styles.rangeActive : ''}`}
              onClick={() => setDays(n)}
              aria-pressed={days === n}
            >
              {n} hari
            </button>
          ))}
        </div>
      </div>

      {state === 'loading' && <div className={styles.muted}>Memuat laporan…</div>}

      {state === 'unauthorized' && (
        <div className={styles.errorBox}>
          Belum masuk (401). Buka <a href="/login">halaman Masuk</a> lalu muat ulang.
        </div>
      )}

      {state === 'unreachable' && (
        <div className={styles.errorBox}>Layanan Python tidak menjawab. Coba lagi sebentar.</div>
      )}

      {state === 'ready' && payload && !payload.ok && (
        <div className={styles.errorBox}>{payload.reason ?? 'Laporan tidak tersedia.'}</div>
      )}

      {state === 'ready' && payload?.ok && payload.totals && (
        <>
          <div className={styles.accountLine}>
            Akun <strong>{payload.account?.login ?? '—'}</strong> · {payload.account?.server ?? '—'} ·{' '}
            {payload.account?.currency ?? ''} · dibuat {payload.generated_at ?? '—'}
          </div>

          <div className={styles.kpiRow}>
            <div className={styles.kpi}>
              <span className={`${styles.kpiValue} ${pnlClass(payload.totals.net)}`}>
                {money(payload.totals.net, payload.account?.currency)}
              </span>
              <span className={styles.kpiLabel}>Net {payload.days} hari</span>
            </div>
            <div className={styles.kpi}>
              <span className={styles.kpiValue}>{payload.totals.closed}</span>
              <span className={styles.kpiLabel}>Trade tertutup</span>
            </div>
            <div className={styles.kpi}>
              <span className={styles.kpiValue}>{percent(payload.totals.win_rate)}</span>
              <span className={styles.kpiLabel}>Win rate ({payload.totals.wins}W / {payload.totals.losses}L)</span>
            </div>
            <div className={styles.kpi}>
              <span className={`${styles.kpiValue} ${pnlClass(payload.totals.best_day?.net)}`}>
                {money(payload.totals.best_day?.net)}
              </span>
              <span className={styles.kpiLabel}>Hari terbaik {payload.totals.best_day ? `(${payload.totals.best_day.date})` : ''}</span>
            </div>
            <div className={styles.kpi}>
              <span className={`${styles.kpiValue} ${pnlClass(payload.totals.worst_day?.net)}`}>
                {money(payload.totals.worst_day?.net)}
              </span>
              <span className={styles.kpiLabel}>Hari terburuk {payload.totals.worst_day ? `(${payload.totals.worst_day.date})` : ''}</span>
            </div>
          </div>

          <h3 className={styles.sectionTitle}>Per hari</h3>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Tanggal</th>
                  <th>Deal</th>
                  <th>Tertutup</th>
                  <th>W / L</th>
                  <th>Win rate</th>
                  <th>Net</th>
                </tr>
              </thead>
              <tbody>
                {(payload.daily ?? []).map((d) => (
                  <tr key={d.date}>
                    <td>{d.date}</td>
                    <td>{d.deals}</td>
                    <td>{d.closed}</td>
                    <td>
                      {d.wins} / {d.losses}
                      {d.breakeven > 0 && <small> +{d.breakeven} BE</small>}
                    </td>
                    <td>{percent(d.win_rate)}</td>
                    <td className={pnlClass(d.net)}>{money(d.net, payload.account?.currency)}</td>
                  </tr>
                ))}
                {(payload.daily ?? []).length === 0 && (
                  <tr>
                    <td colSpan={6} className={styles.muted}>
                      Tidak ada deal tertutup dalam rentang ini.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <h3 className={styles.sectionTitle}>Per simbol</h3>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Simbol</th>
                  <th>Tertutup</th>
                  <th>Menang</th>
                  <th>Win rate</th>
                  <th>Net</th>
                </tr>
              </thead>
              <tbody>
                {(payload.symbols ?? []).map((s) => (
                  <tr key={s.symbol}>
                    <td><strong>{s.symbol}</strong></td>
                    <td>{s.closed}</td>
                    <td>{s.wins}</td>
                    <td>{percent(s.win_rate)}</td>
                    <td className={pnlClass(s.net)}>{money(s.net, payload.account?.currency)}</td>
                  </tr>
                ))}
                {(payload.symbols ?? []).length === 0 && (
                  <tr>
                    <td colSpan={5} className={styles.muted}>Tidak ada data.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
