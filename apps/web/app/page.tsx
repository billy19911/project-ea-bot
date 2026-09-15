'use client';

import Head from 'next/head';
import { FormEvent, Fragment, useEffect, useMemo, useState } from 'react';
import styles from './page.module.css';
import { apiFetch } from '../lib/api';

type SourceState = 'live' | 'unavailable';
type AiModel = { id: string; provider: string; context: number; is_free: boolean; capabilities?: string[] };
type ModelsState = { models: AiModel[]; source: SourceState };

type Experiment = { id: string; name: string; strategy: string; period: string; status: 'Selesai' | 'Berjalan' | 'Menunggu'; pnl: number; sharpe: number; drawdown: number; trades: number };
type Settings = { account: { name: string; email: string; broker: string; mode: string }; risk: { maxDrawdown: string; dailyLoss: string; exposure: string; maxPositions: string }; ai: { model: string; budget: string; temperature: string }; execution: { venue: string; slippage: string; timeout: string; paper: boolean }; notifications: { email: boolean; telegram: boolean; risk: boolean; research: boolean }; safety: { killSwitch: boolean; emergencyStop: boolean } };

const defaultSettings: Settings = {
  account: { name: 'Administrator', email: 'admin@example.com', broker: 'MetaTrader 5', mode: 'paper' },
  risk: { maxDrawdown: '15', dailyLoss: '5', exposure: '30', maxPositions: '5' },
  ai: { model: '', budget: '12000', temperature: '0.2' },
  execution: { venue: 'MT5', slippage: '2', timeout: '10', paper: true },
  notifications: { email: true, telegram: true, risk: true, research: false },
  safety: { killSwitch: false, emergencyStop: false },
};

function loadSettings(): Settings {
  if (typeof window === 'undefined') return defaultSettings;
  try { return { ...defaultSettings, ...JSON.parse(localStorage.getItem('ea-bot-settings') || '{}') }; } catch { return defaultSettings; }
}

export default function Home() {
  const [section, setSection] = useState<'research' | 'settings'>('research');
  const [researchTab, setResearchTab] = useState('Eksperimen');
  const [settingsTab, setSettingsTab] = useState('Akun');
  // No experiments API exists yet. Keep this as real (empty) state rather than
  // fabricating rows; it is populated once ResearchEngine produces runs.
  const [experiments] = useState<Experiment[]>([]);
  const [settings, setSettings] = useState<Settings>(defaultSettings);
  const [notice, setNotice] = useState('');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [modelsState, setModelsState] = useState<ModelsState>({ models: [], source: 'unavailable' });

  useEffect(() => setSettings(loadSettings()), []);
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
  const updateGroup = <K extends keyof Settings>(group: K, field: keyof Settings[K], value: string | boolean) => setSettings((current) => ({ ...current, [group]: { ...current[group], [field]: value } }));
  const saveSettings = (event: FormEvent) => { event.preventDefault(); localStorage.setItem('ea-bot-settings', JSON.stringify(settings)); setNotice('Pengaturan tersimpan di perangkat ini.'); setTimeout(() => setNotice(''), 2500); };
  const runBacktest = () => { setNotice('Permintaan backtest dicatat. Jalankan pipeline di Control Plane untuk hasil nyata.'); setTimeout(() => setNotice(''), 4000); setResearchTab('Backtest'); };

  return <>
    <Head><title>EA Bot — Research & Settings</title><meta name="description" content="EA Bot control center" /></Head>
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}><span className={styles.brandMark}>EA</span><div><strong>EA BOT</strong><small>TRADING CONTROL</small></div></div>
        <div className={styles.workspaceLabel}>WORKSPACE</div>
        <button className={`${styles.navItem} ${section === 'research' ? styles.active : ''}`} onClick={() => setSection('research')}><span>▦</span> Research Center</button>
        <button className={`${styles.navItem} ${section === 'settings' ? styles.active : ''}`} onClick={() => setSection('settings')}><span>⚙</span> System Settings</button>
        <a href="/control-plane" className={styles.navItem}><span>▦</span> Control Plane</a>
        <a href="/ai-control" className={styles.navItem}><span>🧠</span> AI Control Center</a>
        <a href="/strategy" className={styles.navItem}><span>📡</span> Strategy Center</a>
        <a href="/observability" className={styles.navItem}><span>📊</span> Observability</a>
        <div className={styles.sidebarBottom}><span className={styles.greenDot} /> Sistem aktif<div className={styles.version}>v1.0.0 · Paper mode</div></div>
      </aside>
      <main className={styles.main}>
        <header className={styles.topbar}><div><div className={styles.eyebrow}>EA BOT / {section === 'research' ? 'RESEARCH CENTER' : 'SYSTEM SETTINGS'}</div><h1>{section === 'research' ? 'Research Center' : 'System Settings'}</h1></div><div className={styles.topActions}><span className={`${styles.badge} ${modelsState.source === 'live' ? styles.success : styles.muted}`}>{modelsState.source === 'live' ? 'MODELS LIVE' : 'MODELS N/A'}</span><span className={styles.envBadge}>PAPER</span><span className={styles.avatar}>A</span></div></header>
        {notice && <div className={styles.notice}>{notice}</div>}
        {section === 'research' ? <ResearchView tab={researchTab} setTab={setResearchTab} experiments={experiments} filtered={filtered} query={query} setQuery={setQuery} selected={selected} setSelected={setSelected} runBacktest={runBacktest} /> : <SettingsView tab={settingsTab} setTab={setSettingsTab} settings={settings} updateGroup={updateGroup} saveSettings={saveSettings} modelsState={modelsState} />}
      </main>
    </div>
  </>;
}

