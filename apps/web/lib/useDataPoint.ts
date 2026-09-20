'use client';
import { useEffect, useState } from 'react';
import { apiFetchTyped } from './api';

/**
 * useDataPoint – fetches a typed endpoint respecting PRD data contract.
 * Returns { data, status, updatedAt, source, loading, error }.
 */
export function useDataPoint<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [status, setStatus] = useState<string>('');
  const [updatedAt, setUpdatedAt] = useState<string>('');
  const [source, setSource] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiFetchTyped<T>(path)
      .then(res => {
        if (cancelled) return;
        setData(res.value);
        setStatus(res.status);
        setUpdatedAt(res.updated_at);
        setSource(res.source);
        setError('');
      })
      .catch(err => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  return { data, status, updatedAt, source, loading, error };
}
