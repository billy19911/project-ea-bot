'use client';
import AppShell from '@/components/AppShell';
import { DataTable } from '@/components/ui/data-table';
import { Card } from '@/components/ui/card';

const rows = [
  { time: '2026-09-19 12:30', symbol: 'EURUSD', action: 'BUY', qty: 100000, pnl: 12.5 },
  { time: '2026-09-19 12:45', symbol: 'GBPJPY', action: 'SELL', qty: 50000, pnl: -8.2 },
];

const columns = [
  { header: 'Time', accessor: (r: any) => r.time },
  { header: 'Symbol', accessor: (r: any) => r.symbol },
  { header: 'Action', accessor: (r: any) => r.action },
  { header: 'Qty', accessor: (r: any) => r.qty },
  { header: 'PnL', accessor: (r: any) => r.pnl },
];

export default function TradeHistoryPage() {
  return (
    <AppShell activeKey="trade-history" eyebrow="Xynn / Trade History" title="Trade History" actions={null}>
      <Card title="Trade History" description="Recent trades">
        <DataTable columns={columns} rows={rows} />
      </Card>
    </AppShell>
  );
}