function ResearchView({ tab, setTab, experiments, filtered, query, setQuery, selected, setSelected, runBacktest }: { tab: string; setTab: (tab: string) => void; experiments: Experiment[]; filtered: Experiment[]; query: string; setQuery: (value: string) => void; selected: string[]; setSelected: (ids: string[]) => void; runBacktest: () => void }) {
  const tabs = ['Eksperimen', 'Backtest', 'Perbandingan', 'Hasil Riset'];
  return <div className={styles.pageBody}><nav className={styles.tabs}>{tabs.map((item) => <button key={item} className={tab === item ? styles.tabActive : ''} onClick={() => setTab(item)}>{item}</button>)}</nav>
    {tab === 'Eksperimen' && <><div className={styles.sectionHead}><div><h2>Eksperimen strategi</h2><p>Hipotesis, parameter, dan hasil validasi terpusat.</p></div><button className={styles.primary} onClick={runBacktest}>＋ Jalankan backtest</button></div><div className={styles.toolbar}><input aria-label="Cari eksperimen" placeholder="Cari nama atau strategi..." value={query} onChange={(event) => setQuery(event.target.value)} /><select defaultValue="all" aria-label="Filter status"><option value="all">Semua status</option><option>Selesai</option><option>Berjalan</option><option>Menunggu</option></select><span className={styles.resultCount}>{filtered.length} eksperimen</span></div><ExperimentTable items={filtered} compact /></>}
    {tab === 'Backtest' && <BacktestPanel runBacktest={runBacktest} />}
    {tab === 'Perbandingan' && <Comparison experiments={experiments} selected={selected} setSelected={setSelected} />}
    {tab === 'Hasil Riset' && <Results />}
  </div>;
}

