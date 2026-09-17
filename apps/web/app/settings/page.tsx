'use client';

// Halaman Pengaturan (UI/UX F4).
//
// Dipisah dari Research Center agar home hanya punya SATU strip tab. Sebelumnya
// home menampilkan dua baris tab (level-1: Research/Settings + sub-tab), yang
// membuat hierarki membingungkan.
//
// State tetap lokal (localStorage `ea-bot-settings`) — tidak ada API baru.
// Catatan bahasa: label/aksi memakai Indonesia; istilah teknis baku (Token,
// Drawdown, Slippage, Model registry) tetap Inggris.

import Head from 'next/head';
import { FormEvent, Fragment, ReactNode, useEffect, useState } from 'react';
// CSS dipakai bersama dengan home (kelas yang sama: tabs, card, field, toggle).
// Menyalin 545 baris CSS hanya akan membuat dua sumber yang bisa drift.
import styles from '../page.module.css';
import { apiFetch } from '../../lib/api';
import AppShell from '../../components/AppShell';

type SourceState = 'live' | 'unavailable';
type AiModel = { id: string; provider: string; context: number; is_free: boolean; capabilities?: string[] };
type ModelsState = { models: AiModel[]; source: SourceState };
type Settings = {
  account: { name: string; email: string; broker: string; mode: string };
  risk: { maxDrawdown: string; dailyLoss: string; exposure: string; maxPositions: string };
  ai: { model: string; budget: string; temperature: string };
  execution: { venue: string; slippage: string; timeout: string; paper: boolean };
  notifications: { email: boolean; telegram: boolean; risk: boolean; research: boolean };
  safety: { killSwitch: boolean; emergencyStop: boolean };
};

const defaultSettings: Settings = {
  account: { name: '', email: '', broker: 'MetaTrader 5', mode: 'paper' },
  risk: { maxDrawdown: '15', dailyLoss: '5', exposure: '30', maxPositions: '5' },
  ai: { model: '', budget: '12000', temperature: '0.2' },
  execution: { venue: 'MT5', slippage: '2', timeout: '10', paper: true },
  notifications: { email: true, telegram: true, risk: true, research: false },
  safety: { killSwitch: false, emergencyStop: false },
};

function loadSettings(): Settings {
  if (typeof window === 'undefined') return defaultSettings;
  try {
    return { ...defaultSettings, ...JSON.parse(localStorage.getItem('ea-bot-settings') || '{}') };
  } catch {
    return defaultSettings;
  }
}

export default function SettingsPage() {
  const [tab, setTab] = useState('Akun');
  const [settings, setSettings] = useState<Settings>(defaultSettings);
  const [notice, setNotice] = useState('');
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
    return () => {
      cancelled = true;
    };
  }, []);

  const updateGroup = <K extends keyof Settings>(group: K, field: keyof Settings[K], value: string | boolean) =>
    setSettings((current) => ({ ...current, [group]: { ...current[group], [field]: value } }));

  const saveSettings = (event: FormEvent) => {
    event.preventDefault();
    localStorage.setItem('ea-bot-settings', JSON.stringify(settings));
    setNotice('Pengaturan tersimpan di perangkat ini.');
    setTimeout(() => setNotice(''), 2500);
  };

  return (
    <>
      <Head>
        <title>EA Bot — Pengaturan</title>
        <meta name="description" content="Pengaturan workspace EA Bot" />
      </Head>
      <AppShell activeKey="settings" eyebrow="EA BOT / PENGATURAN" title="Pengaturan">
        {notice && <div className={styles.notice}>{notice}</div>}
        <SettingsView
          tab={tab}
          setTab={setTab}
          settings={settings}
          updateGroup={updateGroup}
          saveSettings={saveSettings}
          modelsState={modelsState}
        />
      </AppShell>
    </>
  );
}

