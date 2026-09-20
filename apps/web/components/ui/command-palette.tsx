import * as React from 'react';
import { cn } from '@/lib/utils';
import { X } from 'lucide-react';

/**
 * CommandPalette — modal overlay untuk quick navigation (Ctrl/⌘ K).
 * Daftar shortcut (G then O, G then M, …) dikelola di scrollable list.
 */
export interface CommandPaletteProps {
  /** Open state */
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({ open, onOpenChange }) => {
  const ref = React.useRef<HTMLDivElement>(null);

  // Close on Escape
  React.useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onOpenChange(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onOpenChange]);

  // Focus trap (simplified)
  React.useEffect(() => {
    if (open) ref.current?.focus();
  }, [open]);

  if (!open) return null;
  return (
    <div
      ref={ref}
      tabIndex={-1}
      className={cn(
        'fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm',
        'outline-none'
      )}
      onClick={() => onOpenChange(false)}
    >
      <div
        className="w-full max-w-md rounded-xl bg-[var(--surface)] p-4 shadow-[var(--shadow-md)]"
        onClick={e => e.stopPropagation()}
      >
        <h2 className="mb-2 text-sm font-medium text-[var(--text)]">Command Palette</h2>
        {/* Placeholder: simple list of shortcuts */}
        <ul className="space-y-2 text-[var(--text-muted)]">
          <li>G then O – Open Overview</li>
          <li>G then M – Market</li>
          <li>G then P – Positions</li>
          <li>G then R – Risk</li>
          <li>G then S – Strategy Lab</li>
          <li>G then I – Intelligence</li>
        </ul>
        <button
          onClick={() => onOpenChange(false)}
          className={cn('mt-4 inline-flex items-center gap-1.5 text-sm text-[var(--primary)] hover:text-[var(--primary-hover)]')}
        >
          <X className="h-4 w-4" />
          Close
        </button>
      </div>
    </div>
  );
};
