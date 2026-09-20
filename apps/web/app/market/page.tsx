'use client';
import AppShell from '@/components/AppShell';
import { Card } from '@/components/ui/card';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

// Dummy market data
const data = [
  { time: '09:00', price: 1.1234 },
  { time: '10:00', price: 1.1240 },
  { time: '11:00', price: 1.1225 },
  { time: '12:00', price: 1.1238 },
];

export default function MarketPage() {
  return (
    <AppShell activeKey="market" eyebrow="Xynn / Market" title="Market" actions={null}>
      <Card title="Price Chart" description="Live market price (mock)" >
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={data}>
            <XAxis dataKey="time" />
            <YAxis domain={['dataMin', 'dataMax']} />
            <Tooltip />
            <Line type="monotone" dataKey="price" stroke="#3b82f6" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </Card>
    </AppShell>
  );
}
