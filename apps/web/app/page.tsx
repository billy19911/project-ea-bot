'use client';

import Head from 'next/head';
import { useEffect, useMemo, useState } from 'react';
import styles from './page.module.css';
import { apiFetch } from '../lib/api';
import AppShell from '../components/AppShell';

type SourceState = 'live' | 'unavailable';
type AiModel = { id: string; provider: string; context: number; is_free: boolean; capabilities?: string[] };
type ModelsState = { models: AiModel[]; source: SourceState };

type Experiment = { id: string; name: string; strategy: string; period: string; status: 'Selesai' | 'Berjalan' | 'Menunggu'; pnl: number; sharpe: number; drawdown: number; trades: number };

export default function Home() {
  const [researchTab, setResearchTab] = useState('Eksperimen');
  // No experiments API exists yet. Keep this as real (empty) state rather than
  // fabricating rows; it is populated once ResearchEngine produces runs.
  const [experiments] = useState<Experiment[]>([]);
  const [notice, setNotice] = useState('');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [modelsState, setModelsState] = useState<ModelsState>({ models: [], source: 'unavailable' });
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch(`/ai/models`);
        if (!res.ok) {
          if (!cancelled) setModelsState({ models: [], source: 'unavailable' });
          return;
        }
        const data = await res.json();
        if (cancelled) return;
        setModelsState({
          models: Array.isArray(data.models) ? data.models : [],
          source: data.source === 'live' ? 'live' : 'unavailable',
        });
      } catch {
        if (!cancelled) setModelsState({ models: [], source: 'unavailable' });
      }
    })();
    return () => { cancelled = true; };
  }, []);
  const filtered = useMemo(() => experiments.filter((item) => item.name.toLowerCase().includes(query.toLowerCase()) || item.strategy.toLowerCase().includes(query.toLowerCase())), [experiments, query]);
  const runBacktest = () => { setNotice('Permintaan backtest dicatat. Jalankan pipeline di Control Plane untuk hasil nyata.'); setTimeout(() => setNotice(''), 4000); setResearchTab('Backtest'); };

  return <>
    <Head><title>EA Bot — Pusat Riset</title><meta name="description" content="EA Bot research center" /></Head>
    <AppShell
      activeKey="research"
      eyebrow="EA BOT / PUSAT RISET"
      title="Pusat Riset"
      actions={
        <>
          <span className={`${styles.badge} ${modelsState.source === 'live' ? styles.success : styles.muted}`}>{modelsState.source === 'live' ? 'MODELS LIVE' : 'MODELS N/A'}</span>
        </>
      }
    >
      {/* Hanya SATU strip tab di halaman ini (sub-tab Research). Pengaturan
          pindah ke halaman /settings — sebelumnya dua baris tab bertumpuk. */}
      {notice && <div className={styles.notice}>{notice}</div>}
      <ResearchView tab={researchTab} setTab={setResearchTab} experiments={experiments} filtered={filtered} query={query} setQuery={setQuery} selected={selected} setSelected={setSelected} runBacktest={runBacktest} />
    </AppShell>
  </>;
}

function ResearchView({ tab, setTab, experiments, filtered, query, setQuery, selected, setSelected, runBacktest }: { tab: string; setTab: (tab: string) => void; experiments: Experiment[]; filtered: Experiment[]; query: string; setQuery: (value: string) => void; selected: string[]; setSelected: (ids: string[]) => void; runBacktest: () => void }) {
  const tabs = ['Eksperimen', 'Backtest', 'Perbandingan', 'Hasil Riset'];
  return <div className={styles.pageBody}><nav className={styles.tabs}>{tabs.map((item) => <button key={item} className={tab === item ? styles.tabActive : ''} onClick={() => setTab(item)}>{item}</button>)}</nav>
    {tab === 'Eksperimen' && <><div className={styles.sectionHead}><div><h2>Eksperimen strategi</h2><p>Hipotesis, parameter, dan hasil validasi terpusat.</p></div><button className={styles.primary} onClick={runBacktest}>＋ Jalankan backtest</button></div><div className={styles.toolbar}><input aria-label="Cari eksperimen" placeholder="Cari nama atau strategi..." value={query} onChange={(event) => setQuery(event.target.value)} /><select defaultValue="all" aria-label="Filter status"><option value="all">Semua status</option><option>Selesai</option><option>Berjalan</option><option>Menunggu</option></select><span className={styles.resultCount}>{filtered.length} eksperimen</span></div><ExperimentTable items={filtered} /></>}
    {tab === 'Backtest' && <BacktestPanel runBacktest={runBacktest} />}
    {tab === 'Perbandingan' && <Comparison experiments={experiments} selected={selected} setSelected={setSelected} />}
    {tab === 'Hasil Riset' && <Results />}
  </div>;
}

