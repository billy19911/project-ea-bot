'use client';

/**
 * Pusat Riset (UI/UX ide #6) — tersambung ke ResearchEngine NYATA di layanan
 * Python lewat proxy Node:
 *
 *   GET  /research/overview                     — counts + catatan jujur
 *   GET  /research/experiments                  — daftar eksperimen
 *   POST /research/experiments                  — buat eksperimen (EMA pair)
 *   POST /research/experiments/:id/backtest     — backtest atas bar NYATA MT5
 *   GET  /research/experiments/:id              — detail + provenance + trades
 *   POST /research/compare                      — bandingkan 2 eksperimen
 *
 * Aturan jujur:
 * - tidak ada baris eksperimen fabrikasi — daftar datang dari backend;
 * - backtest menolak saat live mode OFF / bar kurang, dan alasannya ditampilkan;
 * - hasil disimpan di memori layanan Python — catatan itu selalu tampil;
 * - PnL = selisih harga per unit (ukuran posisi tidak dimodelkan) — dilabeli.
 */

import Head from 'next/head';
import { useCallback, useEffect, useState } from 'react';
import styles from './page.module.css';
import { apiFetch } from '../lib/api';
import AppShell from '../components/AppShell';

type Overview = {
  ok: boolean;
  hypotheses: number;
  experiments: number;
  completed: number;
  engine_note?: string;
  data_note?: string;
};

type Metrics = {
  total_trades: number;
  win_rate: number | null;
  profit_factor: number | null;
  sharpe_ratio: number | null;
  max_drawdown: number | null;
  expectation: number | null;
  net_pnl: number | null;
};

type ExperimentRow = {
  id: string;
  name: string;
  strategy_version: string;
  parameters: Record<string, number | string | boolean>;
  status: string;
  has_result: boolean;
  metrics: Metrics | null;
};

type WalkForwardWindow = { name: string; range: number[]; metrics: Metrics };

type Provenance = {
  symbol: string;
  timeframe: string;
  bars: number;
  ran_at: string;
  source: string;
  account: { login: number | null; server: string | null; currency: string | null } | null;
};

type RunResult = {
  ok: boolean;
  reason?: string;
  metrics?: Metrics;
  provenance?: Provenance;
  walk_forward?: { enabled: boolean; train_ratio?: number; windows?: WalkForwardWindow[] };
  trades_total?: number;
  trades_preview?: Array<Record<string, unknown>>;
};

type Detail = {
  ok: boolean;
  metrics: Metrics | null;
  walk_forward: { enabled: boolean; windows?: WalkForwardWindow[] } | null;
  trades_total: number;
  trades_preview: Array<Record<string, unknown>>;
  provenance: Provenance | null;
};

const TABS = ['Eksperimen', 'Backtest', 'Perbandingan'] as const;

function fmt(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toFixed(digits);
}

