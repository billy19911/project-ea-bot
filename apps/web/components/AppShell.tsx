'use client';

// AppShell — kerangka tunggal untuk seluruh halaman dashboard (UI/UX F2).
//
// Menggantikan lima sidebar + header yang sebelumnya diduplikasi di tiap
// halaman (home, control-plane, ai-control, strategy, observability).
//
// Kontrak:
//   activeKey : item navigasi yang disorot (satu per halaman).
//   eyebrow   : label kecil di atas judul, mis. "EA BOT / CONTROL PLANE".
//   title     : judul halaman (h1).
//   actions   : slot tombol kontekstual di kanan header.
//   children  : isi halaman.
//
// Footer sidebar menampilkan terminal MT5 terpilih + mode akun (DEMO/LIVE)
// secara READ-ONLY. Shell ini tidak pernah mengubah state eksekusi — arming
// hanya lewat panel terminal di Control Plane.

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ReactNode, useEffect, useState } from 'react';
import { apiFetch, getAuthToken } from '../lib/api';
import styles from './AppShell.module.css';

type NavKey = 'control-plane' | 'observability' | 'ai-control' | 'strategy' | 'research' | 'settings' | 'login';
type IconName = 'grid' | 'activity' | 'cpu' | 'trend' | 'flask' | 'sliders' | 'key';
type AccountMode = 'LIVE' | 'DEMO' | 'CONTEST';

type TerminalState = { label: string; running: boolean; armed: boolean };
type AccountState = { login: number | null; server: string; mode: AccountMode | null };

const NAV_GROUPS: { label: string; items: { key: NavKey; label: string; href: string; icon: IconName }[] }[] = [
  {
    label: 'Operasional',
    items: [
      { key: 'control-plane', label: 'Control Plane', href: '/control-plane', icon: 'grid' },
      { key: 'observability', label: 'Observability', href: '/observability', icon: 'activity' },
    ],
  },
  {
    label: 'AI',
    items: [
      { key: 'ai-control', label: 'Kontrol AI', href: '/ai-control', icon: 'cpu' },
      { key: 'strategy', label: 'Strategi', href: '/strategy', icon: 'trend' },
    ],
  },
  {
    label: 'Riset',
    items: [{ key: 'research', label: 'Pusat Riset', href: '/', icon: 'flask' }],
  },
  {
    label: 'Sistem',
    items: [
      { key: 'settings', label: 'Pengaturan', href: '/settings', icon: 'sliders' },
      { key: 'login', label: 'Masuk', href: '/login', icon: 'key' },
    ],
  },
];

