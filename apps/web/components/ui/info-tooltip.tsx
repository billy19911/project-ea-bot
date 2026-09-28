'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * InfoTooltip — ikon kecil "i" yang menampilkan penjelasan saat hover/focus.
 *
 * Dipakai untuk menjelaskan fungsi knob/field teknis (mis.
 * `supervisor_token_budget`) tanpa memenuhi layar. Menggunakan atribut `title`
 * native + `aria-label` sehingga tetap aksesibel (dapat difokus lewat keyboard,
 * dibaca screen reader) dan tidak menambah dependency baru.
 */
export interface InfoTooltipProps {
  /** Teks penjelasan yang muncul di tooltip. */
  text: string;
  /** Label aksesibel untuk pembaca layar (default: "Informasi"). */
  label?: string;
  className?: string;
}

export function InfoTooltip({ text, label = 'Informasi', className }: InfoTooltipProps) {
  if (!text) return null;
  const describedById = React.useId();
  return (
    <span className={cn('inline-flex items-center align-middle', className)}>
      <span
        tabIndex={0}
        role="img"
        aria-label={label}
        aria-describedby={describedById}
        title={text}
        className={cn(
          'inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full',
          'border border-[var(--border)] text-[10px] font-semibold leading-none',
          'text-[var(--text-muted)] transition-colors',
          'hover:border-[var(--accent)] hover:text-[var(--accent)]',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]'
        )}
      >
        i
      </span>
      <span id={describedById} className="sr-only">
        {text}
      </span>
    </span>
  );
}

export default InfoTooltip;