function ExperimentTable({ items }: { items: Experiment[] }) { return <div className={styles.tableCard}><table><thead><tr><th>Eksperimen</th><th>Strategi</th><th>Periode</th><th>Status</th><th>PnL</th><th>Sharpe</th><th>Max DD</th><th>Trades</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td><strong>{item.name}</strong><small>{item.id}</small></td><td>{item.strategy}</td><td>{item.period}</td><td><span className={`${styles.badge} ${item.status === 'Selesai' ? styles.success : item.status === 'Berjalan' ? styles.warning : styles.muted}`}>{item.status}</span></td><td className={item.pnl > 0 ? styles.positive : ''}>{item.pnl ? `+${item.pnl.toFixed(1)}%` : '—'}</td><td>{item.sharpe || '—'}</td><td>{item.drawdown ? `${item.drawdown}%` : '—'}</td><td>{item.trades || '—'}</td></tr>)}</tbody></table>{!items.length && <div className={styles.empty}>Belum ada eksperimen. Data akan muncul setelah ResearchEngine dijalankan. <a href="/control-plane">Buka Control Plane</a></div>}</div>; }

function BacktestPanel({ runBacktest }: { runBacktest: () => void }) { return <><div className={styles.sectionHead}><div><h2>Backtest</h2><p>Jalankan simulasi historis dengan ResearchEngine.</p></div><button className={styles.primary} onClick={runBacktest}>Jalankan simulasi</button></div><div className={styles.backtestGrid}><div className={styles.card}><h3>Konfigurasi</h3><label>Data historis<select defaultValue="gold"><option>XAUUSD · H1 · 2022—2024</option><option>XAUUSD · M15 · 2024</option></select></label><label>Modal awal<input defaultValue="10000" type="number" /></label><div className={styles.inline}><label>Komisi<input defaultValue="0.0" /></label><label>Slippage<input defaultValue="2" /></label></div></div><div className={styles.card}><h3>Hasil terakhir</h3><div className={styles.empty}>Belum ada hasil backtest.</div><div className={styles.resultNote}>Jalankan pipeline di Control Plane untuk menghasilkan metrik nyata.</div></div></div></>; }
function Comparison({ experiments, selected, setSelected }: { experiments: Experiment[]; selected: string[]; setSelected: (ids: string[]) => void }) {
  const names = experiments.filter((item) => item.status === 'Selesai');
  const a = names.find((item) => item.id === selected[0]);
  const b = names.find((item) => item.id === selected[1]);
  const ready = Boolean(a && b);
  const fmtDelta = (valueA: number, valueB: number, unit = '') => {
    const delta = valueB - valueA;
    const sign = delta > 0 ? '+' : delta < 0 ? '−' : '';
    return `${sign}${Math.abs(delta).toFixed(2)}${unit}`;
  };
  const rows: [string, string, string, string, boolean][] = ready ? [
    ['Net PnL', `${a!.pnl.toFixed(1)}%`, `${b!.pnl.toFixed(1)}%`, fmtDelta(a!.pnl, b!.pnl, '%'), b!.pnl - a!.pnl >= 0],
    ['Sharpe ratio', a!.sharpe.toFixed(2), b!.sharpe.toFixed(2), fmtDelta(a!.sharpe, b!.sharpe), b!.sharpe - a!.sharpe >= 0],
    ['Max drawdown', `${a!.drawdown.toFixed(1)}%`, `${b!.drawdown.toFixed(1)}%`, fmtDelta(a!.drawdown, b!.drawdown, '%'), b!.drawdown - a!.drawdown <= 0],
    ['Trades', `${a!.trades}`, `${b!.trades}`, fmtDelta(a!.trades, b!.trades), b!.trades - a!.trades >= 0],
  ] : [];
  return <><div className={styles.sectionHead}><div><h2>Perbandingan hasil</h2><p>Pilih dua eksperimen selesai untuk melihat delta metrik.</p></div>{names.length >= 2 && <div className={styles.compareSelect}>{names.map((item) => <label key={item.id}><input type="checkbox" checked={selected.includes(item.id)} disabled={!selected.includes(item.id) && selected.length >= 2} onChange={() => setSelected(selected.includes(item.id) ? selected.filter((id) => id !== item.id) : [...selected, item.id])} /> {item.id}</label>)}</div>}</div>{ready ? <div className={styles.tableCard}><table><thead><tr><th>Metrik</th><th>Eksperimen A</th><th>Eksperimen B</th><th>Delta B − A</th></tr></thead><tbody>{rows.map(([label, aVal, bVal, delta, good]) => <tr key={label}><td><strong>{label}</strong></td><td>{aVal}</td><td>{bVal}</td><td className={good ? styles.positive : styles.negative}>{delta}</td></tr>)}</tbody></table></div> : <div className={styles.empty}>Pilih dua eksperimen selesai untuk membandingkan.</div>}</>; }
function Results() { return <><div className={styles.sectionHead}><div><h2>Hasil riset</h2><p>Kesimpulan yang siap dipakai untuk review strategi.</p></div></div><div className={styles.empty}>Belum ada hasil riset. Temuan akan muncul setelah eksperimen dijalankan di Control Plane.</div></>; }