function Icon({ name }: { name: IconName }) {
  return (
    <svg
      className={styles.icon}
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {name === 'grid' && <path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z" />}
      {name === 'activity' && <path d="M22 12h-4l-3 9L9 3l-3 9H2" />}
      {name === 'cpu' && (
        <>
          <rect x="4" y="4" width="16" height="16" rx="2" />
          <rect x="9" y="9" width="6" height="6" />
          <path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3" />
        </>
      )}
      {name === 'trend' && (
        <>
          <path d="M22 7l-8.5 8.5-5-5L2 17" />
          <path d="M16 7h6v6" />
        </>
      )}
      {name === 'flask' && (
        <>
          <path d="M10 2v7.5a2 2 0 0 1-.2.9L4.7 20.6a1 1 0 0 0 .9 1.4h12.8a1 1 0 0 0 .9-1.4L14.2 10.4a2 2 0 0 1-.2-.9V2" />
          <path d="M8.5 2h7M7 16h10" />
        </>
      )}
      {name === 'sliders' && (
        <>
          <path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3" />
          <path d="M1 14h6M9 8h6M17 16h6" />
        </>
      )}
      {name === 'key' && (
        <>
          <circle cx="7.5" cy="15.5" r="4.5" />
          <path d="M10.7 12.3L21 2M15 7l3 3M18 4l3 3" />
        </>
      )}
    </svg>
  );
}

// MT5 trade_mode: 0 = DEMO, 1 = CONTEST, 2 = REAL. Nilai lain (mis. simulasi
// "FULL") sengaja dipetakan ke null agar badge tidak menyesatkan.
function mapTradeMode(raw: unknown): AccountMode | null {
  const value = String(raw ?? '').toUpperCase();
  if (value === '2' || value.includes('REAL') || value.includes('LIVE')) return 'LIVE';
  if (value === '1' || value.includes('CONTEST')) return 'CONTEST';
  if (value === '0' || value.includes('DEMO')) return 'DEMO';
  return null;
}

export default function AppShell({
  activeKey,
  eyebrow,
  title,
  actions,
  children,
}: {
  activeKey: NavKey;
  eyebrow: string;
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const [terminal, setTerminal] = useState<TerminalState | null>(null);
  const [terminalKnown, setTerminalKnown] = useState(false);
  const [account, setAccount] = useState<AccountState | null>(null);
  const [needsToken, setNeedsToken] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // Read-only: daftar terminal + info akun. Keduanya di belakang auth
      // middleware; tanpa token responsnya 401 — itu dibedakan dari "tidak
      // terdeteksi" agar pesan footer tidak menyesatkan.
      try {
        const res = await apiFetch('/mt5/terminals');
        if (res.status === 401) {
          if (!cancelled) setNeedsToken(true);
          return;
        }
        if (res.ok) {
          const data = await res.json();
          const list: Record<string, unknown>[] = Array.isArray(data?.terminals) ? data.terminals : [];
          const selected = list.find((t) => t?.selected === true) ?? list[0];
          if (!cancelled) {
            setTerminalKnown(true);
            if (selected) {
              setTerminal({
                label: String(selected.label ?? selected.id ?? 'MT5'),
                running: selected.running === true,
                armed: data?.execution_armed === true,
              });
            } else {
              setTerminal(null);
            }
          }
        }
      } catch {
        // Biarkan terminalKnown=false — shell tidak boleh mengarang status.
      }

      if (!getAuthToken()) return;
      try {
        const res = await apiFetch('/mt5/accounts/info');
        if (res.ok) {
          const data = await res.json();
          if (!cancelled) {
            setAccount({
              login: typeof data?.login === 'number' ? data.login : null,
              server: typeof data?.server === 'string' ? data.server : '',
              mode: mapTradeMode(data?.trade_mode),
            });
          }
        }
      } catch {
        // Info akun opsional — footer tetap tampil tanpa meta akun.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <span className={styles.brandMark}>EA</span>
          <div>
            <strong>EA BOT</strong>
            <small>TRADING CONTROL</small>
          </div>
        </div>

        <nav className={styles.nav}>
          {NAV_GROUPS.map((group) => (
            <div key={group.label} className={styles.navGroup}>
              <div className={styles.navLabel}>{group.label}</div>
              {group.items.map((item) => (
                <Link
                  key={item.key}
                  href={item.href}
                  className={`${styles.navItem} ${activeKey === item.key ? styles.navActive : ''}`}
                  aria-current={activeKey === item.key ? 'page' : undefined}
                >
                  <Icon name={item.icon} />
                  <span>{item.label}</span>
                </Link>
              ))}
            </div>
          ))}
        </nav>

        <div className={styles.footer}>
          {terminal ? (
            <div className={styles.account}>
              <div className={styles.accountTop}>
                <span className={`${styles.dot} ${terminal.running ? styles.dotOn : styles.dotOff}`} />
                <span className={styles.accountName}>MT5 · {terminal.label}</span>
                {terminal.armed && <span className={styles.armed}>ARMED</span>}
              </div>
              {account ? (
                <div className={styles.accountMeta}>
                  <span title={`${account.login !== null ? `${account.login} · ` : ''}${account.server}`}>
                    {account.login !== null ? `${account.login} · ` : ''}
                    {account.server}
                  </span>
                  {account.mode && (
                    <span
                      className={`${styles.modeBadge} ${
                        account.mode === 'LIVE' ? styles.modeLive : styles.modeDemo
                      }`}
                    >
                      {account.mode}
                    </span>
                  )}
                </div>
              ) : (
                <div className={styles.accountHint}>Info akun tidak tersedia.</div>
              )}
            </div>
          ) : needsToken ? (
            <div className={styles.accountHint}>
              <Link href="/login" className={styles.loginLink}>
                Masuk untuk melihat akun MT5 →
              </Link>
            </div>
          ) : terminalKnown ? (
            <div className={styles.accountHint}>MT5 tidak terdeteksi.</div>
          ) : (
            <div className={styles.accountHint}>Status MT5 tidak tersedia.</div>
          )}
        </div>
      </aside>

      <main className={styles.main}>
        <header className={styles.topbar}>
          <div>
            <div className={styles.eyebrow}>{eyebrow}</div>
            <h1>{title}</h1>
          </div>
          {actions && <div className={styles.actions}>{actions}</div>}
        </header>
        {children}
      </main>
    </div>
  );
}
