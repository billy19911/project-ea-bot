'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { cn } from '@/lib/utils';
import { Search } from 'lucide-react';

/**
 * CommandPalette — modal overlay untuk quick navigation (Ctrl/⌘ K).
 *
 * Menampilkan daftar halaman yang bisa difilter lewat keyboard. `Enter`
 * membuka item terpilih, `↑`/`↓` memindah seleksi, `Esc` menutup.
 */
export interface CommandPaletteItem {
  key: string;
  label: string;
  href: string;
  /** Optional group label (mis. "Risk & Ops"). */
  group?: string;
}

export interface CommandPaletteProps {
  /** Open state */
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Navigable items (biasanya diturunkan dari NAV_GROUPS). */
  items: CommandPaletteItem[];
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({ open, onOpenChange, items }) => {
  const router = useRouter();
  const ref = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const listRef = React.useRef<HTMLUListElement>(null);
  const [query, setQuery] = React.useState('');
  const [activeIndex, setActiveIndex] = React.useState(0);

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(item => {
      const haystack = `${item.label} ${item.group ?? ''} ${item.href}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [items, query]);

  // Reset query + selection whenever the palette is (re)opened.
  React.useEffect(() => {
    if (open) {
      setQuery('');
      setActiveIndex(0);
      // Focus the input on the next frame so the modal is mounted.
      const id = window.setTimeout(() => inputRef.current?.focus(), 0);
      return () => window.clearTimeout(id);
    }
  }, [open]);

  // Clamp the active index whenever the filtered list shrinks.
  React.useEffect(() => {
    setActiveIndex(current => (current >= filtered.length ? 0 : current));
  }, [filtered.length]);

  const go = React.useCallback(
    (href: string) => {
      onOpenChange(false);
      router.push(href);
    },
    [onOpenChange, router]
  );

  // Keyboard handling: Esc closes, arrows move, Enter navigates.
  React.useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onOpenChange(false);
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActiveIndex(i => (filtered.length ? (i + 1) % filtered.length : 0));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActiveIndex(i => (filtered.length ? (i - 1 + filtered.length) % filtered.length : 0));
      } else if (e.key === 'Enter') {
        const target = filtered[activeIndex];
        if (target) {
          e.preventDefault();
          go(target.href);
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, filtered, activeIndex, go, onOpenChange]);

  // Keep the active item scrolled into view.
  React.useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-index="${activeIndex}"]`);
    el?.scrollIntoView({ block: 'nearest' });
  }, [activeIndex]);

  if (!open) return null;

  return (
    <div
      className={cn(
        'fixed inset-0 z-50 flex items-start justify-center bg-black/50 backdrop-blur-sm pt-[15vh]',
        'outline-none'
      )}
      onClick={() => onOpenChange(false)}
    >
      <div
        ref={ref}
        className="w-full max-w-md rounded-xl bg-[var(--surface)] p-4 shadow-[var(--shadow-md)]"
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
      >
        <div className="mb-3 flex items-center gap-2 border-b border-[var(--border)] pb-2">
          <Search className="h-4 w-4 text-[var(--text-muted)]" />
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Cari halaman…"
            aria-label="Cari halaman"
            className="w-full bg-transparent text-sm text-[var(--text)] outline-none placeholder:text-[var(--text-muted)]"
          />
        </div>

        {filtered.length === 0 ? (
          <p className="py-4 text-center text-sm text-[var(--text-muted)]">
            Tidak ada halaman yang cocok.
          </p>
        ) : (
          <ul ref={listRef} className="max-h-72 space-y-0.5 overflow-y-auto">
            {filtered.map((item, index) => (
              <li key={item.key} data-index={index}>
                <button
                  type="button"
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => go(item.href)}
                  className={cn(
                    'flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm',
                    index === activeIndex
                      ? 'bg-[var(--surface-muted)] text-[var(--text)]'
                      : 'text-[var(--text-muted)] hover:bg-[var(--surface-muted)]'
                  )}
                >
                  <span>{item.label}</span>
                  {item.group && (
                    <span className="text-[10px] uppercase tracking-wide opacity-60">
                      {item.group}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-3 flex items-center justify-between text-[10px] text-[var(--text-muted)]">
          <span>↑↓ pindah · Enter buka · Esc tutup</span>
          <span>Ctrl/⌘ K</span>
        </div>
      </div>
    </div>
  );
};