function ExperimentTable({ items, compact = false }: { items: Experiment[]; compact?: boolean }) { return <div className={styles.tableCard}><table><thead><tr><th>Eksperimen</th><th>Strategi</th><th>Periode</th><th>Status</th><th>PnL</th><th>Sharpe</th><th>Max DD</th><th>Trades</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td><strong>{item.name}</strong><small>{item.id}</small></td><td>{item.strategy}</td><td>{item.period}</td><td><span className={`${styles.badge} ${item.status === 'Selesai' ? styles.success : item.status === 'Berjalan' ? styles.warning : styles.muted}`}>{item.status}</span></td><td className={item.pnl > 0 ? styles.positive : ''}>{item.pnl ? `+${item.pnl.toFixed(1)}%` : '—'}</td><td>{item.sharpe || '—'}</td><td>{item.drawdown ? `${item.drawdown}%` : '—'}</td><td>{item.trades || '—'}</td></tr>)}</tbody></table>{!items.length && <div className={styles.empty}>Belum ada eksperimen. Data akan muncul setelah ResearchEngine dijalankan. <a href="/control-plane">Buka Control Plane</a></div>}</div>; }

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

function SettingsView({ tab, setTab, settings, updateGroup, saveSettings, modelsState }: { tab: string; setTab: (tab: string) => void; settings: Settings; updateGroup: <K extends keyof Settings>(group: K, field: keyof Settings[K], value: string | boolean) => void; saveSettings: (event: FormEvent) => void; modelsState: ModelsState }) { const tabs = ['Akun', 'Risiko', 'AI', 'Model registry', 'Eksekusi', 'Notifikasi', 'Safety']; return <div className={styles.pageBody}><nav className={styles.tabs}>{tabs.map((item) => <button key={item} className={tab === item ? styles.tabActive : ''} onClick={() => setTab(item)}>{item}</button>)}</nav><form onSubmit={saveSettings}>{tab === 'Akun' && <FormSection title="Akun & koneksi" description="Identitas workspace dan koneksi broker."><Field label="Nama pengguna"><input value={settings.account.name} onChange={(e) => updateGroup('account', 'name', e.target.value)} /></Field><Field label="Email"><input type="email" value={settings.account.email} onChange={(e) => updateGroup('account', 'email', e.target.value)} /></Field><Field label="Broker"><select value={settings.account.broker} onChange={(e) => updateGroup('account', 'broker', e.target.value)}><option>MetaTrader 5</option><option>Paper broker</option></select></Field><Field label="Mode"><select value={settings.account.mode} onChange={(e) => updateGroup('account', 'mode', e.target.value)}><option value="paper">Paper trading</option><option value="live">Live trading</option></select></Field></FormSection>}{tab === 'Risiko' && <FormSection title="Batas risiko" description="Nilai persentase diteruskan ke RiskEngine sebagai pecahan desimal."><Field label="Max drawdown (%)"><input type="number" min="0" max="100" value={settings.risk.maxDrawdown} onChange={(e) => updateGroup('risk', 'maxDrawdown', e.target.value)} /></Field><Field label="Daily loss limit (%)"><input type="number" min="0" max="100" value={settings.risk.dailyLoss} onChange={(e) => updateGroup('risk', 'dailyLoss', e.target.value)} /></Field><Field label="Max exposure (%)"><input type="number" min="0" max="100" value={settings.risk.exposure} onChange={(e) => updateGroup('risk', 'exposure', e.target.value)} /></Field><Field label="Max posisi terbuka"><input type="number" min="1" value={settings.risk.maxPositions} onChange={(e) => updateGroup('risk', 'maxPositions', e.target.value)} /></Field></FormSection>}{tab === 'AI' && <FormSection title="AI runtime" description="Kontrol model dan penggunaan token Supervisor."><Field label="Model utama"><select value={settings.ai.model} onChange={(e) => updateGroup('ai', 'model', e.target.value)}><option value="">{modelsState.models.length ? 'Pilih model…' : 'No models available — gateway disconnected'}</option>{modelsState.models.map((m) => <option key={m.id} value={m.id}>{m.id}{m.is_free ? ' · free' : ''}</option>)}</select></Field><Field label="Token budget / request"><input type="number" value={settings.ai.budget} onChange={(e) => updateGroup('ai', 'budget', e.target.value)} /></Field><Field label="Temperature"><input type="number" min="0" max="1" step="0.1" value={settings.ai.temperature} onChange={(e) => updateGroup('ai', 'temperature', e.target.value)} /></Field></FormSection>}{tab === 'Model registry' && <FormSection title="Model registry" description="Model terdaftar dan status kesehatan gateway."><div className={styles.registry}>{modelsState.models.length === 0 ? <div><strong>{modelsState.source === 'live' ? 'Tidak ada model' : 'Gateway tidak tersedia'}</strong><span>{modelsState.source === 'live' ? 'Registry kosong' : 'Python service tidak terjangkau'}</span></div> : modelsState.models.map((m) => <Fragment key={m.id}><div><strong>{m.id}</strong><span>{m.provider}{m.is_free ? ' · free' : ' · premium'}</span></div><span className={`${styles.badge} ${m.is_free ? styles.success : styles.muted}`}>{m.is_free ? 'Gratis' : 'Berbayar'}</span></Fragment>)}</div></FormSection>}{tab === 'Eksekusi' && <FormSection title="Eksekusi order" description="Parameter deterministik sebelum order dikirim ke MT5."><Field label="Venue"><select value={settings.execution.venue} onChange={(e) => updateGroup('execution', 'venue', e.target.value)}><option>MT5</option><option>Paper broker</option></select></Field><Field label="Max slippage (poin)"><input type="number" value={settings.execution.slippage} onChange={(e) => updateGroup('execution', 'slippage', e.target.value)} /></Field><Field label="Timeout order (detik)"><input type="number" value={settings.execution.timeout} onChange={(e) => updateGroup('execution', 'timeout', e.target.value)} /></Field><Toggle label="Paper execution" checked={settings.execution.paper} onChange={(value) => updateGroup('execution', 'paper', value)} /></FormSection>}{tab === 'Notifikasi' && <FormSection title="Notifikasi" description="Pilih event yang dikirim ke kanal terhubung."><Toggle label="Email ringkasan harian" checked={settings.notifications.email} onChange={(value) => updateGroup('notifications', 'email', value)} /><Toggle label="Telegram trade alert" checked={settings.notifications.telegram} onChange={(value) => updateGroup('notifications', 'telegram', value)} /><Toggle label="Risk breach" checked={settings.notifications.risk} onChange={(value) => updateGroup('notifications', 'risk', value)} /><Toggle label="Research selesai" checked={settings.notifications.research} onChange={(value) => updateGroup('notifications', 'research', value)} /></FormSection>}{tab === 'Safety' && <FormSection title="Safety controls" description="Kontrol ini menghentikan jalur eksekusi. Perubahan dicatat pada audit log."><div className={styles.dangerBox}><strong>Zona keselamatan</strong><p>Aktifkan kill switch untuk memblokir order baru. Emergency stop membatalkan proses eksekusi aktif.</p><Toggle label="Kill switch — blokir order baru" checked={settings.safety.killSwitch} onChange={(value) => updateGroup('safety', 'killSwitch', value)} danger /><Toggle label="Emergency stop" checked={settings.safety.emergencyStop} onChange={(value) => updateGroup('safety', 'emergencyStop', value)} danger /></div></FormSection>}<div className={styles.formFooter}><span>Perubahan lokal tersinkron saat disimpan.</span><button className={styles.primary} type="submit">Simpan pengaturan</button></div></form></div>; }

function FormSection({ title, description, children }: { title: string; description: string; children: React.ReactNode }) { return <section className={styles.formCard}><div className={styles.formTitle}><h2>{title}</h2><p>{description}</p></div><div className={styles.formGrid}>{children}</div></section>; }
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className={styles.field}><span>{label}</span>{children}</label>; }
function Toggle({ label, checked, onChange, danger = false }: { label: string; checked: boolean; onChange: (value: boolean) => void; danger?: boolean }) { return <label className={`${styles.toggle} ${danger ? styles.toggleDanger : ''}`}><span>{label}</span><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} /><i /></label>; }
