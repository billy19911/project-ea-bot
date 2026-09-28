'use client';

import { useCallback, useState } from 'react';
import { useAutoRefresh } from '@/lib/useAutoRefresh';
import AppShell from '@/components/AppShell';
import { apiFetch } from '@/lib/api';
import styles from '@/components/ops.module.css';

type Broker = { broker_id: string; name: string; server: string };
type Account = {
  account_id: string;
  broker_id: string;
  login: string;
  terminal_id: string;
  symbol_spec_id: string;
  environment: string;
};
type AttachedAccount = {
  login?: number | string;
  server?: string;
  currency?: string;
  trade_mode?: string | number;
  leverage?: number | string;
  terminal_id?: string;
  execution_armed?: boolean;
};
type AccountsData = {
  brokers: Broker[];
  accounts: Account[];
  attached_account?: AttachedAccount | null;
  unavailable?: string;
  source?: string;
};

function tradeModeLabel(mode: unknown): string {
  // MT5 trade_mode: 0 = DEMO, 1 = CONTEST, 2 = REAL.
  if (typeof mode === 'number') return mode === 2 ? 'REAL' : mode === 0 ? 'DEMO' : 'CONTEST';
  const s = String(mode ?? '').toLowerCase();
  if (s.includes('real') || s === '2') return 'REAL';
  if (s.includes('demo') || s === '0') return 'DEMO';
  if (s.includes('contest') || s === '1') return 'CONTEST';
  return mode ? String(mode) : '—';
}

export default function AccountsPage() {
  const [data, setData] = useState<AccountsData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch('/v2/accounts');
      if (!res.ok) {
        setError(res.status === 503 ? 'Python service unavailable.' : `Request failed (${res.status})`);
        return;
      }
      const body = await res.json();
      setData(body.value ?? { brokers: [], accounts: [] });
      setError(null);
    } catch {
      setError('Could not reach the API.');
    }
  }, []);

  useAutoRefresh(load);

  const attached = data?.attached_account ?? null;

  return (
    <AppShell activeKey="accounts" eyebrow="Xynn / Sistem" title="Akun & Broker">
      <div className={styles.wrap}>
        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Attached account</span>
            <span className={styles.cardValue}>{attached?.login ?? '—'}</span>
            <span className={styles.cardHint}>
              {attached ? attached.server ?? 'MT5 live' : data?.unavailable ?? 'belum tersambung'}
            </span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Mode</span>
            <span className={styles.cardValue}>{attached ? tradeModeLabel(attached.trade_mode) : '—'}</span>
            <span className={styles.cardHint}>
              {attached ? `${attached.currency ?? '—'} · leverage ${attached.leverage ?? '—'}` : ''}
            </span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Execution</span>
            <span className={styles.cardValue}>
              {attached == null ? '—' : attached.execution_armed ? 'ARMED' : 'DISARMED'}
            </span>
            <span className={styles.cardHint}>terminal</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Registry</span>
            <span className={styles.cardValue}>{data?.accounts.length ?? 0}</span>
            <span className={styles.cardHint}>multi-account (opsional)</span>
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Registered Accounts</span>
            <button type="button" className={styles.btn} onClick={load}>
              Refresh
            </button>
          </div>
          {data && data.accounts.length > 0 ? (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Broker</th>
                  <th>Login</th>
                  <th>Terminal</th>
                  <th>Symbol Spec</th>
                  <th>Environment</th>
                </tr>
              </thead>
              <tbody>
                {data.accounts.map((a) => (
                  <tr key={a.account_id}>
                    <td className={styles.mono}>{a.account_id}</td>
                    <td>{a.broker_id}</td>
                    <td className={styles.mono}>{a.login}</td>
                    <td className={styles.mono}>{a.terminal_id || '—'}</td>
                    <td className={styles.mono}>{a.symbol_spec_id || '—'}</td>
                    <td>{a.environment}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className={styles.empty}>
              Belum ada akun di registry. Produksi single-broker tidak memerlukan registry
              multi-account — akun MT5 yang terpasang ditampilkan di kartu “Attached account”.
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
