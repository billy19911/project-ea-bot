'use client';

import { useCallback, useEffect, useState } from 'react';
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
type AccountsData = { brokers: Broker[]; accounts: Account[] };

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

  useEffect(() => {
    load();
  }, [load]);

  return (
    <AppShell activeKey="accounts" eyebrow="Xynn / System" title="Accounts & Brokers">
      <div className={styles.wrap}>
        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Brokers</span>
            <span className={styles.cardValue}>{data?.brokers.length ?? 0}</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Accounts</span>
            <span className={styles.cardValue}>{data?.accounts.length ?? 0}</span>
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
                {data.accounts.map(a => (
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
            <div className={styles.empty}>No accounts registered. Multi-account is optional for single-broker production.</div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
