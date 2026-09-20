import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * cn — gabungkan className, resolve konflik Tailwind dengan twMerge.
 * Dipakai oleh seluruh primitive di components/ui/*.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
