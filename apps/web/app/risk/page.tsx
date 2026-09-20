'use client';
import AppShell from '@/components/AppShell';
import { RiskBadge } from '@/components/ui/risk-badge';

export default function RiskPage() {
  return (
    <AppShell
      activeKey="overview"
      eyebrow="Xynn / Risk"
      title="Risk Center"
      actions={<RiskBadge level="UNKNOWN" />}
    >
      <div className="grid gap-4">
        <section className="p-4 bg-[var(--surface-muted)] rounded-md">
          <h2 className="text-lg font-semibold mb-2">Circuit Breaker</h2>
          <RiskBadge level="UNKNOWN" />
        </section>
        <section className="p-4 bg-[var(--surface-muted)] rounded-md">
          <h2 className="text-lg font-semibold mb-2">Reconciliation</h2>
          <RiskBadge level="UNKNOWN" />
        </section>
      </div>
    </AppShell>
  );
}
