import * as React from 'react';
import { cva, VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

/**
 * Button — base tombol memakai design token proyek (var(--primary) dst).
 *
 * Sebelumnya memakai token Tailwind (bg-primary/ring-ring) yang TIDAK ada di
 * token set proyek sehingga tak ter-style. Versi ini memakai CSS variable yang
 * benar sehingga konsisten dengan seluruh dashboard.
 */
const buttonVariants = cva(
  [
    'inline-flex items-center justify-center gap-2 rounded-[var(--r-sm)]',
    'text-[var(--fs-md)] font-semibold leading-none whitespace-nowrap',
    'border border-transparent cursor-pointer select-none',
    'transition-[background,border-color,color] duration-[var(--dur-fast)] ease-[var(--ease)]',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg)]',
    'disabled:opacity-50 disabled:pointer-events-none',
  ].join(' '),
  {
    variants: {
      variant: {
        default:
          'bg-[var(--primary)] text-[var(--on-primary)] hover:bg-[var(--primary-hover)]',
        outline:
          'border-[var(--border-strong)] bg-[var(--surface)] text-[var(--text-secondary)] hover:bg-[var(--surface-muted)] hover:text-[var(--text)]',
        ghost:
          'bg-transparent text-[var(--text-secondary)] hover:bg-[var(--surface-muted)] hover:text-[var(--text)]',
        danger:
          'bg-[var(--danger)] text-[var(--on-primary)] hover:opacity-90',
      },
      size: {
        sm: 'h-8 px-3 text-[var(--fs-sm)]',
        default: 'h-9 px-4',
        lg: 'h-10 px-5',
        icon: 'h-9 w-9 p-0',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
  )
);
Button.displayName = 'Button';

export { Button, buttonVariants };
