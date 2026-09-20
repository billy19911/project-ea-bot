'use client';

import AppShell from '@/components/AppShell';
import { Card } from '@/components/ui/card';
import { MetricGroup, Metric } from '@/components/ui/metric';
import { StatusIndicator } from '@/components/ui/status-indicator';
import { RealtimeIndicator } from '@/components/ui/realtime-indicator';
import { EnvironmentBadge } from '@/components/ui/environment-badge';
import { DataFreshness } from '@/components/ui/data-freshness';
import { cn } from '@/lib/utils';

export default function OverviewPage() {
  // Placeholder data – replace with real API calls later (F10).
  const systemStatus: 'HEALTHY' = 'HEALTHY';
  const decisionStatus: 'RUNNING' = 'RUNNING';
  const realtime: 'LIVE' = 'LIVE';

  return (
    <AppShell
      activeKey="control-plane"
      eyebrow="Xynn / Overview"
      title="Command Center Overview"
      actions={<EnvironmentBadge environment="PRODUCTION" />}
    >
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <Card title="System Health" description="Overall system status">
          <div className="flex items-center gap-2">
            <StatusIndicator status={systemStatus} />
            <span className="text-sm text-[var(--text-muted)]">All services operational</span>
          </div>
        </Card>
        <Card title="Active Decision" description="Current AI decision engine">
          <StatusIndicator status={decisionStatus} />
        </Card>
        <Card title="Realtime" description="Broker connection">
          <RealtimeIndicator status={realtime} />
        </Card>
        <Card title="Key Metrics" description="Trading KPIs">
          <MetricGroup columns={3}>
            <Metric label="PnL / unit" value={null} tone="muted" />
            <Metric label="Win rate" value={null} tone="muted" />
            <Metric label="Sharpe" value={null} tone="muted" />
          </MetricGroup>
        </Card>
        <Card title="Data Freshness" description="Last update timestamps">
          <DataFreshness updatedAt={null} />
        </Card>
        <Card title="Risk Summary" description="Current exposure">
          <p className="text-[var(--text-muted)]">—</p>
        </Card>
      </div>
    </AppShell>
  );
}
