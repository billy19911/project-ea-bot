'use client';

import { useCallback, useEffect, useState } from 'react';
import AppShell from '@/components/AppShell';
import { DataTable } from '@/components/ui/data-table';
import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { LoadingState } from '@/components/ui/loading-state';
import { apiFetch } from '@/lib/api';
import { errorMessageFor, fmtDateTime } from '@/lib/useApiData';
import { useAutoRefresh } from '@/lib/useAutoRefresh';

type Position = {
  ticket: number;
  symbol: string;
  side: string;
  quantity: number;
  price_open: number;
  price_current: number;
  profit: number;
  sl: number | null;
  tp: number | null;
  status: string;
  time: string;
};

const columns = [
  { header: 'Ticket', accessor: (r: Position) => <span className="mono">{r.ticket}</span> },
  { header: 'Time', accessor: (r: Position) => fmtDateTime(r.time) },
  { header: 'Symbol', accessor: (r: Position) => r.symbol },
  { header: 'Side', accessor: (r: Position) => <span className={r.side === 'BUY' ? 'trendUp' : 'trendDown'}>{r.side}</span> },
  { header: 'Qty', accessor: (r: Position) => <span className="mono">{r.quantity}</span> },
  { header: 'Open', accessor: (r: Position) => <span className="mono">{r.price_open}</span> },
  { header: 'Current', accessor: (r: Position) => <span className="mono">{r.price_current}</span> },
  { header: 'PnL', accessor: (r: Position) => <span className={`mono ${r.profit >= 0 ? 'trendUp' : 'trendDown'}`}>{r.profit >= 0 ? '+' : ''}{r.profit}</span> },
  { header: 'SL', accessor: (r: Position) => r.sl ?? '—' },
  { header: 'TP', accessor: (r: Position) => r.tp ?? '—' },
  { header: 'Status', accessor: (r: Position) => r.status },
];

export default function PositionsPage() {
  const [rows, setRows] = useState<Position[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [mode, setMode] = useState<'PAPER' | 'LIVE'>('PAPER');

  const loadInfo = useCallback(async () => {
    try {
      const res = await apiFetch('/mt5/mode');
      if (!res.ok) return;
      const data = await res.json();
      setMode(data.live_data === true ? 'LIVE' : 'PAPER');
    } catch {}
  }, []);

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

  useAutoRefresh(load, 10_000);

  // Load mode once on mount
  useEffect(() => {
    loadInfo();
  }, [loadInfo]);

  return (
    <AppShell activeKey="positions" eyebrow="Xynn / Posisi" title="Posisi Terbuka" actions={null}>
      {error && <ErrorState title="Gagal memuat posisi" description={error} onRetry={load} />}

      <Card title="Info Posisi" description={`Mode MT5: ${mode} • Status Data Live`} noPadding>
        <div className="px-4 py-2 text-sm">
          <div className="flex gap-3 text-[var(--text-muted)]">
            <span>Status:</span>
            <span className={mode === 'LIVE' ? 'trendUp' : 'mono'}>
              {mode === 'LIVE' ? 'Data broker live terpasang' : 'Sesi paper / simulasi'}
            </span>
          </div>
        </div>
      </Card>

      <div style={{ height: 'var(--sp-4)' }} />

      <Card title="Posisi Terbuka" description={`${rows.length} posisi sedang terbuka`} noPadding>
        {!loaded ? (
          <div className="p-4">
            <LoadingState rows={5} />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            title="Belum ada posisi terbuka"
            description={
              mode === 'LIVE'
                ? 'Periksa tab Broker atau pasang order manual.'
                : 'Akun paper dalam mode simulasi; tidak ada posisi nyata.'
            }
          />
        ) : (
          <DataTable columns={columns} rows={rows} unitLabel="posisi" />
        )}
      </Card>
    </AppShell>
  );
}
