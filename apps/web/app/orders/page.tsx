'use client';

import { useCallback, useState } from 'react';
import AppShell from '@/components/AppShell';
import { DataTable } from '@/components/ui/data-table';
import { Card } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';
import { useAutoRefresh } from '@/lib/useAutoRefresh';

type Order = {
  ticket: number;
  symbol: string;
  side: string;
  order_type: string;
  price: number;
  stop_price: number | null;
  quantity: number;
  filled_qty: number;
  status: string;
  time_setup: string;
  time_expiration: string | null;
};

const columns = [
  { header: 'Ticket', accessor: (r: Order) => <span className="mono">{r.ticket}</span> },
  { header: 'Time setup', accessor: (r: Order) => new Date(r.time_setup).toLocaleString() },
  { header: 'Symbol', accessor: (r: Order) => r.symbol },
  { header: 'Side', accessor: (r: Order) => <span className={r.side === 'BUY' ? 'trendUp' : 'trendDown'}>{r.side}</span> },
  { header: 'Type', accessor: (r: Order) => r.order_type },
  { header: 'Price', accessor: (r: Order) => <span className="mono">{r.price}</span> },
  { header: 'Qty', accessor: (r: Order) => <span className="mono">{r.quantity}</span> },
  { header: 'Filled', accessor: (r: Order) => <span className="mono">{r.filled_qty}</span> },
  { header: 'Status', accessor: (r: Order) => r.status },
];

export default function OrdersPage() {
  const [rows, setRows] = useState<Order[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch('/orders');
      if (!res.ok) {
        setError(res.status === 503 ? 'Python service unavailable.' : `Request failed (${res.status})`);
        return;
      }
      const data = await res.json();
      setRows(Array.isArray(data.orders) ? data.orders : []);
      setError(null);
    } catch {
      setError('Could not reach the API.');
    } finally {
      setLoaded(true);
    }
  }, []);

  useAutoRefresh(load);

  return (
    <AppShell activeKey="orders" eyebrow="Xynn / Orders" title="Orders" actions={null}>
      {error && <div style={{ marginBottom: 12, color: 'var(--danger)' }}>{error}</div>}
      <Card title="Orders" description="All recent orders">
        <DataTable columns={columns} rows={rows} unitLabel="orders" />
      </Card>
      {!loaded && <p style={{ marginTop: 12 }}>Loading…</p>}
    </AppShell>
  );
}
