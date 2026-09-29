'use client';

import { useCallback, useState } from 'react';
import AppShell from '@/components/AppShell';
import { DataTable } from '@/components/ui/data-table';
import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { LoadingState } from '@/components/ui/loading-state';
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
    <AppShell activeKey="orders" eyebrow="Xynn / Order" title="Order" actions={null}>
      {error ? (
        <ErrorState title="Gagal memuat order" description={error} onRetry={load} />
      ) : (
        <Card title="Order" description="Order pending di broker" noPadding>
          {!loaded ? (
            <div className="p-4">
              <LoadingState rows={5} />
            </div>
          ) : rows.length === 0 ? (
            <EmptyState
              title="Tidak ada order pending"
              description="Entry pasar dieksekusi langsung, jadi daftar ini biasanya kosong kecuali Anda memasang order pending (limit/stop)."
            />
          ) : (
            <DataTable columns={columns} rows={rows} unitLabel="order" />
          )}
        </Card>
      )}
    </AppShell>
  );
}
