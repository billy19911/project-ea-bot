'use client';
import AppShell from '@/components/AppShell';
import { DataTable } from '@/components/ui/data-table';
import { Card } from '@/components/ui/card';

const rows = [
  { id: 'ORD-1', symbol: 'EURUSD', side: 'BUY', qty: 100000, status: 'FILLED' },
  { id: 'ORD-2', symbol: 'GBPJPY', side: 'SELL', qty: 50000, status: 'PENDING' },
];

const columns = [
  { header: 'Order ID', accessor: (r: any) => r.id },
  { header: 'Symbol', accessor: (r: any) => r.symbol },
  { header: 'Side', accessor: (r: any) => r.side },
  { header: 'Qty', accessor: (r: any) => r.qty },
  { header: 'Status', accessor: (r: any) => r.status },
];

export default function OrdersPage() {
  return (
    <AppShell activeKey="orders" eyebrow="Xynn / Orders" title="Orders" actions={null}>
      <Card title="Orders" description="All recent orders">
        <DataTable columns={columns} rows={rows} />
      </Card>
    </AppShell>
  );
}