function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${value.toFixed(1)}%`;
}

export default function Home() {
  const [tab, setTab] = useState<(typeof TABS)[number]>('Eksperimen');
  const [overview, setOverview] = useState<Overview | null>(null);
  const [experiments, setExperiments] = useState<ExperimentRow[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  // Create-experiment form
  const [fast, setFast] = useState('3');
  const [slow, setSlow] = useState('8');

  // Backtest form
  const [selectedId, setSelectedId] = useState('');
  const [symbol, setSymbol] = useState('XAUUSD');
  const [timeframe, setTimeframe] = useState('H1');
  const [bars, setBars] = useState('500');
  const [runResult, setRunResult] = useState<RunResult | null>(null);

  // Detail
  const [detail, setDetail] = useState<Detail | null>(null);

  // Compare
  const [cmpA, setCmpA] = useState('');
  const [cmpB, setCmpB] = useState('');
  const [cmpResult, setCmpResult] = useState<Record<string, unknown> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [ovRes, exRes] = await Promise.all([
        apiFetch('/research/overview'),
        apiFetch('/research/experiments'),
      ]);
      if (ovRes.status === 401 || exRes.status === 401) {
        setError('Sesi tidak valid — buka halaman Masuk untuk mendapatkan token.');
        return;
      }
      if (!ovRes.ok || !exRes.ok) {
        setError('Layanan riset tidak menjawab — periksa Python API (:8000).');
        return;
      }
      const ov = (await ovRes.json()) as Overview;
      const ex = (await exRes.json()) as { experiments: ExperimentRow[] };
      setOverview(ov);
      setExperiments(ex.experiments ?? []);
      setError('');
      const withResults = (ex.experiments ?? []).filter((e) => e.has_result);
      setSelectedId((current) => current || withResults[0]?.id || ex.experiments?.[0]?.id || '');
    } catch {
      setError('Layanan riset tidak menjawab — periksa Python API (:8000).');
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const flash = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(''), 5000);
  };

  const createExperiment = async () => {
    setBusy(true);
    try {
      const res = await apiFetch('/research/experiments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fast_ema_period: Number(fast) || 3,
          slow_ema_period: Number(slow) || 8,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(String(data.detail || 'Gagal membuat eksperimen.'));
        return;
      }
      setError('');
      flash(`Eksperimen dibuat: EMA ${fast}/${slow}. Jalankan backtest di tab Backtest.`);
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const runBacktest = async () => {
    if (!selectedId) {
      setError('Pilih eksperimen dulu.');
      return;
    }
    setBusy(true);
    setRunResult(null);
    try {
      const res = await apiFetch(`/research/experiments/${encodeURIComponent(selectedId)}/backtest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: symbol.trim().toUpperCase(),
          timeframe,
          bars: Number(bars) || 500,
        }),
      });
      const data = (await res.json()) as RunResult;
      if (!res.ok) {
        setError(String((data as { detail?: string }).detail || 'Backtest gagal dijalankan.'));
        return;
      }
      setError('');
      setRunResult(data);
      if (!data.ok && data.reason) flash(data.reason);
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const loadDetail = async (id: string) => {
    try {
      const res = await apiFetch(`/research/experiments/${encodeURIComponent(id)}`);
      if (!res.ok) {
        setDetail(null);
        return;
      }
      setDetail((await res.json()) as Detail);
    } catch {
      setDetail(null);
    }
  };

  const runCompare = async () => {
    if (!cmpA || !cmpB) {
      setError('Pilih dua eksperimen dengan hasil backtest.');
      return;
    }
    setBusy(true);
    try {
      const res = await apiFetch('/research/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id_a: cmpA, id_b: cmpB }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(String(data.detail || 'Perbandingan gagal.'));
        return;
      }
      setError('');
      setCmpResult(data);
    } finally {
      setBusy(false);
    }
  };

  const withResults = experiments.filter((e) => e.has_result);

  return (
    <>
      <Head>
        <title>EA Bot — Pusat Riset</title>
        <meta name="description" content="EA Bot research center" />
      </Head>
      <AppShell
        activeKey="research"
        eyebrow="EA BOT / PUSAT RISET"
        title="Pusat Riset"
        actions={
          <span className={`${styles.badge} ${styles.success}`}>
            {overview ? `${overview.experiments} EKSPERIMEN` : 'MEMUAT…'}
          </span>
        }
      >
        <div className={styles.pageBody}>
          {error && <div className={styles.noticeError}>{error}</div>}
          {notice && <div className={styles.notice}>{notice}</div>}

          <nav className={styles.tabs}>
            {TABS.map((item) => (
              <button
                key={item}
                className={tab === item ? styles.tabActive : ''}
                onClick={() => setTab(item)}
              >
                {item}
              </button>
            ))}
          </nav>

          {tab === 'Eksperimen' && (
            <>
              <div className={styles.sectionHead}>
                <div>
                  <h2>Eksperimen strategi</h2>
                  <p>
                    Hipotesis baseline: EMA crossover (implementasi indikator nyata
                    proyek). Buat eksperimen dengan pasangan periode EMA.
                  </p>
                </div>
              </div>
              <div className={styles.toolbar}>
                <label className={styles.field}>
                  EMA cepat
                  <input
                    type="number"
                    min={1}
                    max={200}
                    value={fast}
                    onChange={(e) => setFast(e.target.value)}
                  />
                </label>
                <label className={styles.field}>
                  EMA lambat
                  <input
                    type="number"
                    min={2}
                    max={400}
                    value={slow}
                    onChange={(e) => setSlow(e.target.value)}
                  />
                </label>
                <button className={styles.primary} onClick={createExperiment} disabled={busy}>
                  ＋ Buat eksperimen
                </button>
                <span className={styles.resultCount}>{experiments.length} eksperimen</span>
              </div>
              <ExperimentTable
                items={experiments}
                onSelect={(id) => {
                  void loadDetail(id);
                }}
              />
              {detail && <DetailCard detail={detail} />}
            </>
          )}

          {tab === 'Backtest' && (
            <>
              <div className={styles.sectionHead}>
                <div>
                  <h2>Backtest</h2>
                  <p>
                    Simulasi deterministik atas bar harga NYATA dari terminal MT5
                    yang terpasang (read-only). Bukan data acak.
                  </p>
                </div>
              </div>
              <div className={styles.card}>
                <label className={styles.field}>
                  Eksperimen
                  <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
                    {experiments.length === 0 && <option value="">(belum ada — buat dulu)</option>}
                    {experiments.map((e) => (
                      <option key={e.id} value={e.id}>
                        {e.name} · {e.id.slice(0, 8)}
                      </option>
                    ))}
                  </select>
                </label>
                <div className={styles.inline}>
                  <label className={styles.field}>
                    Simbol
                    <input value={symbol} onChange={(e) => setSymbol(e.target.value)} />
                  </label>
                  <label className={styles.field}>
                    Timeframe
                    <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
                      {['M5', 'M15', 'M30', 'H1', 'H4', 'D1'].map((tf) => (
                        <option key={tf}>{tf}</option>
                      ))}
                    </select>
                  </label>
                  <label className={styles.field}>
                    Jumlah bar
                    <input
                      type="number"
                      min={100}
                      max={2000}
                      value={bars}
                      onChange={(e) => setBars(e.target.value)}
                    />
                  </label>
                </div>
                <button className={styles.primary} onClick={runBacktest} disabled={busy || !selectedId}>
                  {busy ? 'Menjalankan…' : 'Jalankan backtest'}
                </button>
              </div>
              {runResult && <RunResultCard result={runResult} />}
            </>
          )}

          {tab === 'Perbandingan' && (
            <>
              <div className={styles.sectionHead}>
                <div>
                  <h2>Perbandingan hasil</h2>
                  <p>Bandingkan dua eksperimen yang sudah punya hasil backtest.</p>
                </div>
              </div>
              {withResults.length < 2 ? (
                <div className={styles.empty}>
                  Butuh dua eksperimen dengan hasil. Jalankan backtest dulu di tab Backtest.
                </div>
              ) : (
                <div className={styles.card}>
                  <div className={styles.inline}>
                    <label className={styles.field}>
                      Eksperimen A
                      <select value={cmpA} onChange={(e) => setCmpA(e.target.value)}>
                        <option value="">(pilih)</option>
                        {withResults.map((e) => (
                          <option key={e.id} value={e.id}>
                            {e.name} · {e.id.slice(0, 8)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className={styles.field}>
                      Eksperimen B
                      <select value={cmpB} onChange={(e) => setCmpB(e.target.value)}>
                        <option value="">(pilih)</option>
                        {withResults.map((e) => (
                          <option key={e.id} value={e.id}>
                            {e.name} · {e.id.slice(0, 8)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button className={styles.primary} onClick={runCompare} disabled={busy}>
                      Bandingkan
                    </button>
                  </div>
                </div>
              )}
              {cmpResult && <CompareCard result={cmpResult} />}
            </>
          )}

          {(overview?.engine_note || overview?.data_note) && (
            <p className={styles.mutedText}>
              {overview?.engine_note} {overview?.data_note}
            </p>
          )}
        </div>
      </AppShell>
    </>
  );
}

function ExperimentTable({ items, onSelect }: { items: ExperimentRow[]; onSelect: (id: string) => void }) {
  if (!items.length) {
    return (
      <div className={styles.empty}>
        Belum ada eksperimen. Buat satu dengan pasangan periode EMA di atas — backtest
        berjalan atas bar nyata dari terminal MT5.
      </div>
    );
  }
  return (
    <div className={styles.tableCard}>
      <table>
        <thead>
          <tr>
            <th>Eksperimen</th>
            <th>Parameter</th>
            <th>Status</th>
            <th>Trades</th>
            <th>Win rate</th>
            <th>PnL / unit</th>
            <th>Max DD</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>
                <strong>{item.name}</strong>
                <small>{item.id.slice(0, 8)}</small>
              </td>
              <td>
                {Object.entries(item.parameters)
                  .map(([k, v]) => `${k}=${v}`)
                  .join(', ') || '—'}
              </td>
              <td>
                <span
                  className={`${styles.badge} ${
                    item.has_result ? styles.success : styles.muted
                  }`}
                >
                  {item.has_result ? 'Ada hasil' : 'Belum diuji'}
                </span>
              </td>
              <td>{item.metrics ? item.metrics.total_trades : '—'}</td>
              <td>{item.metrics ? fmtPct(item.metrics.win_rate) : '—'}</td>
              <td
                className={
                  item.metrics && (item.metrics.net_pnl ?? 0) > 0 ? styles.positive : ''
                }
              >
                {item.metrics ? fmt(item.metrics.net_pnl) : '—'}
              </td>
              <td>{item.metrics ? fmtPct(item.metrics.max_drawdown) : '—'}</td>
              <td>
                <button onClick={() => onSelect(item.id)}>Detail</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MetricsGrid({ metrics }: { metrics: Metrics }) {
  return (
    <div className={styles.metrics}>
      <div>
        <small>Trades</small>
        <strong>{metrics.total_trades}</strong>
      </div>
      <div>
        <small>Win rate</small>
        <strong>{fmtPct(metrics.win_rate)}</strong>
      </div>
      <div>
        <small>Profit factor</small>
        <strong>{fmt(metrics.profit_factor)}</strong>
      </div>
      <div>
        <small>Sharpe</small>
        <strong>{fmt(metrics.sharpe_ratio)}</strong>
      </div>
      <div>
        <small>Max drawdown</small>
        <strong>{fmtPct(metrics.max_drawdown)}</strong>
      </div>
      <div>
        <small>Ekspektasi / trade</small>
        <strong>{fmt(metrics.expectation)}</strong>
      </div>
      <div>
        <small>PnL / unit</small>
        <strong className={(metrics.net_pnl ?? 0) > 0 ? styles.positive : styles.negative}>
          {fmt(metrics.net_pnl)}
        </strong>
      </div>
    </div>
  );
}

function WalkForwardCard({ wf }: { wf: { enabled: boolean; train_ratio?: number; windows?: WalkForwardWindow[] } }) {
  if (!wf.enabled || !wf.windows?.length) return null;
  return (
    <div className={styles.card}>
      <h3>Walk-forward (split {wf.train_ratio ? `${Math.round(wf.train_ratio * 100)}/${Math.round((1 - wf.train_ratio) * 100)}` : '70/30'})</h3>
      <div className={styles.tableCard}>
        <table>
          <thead>
            <tr>
              <th>Jendela</th>
              <th>Bar</th>
              <th>Trades</th>
              <th>Win rate</th>
              <th>PnL / unit</th>
            </tr>
          </thead>
          <tbody>
            {wf.windows.map((w) => (
              <tr key={w.name}>
                <td>{w.name}</td>
                <td>
                  {w.range[0]}–{w.range[1]}
                </td>
                <td>{w.metrics.total_trades}</td>
                <td>{fmtPct(w.metrics.win_rate)}</td>
                <td className={(w.metrics.net_pnl ?? 0) > 0 ? styles.positive : ''}>
                  {fmt(w.metrics.net_pnl)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ProvenanceLine({ provenance }: { provenance: Provenance }) {
  const account = provenance.account;
  return (
    <p className={styles.mutedText}>
      Sumber: {provenance.symbol} · {provenance.timeframe} · {provenance.bars} bar nyata
      {account?.login ? ` — akun ${account.login} (${account.server ?? '—'})` : ''} ·{' '}
      {provenance.ran_at.replace('T', ' ').replace('+00:00', ' UTC')}
    </p>
  );
}

// Label tampilan untuk alasan keluar backtest — kode mentah dari engine tetap
// `stop_loss`/`take_profit`/`signal_reversal`/`end_of_data` (dipakai logika),
// hanya tampilan yang diterjemahkan. Kode tak dikenal ditampilkan apa adanya.
const EXIT_REASON_LABELS: Record<string, string> = {
  stop_loss: 'Stop loss',
  take_profit: 'Take profit',
  signal_reversal: 'Sinyal berbalik',
  end_of_data: 'Data habis',
};

function TradesPreview({ trades }: { trades: Array<Record<string, unknown>> }) {
  if (!trades.length) return null;
  return (
    <div className={styles.card}>
      <h3>Trade terakhir (preview)</h3>
      <div className={styles.tableCard}>
        <table>
          <thead>
            <tr>
              <th>Entry</th>
              <th>SL</th>
              <th>TP</th>
              <th>Exit</th>
              <th>Arah</th>
              <th>PnL / unit</th>
              <th>Alasan keluar</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t, i) => (
              <tr key={i}>
                <td>{fmt(Number(t.entry))}</td>
                <td>{t.stop_loss == null ? '—' : fmt(Number(t.stop_loss))}</td>
                <td>{t.take_profit == null ? '—' : fmt(Number(t.take_profit))}</td>
                <td>{fmt(Number(t.exit))}</td>
                <td>{Number(t.direction) === 1 ? 'Long' : 'Short'}</td>
                <td className={Number(t.pnl) > 0 ? styles.positive : styles.negative}>
                  {fmt(Number(t.pnl))}
                </td>
                <td>{EXIT_REASON_LABELS[String(t.exit_reason ?? '')] ?? String(t.exit_reason ?? '—')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RunResultCard({ result }: { result: RunResult }) {
  if (!result.ok) {
    return <div className={styles.noticeError}>{result.reason ?? 'Backtest tidak berjalan.'}</div>;
  }
  return (
    <>
      {result.provenance && <ProvenanceLine provenance={result.provenance} />}
      {result.metrics && <MetricsGrid metrics={result.metrics} />}
      {result.walk_forward && <WalkForwardCard wf={result.walk_forward} />}
      {result.trades_preview && <TradesPreview trades={result.trades_preview} />}
    </>
  );
}

function DetailCard({ detail }: { detail: Detail }) {
  if (!detail.metrics) {
    return <div className={styles.empty}>Eksperimen ini belum punya hasil backtest.</div>;
  }
  return (
    <>
      {detail.provenance && <ProvenanceLine provenance={detail.provenance} />}
      <MetricsGrid metrics={detail.metrics} />
      {detail.walk_forward && <WalkForwardCard wf={detail.walk_forward} />}
      <TradesPreview trades={detail.trades_preview} />
    </>
  );
}

const COMPARE_METRICS: Array<[string, string]> = [
  ['total_trades', 'Trades'],
  ['win_rate', 'Win rate (%)'],
  ['profit_factor', 'Profit factor'],
  ['sharpe_ratio', 'Sharpe'],
  ['max_drawdown', 'Max drawdown (%)'],
  ['expectation', 'Ekspektasi / trade'],
  ['net_pnl', 'PnL / unit'],
];

function CompareCard({ result }: { result: Record<string, unknown> }) {
  const a = result.experiment_1 as Record<string, unknown>;
  const b = result.experiment_2 as Record<string, unknown>;
  const diff = result.difference as Record<string, unknown>;
  return (
    <div className={styles.tableCard}>
      <table>
        <thead>
          <tr>
            <th>Metrik</th>
            <th>A: {String(a.name)}</th>
            <th>B: {String(b.name)}</th>
            <th>Delta B − A</th>
          </tr>
        </thead>
        <tbody>
          {COMPARE_METRICS.map(([key, label]) => {
            const av = a[key] as number | null;
            const bv = b[key] as number | null;
            const dv = diff[key] as number | null;
            return (
              <tr key={key}>
                <td>
                  <strong>{label}</strong>
                </td>
                <td>{fmt(av)}</td>
                <td>{fmt(bv)}</td>
                <td className={(dv ?? 0) >= 0 ? styles.positive : styles.negative}>
                  {dv === null || dv === undefined ? '—' : `${dv >= 0 ? '+' : ''}${fmt(dv)}`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
