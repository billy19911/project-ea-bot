'use client';

import { useCallback, useState } from 'react';
import { useAutoRefresh } from '@/lib/useAutoRefresh';
import AppShell from '@/components/AppShell';
import { DataTable } from '@/components/ui/data-table';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { LoadingState } from '@/components/ui/loading-state';
import { apiFetch } from '@/lib/api';
import { errorMessageFor, fmtDateTime } from '@/lib/useApiData';

type Position = {
  ticket: number;
  symbol: string;
  side: string;
  quantity: number;
  price_open: number;
  price_current: number;
  profit: number;
  status: string;
  time: string;
};

const columns = [
  {
    header: 'Ticket',
    accessor: (r: Position) => <span className="mono">{r.ticket}</span>,
  },
  { header: 'Time', accessor: (r: Position) => fmtDateTime(r.time) },
  { header: 'Symbol', accessor: (r: Position) => r.symbol },
  {
    header: 'Side',
    accessor: (r: Position) => (
      <span className={r.side === 'BUY' ? 'trendUp' : 'trendDown'}>{r.side}</span>
    ),
  },
  { header: 'Qty', accessor: (r: Position) => <span className="mono">{r.quantity}</span> },
  {
    header: 'Open',
    accessor: (r: Position) => <span className="mono">{r.price_open}</span>,
  },
  {
    header: 'Current',
    accessor: (r: Position) => <span className="mono">{r.price_current}</span>,
  },
  {
    header: 'PnL',
    accessor: (r: Position) => (
      <span className={`mono ${r.profit >= 0 ? 'trendUp' : 'trendDown'}`}>
        {r.profit >= 0 ? '+' : ''}
        {r.profit}
      </span>
    ),
  },
  { header: 'Status', accessor: (r: Position) => r.status },
];

export default function TradeHistoryPage() {
  const [rows, setRows] = useState<Position[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch('/positions');
      if (!res.ok) {
        setError(errorMessageFor(res.status));
        return;
      }
      const data = await res.json();
      setRows(Array.isArray(data.positions) ? data.positions : []);
      setError(null);
    } catch {
      setError(errorMessageFor(0));
    } finally {
      setLoaded(true);
    }
  }, []);

  useAutoRefresh(load);

  return (
    <AppShell activeKey="trade-history" eyebrow="Xynn / Transaksi" title="Posisi & Transaksi">
      {error ? (
        <ErrorState title="Gagal memuat riwayat" description={error} onRetry={load} />
      ) : !loaded ? (
        <LoadingState rows={6} />
      ) : rows.length === 0 ? (
        <EmptyState
          title="Belum ada riwayat posisi"
          description="Trade tertutup muncul di sini setelah broker melaporkannya; jika belum ada trade, daftar ini tetap kosong."
        />
      ) : (
        <DataTable columns={columns} rows={rows} pageSize={10} unitLabel="position" />
      )}
    </AppShell>
  );
}
