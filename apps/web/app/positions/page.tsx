'use client';

import { useCallback, useState } from 'react';
import AppShell from '@/components/AppShell';
import { DataTable } from '@/components/ui/data-table';
import { Card } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';
import { useAutoRefresh } from '@/lib/useAutoRefresh';

type Position = {
  ticket: number;
  symbol: string;
  side: string;
  quantity: number;
  price_open: number;
  price_current: number;
  profit: number;
  sl: number | null;
  tp: number | null;
  status: string;
  time: string;
};

const columns = [
  { header: 'Ticket', accessor: (r: Position) => <span className="mono">{r.ticket}</span> },
  { header: 'Time', accessor: (r: Position) => new Date(r.time).toLocaleString() },
  { header: 'Symbol', accessor: (r: Position) => r.symbol },
  { header: 'Side', accessor: (r: Position) => <span className={r.side === 'BUY' ? 'trendUp' : 'trendDown'}>{r.side}</span> },
  { header: 'Qty', accessor: (r: Position) => <span className="mono">{r.quantity}</span> },
  { header: 'Open', accessor: (r: Position) => <span className="mono">{r.price_open}</span> },
  { header: 'Current', accessor: (r: Position) => <span className="mono">{r.price_current}</span> },
  { header: 'PnL', accessor: (r: Position) => <span className={`mono ${r.profit >= 0 ? 'trendUp' : 'trendDown'}`}>{r.profit >= 0 ? '+' : ''}{r.profit}</span> },
  { header: 'SL', accessor: (r: Position) => r.sl ?? '—' },
  { header: 'TP', accessor: (r: Position) => r.tp ?? '—' },
  { header: 'Status', accessor: (r: Position) => r.status },
];

export default function PositionsPage() {
  const [rows, setRows] = useState<Position[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch('/positions');
      if (!res.ok) {
        setError(res.status === 503 ? 'Python service unavailable.' : `Request failed (${res.status})`);
        return;
      }
      const data = await res.json();
      setRows(Array.isArray(data.positions) ? data.positions : []);
      setError(null);
    } catch {
      setError('Could not reach the API.');
    } finally {
      setLoaded(true);
    }
  }, []);

  useAutoRefresh(load);

  return (
    <AppShell activeKey="positions" eyebrow="Xynn / Positions" title="Positions" actions={null}>
      {error && <div style={{ marginBottom: 12, color: 'var(--danger)' }}>{error}</div>}
      <Card title="Open Positions" description="Current open positions">
        <DataTable columns={columns} rows={rows} unitLabel="positions" />
      </Card>
      {!loaded && <p style={{ marginTop: 12 }}>Loading…</p>}
    </AppShell>
  );
}
