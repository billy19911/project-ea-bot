'use client';

import { useEffect, useState } from 'react';
import AppShell from '../../components/AppShell';
import { apiFetch } from '../../lib/api';
import styles from './page.module.css';

export default function SystemReadinessPage() {
  const [components, setComponents] = useState<Array<any>>([]);

  useEffect(() => {
    apiFetch('/certify').then(async res => {
      if (res.ok) {
        const data = await res.json();
        setComponents(data.components || []);
      }
    });
  }, []);

  return (
    <AppShell activeKey="system-readiness" eyebrow="EA BOT / SYSTEM" title="System Readiness">
      <section className={styles.tableWrapper}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Component</th>
              <th>Status</th>
              <th>Version</th>
              <th>Verified</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {components.map((c, i) => (
              <tr key={i}>
                <td>{c.component}</td>
                <td>{c.status}</td>
                <td>{c.version || '-'} </td>
                <td>{c.verified_at?.slice(0, 19).replace('T', ' ')}</td>
                <td>{c.details?.join(', ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </AppShell>
  );
}
