import * as React from 'react';

/**
 * Ikon SVG inline untuk halaman Agen — menggantikan emoji sebagai ikon
 * (UX rule: no emoji as icons; pakai SVG, satu keluarga visual, aria-hidden
 * untuk dekoratif). Satu keluarga stroke 1.8px agar konsisten.
 */

type IconName =
  | 'brain'
  | 'puzzle'
  | 'chat'
  | 'clock'
  | 'users'
  | 'book'
  | 'ticket'
  | 'scan'
  | 'warning'
  | 'ban';

const PATHS: Record<IconName, React.ReactNode> = {
  brain: (
    <>
      <path d="M9 3a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 4 3 3 0 0 0 3 3 2 2 0 0 0 2-2V5a2 2 0 0 0-2-2z" />
      <path d="M15 3a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 4 3 3 0 0 1-3 3 2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" />
    </>
  ),
  puzzle: (
    <path d="M19.4 7.5a2 2 0 0 0-1-3.5 2 2 0 0 0-2 2H14V4a2 2 0 1 0-4 0v.5H7.5a2 2 0 0 0-2 2V9H5a2 2 0 1 0 0 4h.5v2.5a2 2 0 0 0 2 2H10v.5a2 2 0 1 0 4 0V17h2.5a2 2 0 0 0 2-2v-2.5H19a2 2 0 0 0 1.5-3.3" />
  ),
  chat: <path d="M21 11.5a8.4 8.4 0 0 1-9 8 9 9 0 0 1-4-.9L3 20l1.4-4A8.4 8.4 0 0 1 12 3.5a8.4 8.4 0 0 1 9 8z" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  users: (
    <>
      <path d="M17 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9.5" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
    </>
  ),
  book: (
    <>
      <path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v18H6.5A2.5 2.5 0 0 0 4 22z" />
      <path d="M4 4.5A2.5 2.5 0 0 0 6.5 7H20" />
    </>
  ),
  ticket: (
    <>
      <path d="M3 8a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2 2 2 0 0 0 0 4 2 2 0 0 1-2 2H5a2 2 0 0 1-2-2 2 2 0 0 0 0-4z" />
      <path d="M13 6v12" />
    </>
  ),
  scan: (
    <>
      <path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2" />
      <path d="M3 12h18" />
    </>
  ),
  warning: (
    <>
      <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
      <path d="M12 9v4M12 17h.01" />
    </>
  ),
  ban: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M5.6 5.6l12.8 12.8" />
    </>
  ),
};

export function AgentIcon({
  name,
  size = 16,
  className,
}: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
      style={{ flexShrink: 0 }}
    >
      {PATHS[name]}
    </svg>
  );
}

export type { IconName as AgentIconName };
