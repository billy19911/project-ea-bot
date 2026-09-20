'use client';
import AppShell from '@/components/AppShell';
import { DataTable } from '@/components/ui/data-table';
import { Card } from '@/components/ui/card';

// Dummy positions data
const rows = [
  { symbol: 'EURUSD', qty: 100000, pnl: 12.5, updated: '2026-09-20T12:34:00Z' },
  { symbol: 'GBPJPY', qty: -50000, pnl: -8.2, updated: '2026-09-20T12:35:00Z' },
];

const columns = [
  { header: 'Symbol', accessor: (r: any) => r.symbol },
  { header: 'Qty', accessor: (r: any) => r.qty },
  { header: 'PnL', accessor: (r: any) => r.pnl },
  { header: 'Updated', accessor: (r: any) => new Date(r.updated).toLocaleTimeString() },
];

export default function PositionsPage() {
  return (
    <AppShell activeKey="positions" eyebrow="Xynn / Positions" title="Positions" actions={null}>
      <Card title="Open Positions" description="Current open positions">
        <DataTable columns={columns} rows={rows} />
      </Card>
    </AppShell>
  );
}
