'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * Toast — umpan balik ringan + aksesibel (aria-live) untuk aksi async.
 *
 * Dipakai secara lokal di halaman (mis. Settings, Control Panel) tanpa perlu
 * provider global. `useToast()` memberi `show(message, kind)` + elemen `<View/>`
 * yang dirender di sudut kanan bawah, auto-hilang.
 */
export type ToastKind = 'ok' | 'error' | 'info';

export interface ToastState {
  text: string;
  kind: ToastKind;
}

const KIND_CLASS: Record<ToastKind, string> = {
  ok: 'border-[var(--success-border)] bg-[var(--success-soft)] text-[var(--success)]',
  error: 'border-[var(--danger-border)] bg-[var(--danger-soft)] text-[var(--danger)]',
  info: 'border-[var(--border-strong)] bg-[var(--surface)] text-[var(--text-secondary)]',
};

export function useToast(timeoutMs = 4200) {
  const [toast, setToast] = React.useState<ToastState | null>(null);
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = React.useCallback(
    (text: string, kind: ToastKind = 'info') => {
      setToast({ text, kind });
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setToast(null), timeoutMs);
    },
    [timeoutMs]
  );

  const clear = React.useCallback(() => setToast(null), []);

  React.useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    []
  );

  const View = React.useCallback(
    () => <ToastView toast={toast} onClose={clear} />,
    [toast, clear]
  );

  return { toast, show, clear, View };
}

export function ToastView({
  toast,
  onClose,
}: {
  toast: ToastState | null;
  onClose: () => void;
}) {
  return (
    <div
      aria-live="polite"
      role="status"
      className="pointer-events-none fixed bottom-5 right-5 z-[120] flex flex-col gap-2"
    >
      {toast && (
        <button
          type="button"
          onClick={onClose}
          className={cn(
            'pointer-events-auto max-w-sm rounded-[var(--r-md)] border px-4 py-3 text-left text-[var(--fs-sm)] font-medium shadow-[var(--shadow-md)]',
            KIND_CLASS[toast.kind]
          )}
        >
          {toast.text}
        </button>
      )}
    </div>
  );
}
