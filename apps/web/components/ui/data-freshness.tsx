import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * DataFreshness — menampilkan timestamp terakhir update.
 * PRD §114: "Updated 0.8s ago". Jika data belum ada, tampilkan "—".
 */
export interface DataFreshnessProps {
  updatedAt: string | Date | null;
  /** Teks alternatif bila tidak ada timestamp. */
  placeholder?: string;
  className?: string;
}

export const DataFreshness: React.FC<DataFreshnessProps> = ({
  updatedAt,
  placeholder = '—',
  className,
}) => {
  const [text, setText] = React.useState<string>(placeholder);

  React.useEffect(() => {
    if (!updatedAt) {
      setText(placeholder);
      return;
    }
    const ts = typeof updatedAt === 'string' ? new Date(updatedAt) : updatedAt;
    const fmt = () => {
      const diff = Date.now() - ts.getTime();
      if (diff < 1000) return 'just now';
      const secs = Math.round(diff / 1000);
      if (secs < 60) return `${secs}s ago`;
      const mins = Math.round(secs / 60);
      if (mins < 60) return `${mins}m ago`;
      const hrs = Math.round(mins / 60);
      return `${hrs}h ago`;
    };
    setText(fmt());
    const id = setInterval(() => setText(fmt()), 5000);
    return () => clearInterval(id);
  }, [updatedAt, placeholder]);

  return (
    <span className={cn('text-xs text-[var(--text-muted)]', className)}>{text}</span>
  );
};
