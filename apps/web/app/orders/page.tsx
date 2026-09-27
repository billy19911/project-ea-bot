'use client';

import { useCallback, useState } from 'react';
import AppShell from '@/components/AppShell';
import { DataTable } from '@/components/ui/data-table';
import { Card } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';
import { errorMessageFor, fmtDateTime } from '@/lib/useApiData';
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
  { header: 'Time setup', accessor: (r: Order) => fmtDateTime(r.time_setup) },
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
        setError(errorMessageFor(res.status));
        return;
      }
      const data = await res.json();
      setRows(Array.isArray(data.orders) ? data.orders : []);
      setError(null);
    } catch {
      setError(errorMessageFor(0));
    } finally {
      setLoaded(true);
    }
  }, []);

  useAutoRefresh(load);

  return (
    <AppShell activeKey="orders" eyebrow="Xynn / Orders" title="Orders" actions={null}>
      {error && <div style={{ marginBottom: 12, color: 'var(--danger)' }}>{error}</div>}
      <Card title="Orders" description="Pending orders at the broker">
        {loaded && rows.length === 0 && !error ? (
          <p className="text-center text-[var(--text-muted)] py-6">
            No pending orders. Market entries execute immediately, so this list is
            usually empty unless you placed pending (limit/stop) orders.
          </p>
        ) : (
          <DataTable columns={columns} rows={rows} unitLabel="order" />
        )}
      </Card>
    </AppShell>
  );
}
