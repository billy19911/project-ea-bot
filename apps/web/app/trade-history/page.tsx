'use client';

import { useCallback, useState } from 'react';
import { useAutoRefresh } from '@/lib/useAutoRefresh';
import AppShell from '@/components/AppShell';
import { DataTable } from '@/components/ui/data-table';
import { apiFetch } from '@/lib/api';
import { errorMessageFor } from '@/lib/useApiData';

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
  { header: 'Time', accessor: (r: Position) => r.time?.replace('T', ' ') ?? '—' },
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
    <AppShell activeKey="trade-history" eyebrow="Xynn / Trade History" title="Positions & Trades">
      {error && <div style={{ marginBottom: 12, color: 'var(--danger)' }}>{error}</div>}
      {loaded && rows.length === 0 && !error ? (
        <p className="text-center text-[var(--text-muted)] py-6">
          No position history yet. Closed trades appear here once the broker
          reports them; if you have not placed a trade, this stays empty.
        </p>
      ) : (
        <DataTable columns={columns} rows={rows} pageSize={25} unitLabel="position" />
      )}
    </AppShell>
  );
}