function SettingsView({
  tab,
  setTab,
  settings,
  updateGroup,
  saveSettings,
  modelsState,
}: {
  tab: string;
  setTab: (tab: string) => void;
  settings: Settings;
  updateGroup: <K extends keyof Settings>(group: K, field: keyof Settings[K], value: string | boolean) => void;
  saveSettings: (event: FormEvent) => void;
  modelsState: ModelsState;
}) {
  const tabs = ['Akun', 'Risiko', 'AI', 'Model registry', 'Eksekusi', 'Notifikasi', 'Keamanan'];
  return (
    <div className={styles.pageBody}>
      <nav className={styles.tabs} aria-label="Bagian pengaturan">
        {tabs.map((item) => (
          <button key={item} className={tab === item ? styles.tabActive : ''} onClick={() => setTab(item)}>
            {item}
          </button>
        ))}
      </nav>
      <form onSubmit={saveSettings}>
        {tab === 'Akun' && (
          <FormSection title="Akun & koneksi" description="Identitas workspace dan koneksi broker.">
            <Field label="Nama pengguna">
              <input
                placeholder="Nama pengguna"
                value={settings.account.name}
                onChange={(e) => updateGroup('account', 'name', e.target.value)}
              />
            </Field>
            <Field label="Email">
              <input
                type="email"
                placeholder="nama@domain"
                value={settings.account.email}
                onChange={(e) => updateGroup('account', 'email', e.target.value)}
              />
            </Field>
            <Field label="Broker">
              <select
                value={settings.account.broker}
                onChange={(e) => updateGroup('account', 'broker', e.target.value)}
              >
                <option>MetaTrader 5</option>
                <option>Paper broker</option>
              </select>
            </Field>
            <Field label="Mode">
              <select value={settings.account.mode} onChange={(e) => updateGroup('account', 'mode', e.target.value)}>
                <option value="paper">Paper trading</option>
                <option value="live">Live trading</option>
              </select>
            </Field>
          </FormSection>
        )}
        {tab === 'Risiko' && (
          <FormSection
            title="Batas risiko"
            description="Nilai persentase diteruskan ke RiskEngine sebagai pecahan desimal."
          >
            <Field label="Max drawdown (%)">
              <input
                type="number"
                min="0"
                max="100"
                value={settings.risk.maxDrawdown}
                onChange={(e) => updateGroup('risk', 'maxDrawdown', e.target.value)}
              />
            </Field>
            <Field label="Daily loss limit (%)">
              <input
                type="number"
                min="0"
                max="100"
                value={settings.risk.dailyLoss}
                onChange={(e) => updateGroup('risk', 'dailyLoss', e.target.value)}
              />
            </Field>
            <Field label="Max exposure (%)">
              <input
                type="number"
                min="0"
                max="100"
                value={settings.risk.exposure}
                onChange={(e) => updateGroup('risk', 'exposure', e.target.value)}
              />
            </Field>
            <Field label="Max posisi terbuka">
              <input
                type="number"
                min="1"
                value={settings.risk.maxPositions}
                onChange={(e) => updateGroup('risk', 'maxPositions', e.target.value)}
              />
            </Field>
          </FormSection>
        )}
        {tab === 'AI' && (
          <FormSection title="AI runtime" description="Kontrol model dan penggunaan token Supervisor.">
            <Field label="Model utama">
              <select value={settings.ai.model} onChange={(e) => updateGroup('ai', 'model', e.target.value)}>
                <option value="">
                  {modelsState.models.length ? 'Pilih model…' : 'Belum ada model — gateway tidak terhubung'}
                </option>
                {modelsState.models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id}
                    {m.is_free ? ' · gratis' : ''}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Token budget / request">
              <input
                type="number"
                value={settings.ai.budget}
                onChange={(e) => updateGroup('ai', 'budget', e.target.value)}
              />
            </Field>
            <Field label="Temperature">
              <input
                type="number"
                min="0"
                max="1"
                step="0.1"
                value={settings.ai.temperature}
                onChange={(e) => updateGroup('ai', 'temperature', e.target.value)}
              />
            </Field>
          </FormSection>
        )}
        {tab === 'Model registry' && (
          <FormSection title="Model registry" description="Model terdaftar dan status kesehatan gateway.">
            <div className={styles.registry}>
              {modelsState.models.length === 0 ? (
                <div>
                  <strong>{modelsState.source === 'live' ? 'Tidak ada model' : 'Gateway tidak terhubung'}</strong>
                  <span>
                    {modelsState.source === 'live'
                      ? 'Registry kosong — tambahkan model di gateway.'
                      : 'Jalankan token.bat lalu muat ulang halaman.'}
                  </span>
                </div>
              ) : (
                modelsState.models.map((m) => (
                  <Fragment key={m.id}>
                    <div>
                      <strong>{m.id}</strong>
                      <span>
                        {m.provider}
                        {m.is_free ? ' · gratis' : ' · premium'}
                      </span>
                    </div>
                    <span className={`${styles.badge} ${m.is_free ? styles.success : styles.muted}`}>
                      {m.is_free ? 'Gratis' : 'Berbayar'}
                    </span>
                  </Fragment>
                ))
              )}
            </div>
          </FormSection>
        )}
        {tab === 'Eksekusi' && (
          <FormSection
            title="Eksekusi order"
            description="Parameter deterministik sebelum order dikirim ke MT5."
          >
            <Field label="Venue">
              <select
                value={settings.execution.venue}
                onChange={(e) => updateGroup('execution', 'venue', e.target.value)}
              >
                <option>MT5</option>
                <option>Paper broker</option>
              </select>
            </Field>
            <Field label="Max slippage (poin)">
              <input
                type="number"
                value={settings.execution.slippage}
                onChange={(e) => updateGroup('execution', 'slippage', e.target.value)}
              />
            </Field>
            <Field label="Timeout order (detik)">
              <input
                type="number"
                value={settings.execution.timeout}
                onChange={(e) => updateGroup('execution', 'timeout', e.target.value)}
              />
            </Field>
            <Toggle
              label="Paper execution"
              checked={settings.execution.paper}
              onChange={(value) => updateGroup('execution', 'paper', value)}
            />
          </FormSection>
        )}
        {tab === 'Notifikasi' && (
          <FormSection title="Notifikasi" description="Pilih event yang dikirim ke kanal terhubung.">
            <Toggle
              label="Email ringkasan harian"
              checked={settings.notifications.email}
              onChange={(value) => updateGroup('notifications', 'email', value)}
            />
            <Toggle
              label="Telegram trade alert"
              checked={settings.notifications.telegram}
              onChange={(value) => updateGroup('notifications', 'telegram', value)}
            />
            <Toggle
              label="Pelanggaran risiko"
              checked={settings.notifications.risk}
              onChange={(value) => updateGroup('notifications', 'risk', value)}
            />
            <Toggle
              label="Riset selesai"
              checked={settings.notifications.research}
              onChange={(value) => updateGroup('notifications', 'research', value)}
            />
          </FormSection>
        )}
        {tab === 'Keamanan' && (
          <FormSection
            title="Kontrol keamanan"
            description="Kontrol ini menghentikan jalur eksekusi. Perubahan dicatat pada audit log."
          >
            <div className={styles.dangerBox}>
              <strong>Zona keselamatan</strong>
              <p>
                Aktifkan kill switch untuk memblokir order baru. Emergency stop membatalkan proses eksekusi aktif.
              </p>
              <Toggle
                label="Kill switch — blokir order baru"
                checked={settings.safety.killSwitch}
                onChange={(value) => updateGroup('safety', 'killSwitch', value)}
                danger
              />
              <Toggle
                label="Emergency stop"
                checked={settings.safety.emergencyStop}
                onChange={(value) => updateGroup('safety', 'emergencyStop', value)}
                danger
              />
            </div>
          </FormSection>
        )}
        <div className={styles.formFooter}>
          <span>Perubahan lokal tersinkron saat disimpan.</span>
          <button className={styles.primary} type="submit">
            Simpan pengaturan
          </button>
        </div>
      </form>
    </div>
  );
}

function FormSection({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <section className={styles.formCard}>
      <div className={styles.formTitle}>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      <div className={styles.formGrid}>{children}</div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className={styles.field}>
      <span>{label}</span>
      {children}
    </label>
  );
}

function Toggle({
  label,
  checked,
  onChange,
  danger = false,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  danger?: boolean;
}) {
  return (
    <label className={`${styles.toggle} ${danger ? styles.toggleDanger : ''}`}>
      <span>{label}</span>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <i />
    </label>
  );
}
