import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ReactNode, useEffect, useState } from 'react';
import { apiFetch, getAuthToken } from '../lib/api';
import { cn } from '../lib/utils';
// Inline SVG Icon component defined later
import { StatusIndicator, type UiStatus } from './ui/status-indicator';
import { EnvironmentBadge, type Environment } from './ui/environment-badge';
import { RealtimeIndicator, type RealtimeStatus } from './ui/realtime-indicator';
import { CommandPalette } from './ui/command-palette';
import { ThemeToggle } from './ui/theme-toggle';
import styles from './AppShell.module.css';

type NavKey = string;
type IconName = 'grid' | 'activity' | 'cpu' | 'trend' | 'flask' | 'candles' | 'sliders';

type AccountMode = 'LIVE' | 'DEMO' | 'CONTEST';

type TerminalState = { label: string; running: boolean; armed: boolean };
type AccountState = { login: number | null; server: string; mode: AccountMode | null };

function mapTradeMode(raw: unknown): AccountMode | null {
  if (typeof raw !== 'string') return null;
  const value = raw.toUpperCase();
  if (value.includes('LIVE') || value.includes('REAL')) return 'LIVE';
  if (value.includes('DEMO')) return 'DEMO';
  if (value.includes('CONTEST')) return 'CONTEST';
  return null;
}

const NAV_GROUPS = [
  {
    label: 'Operasional',
    items: [
      { key: 'control-plane', label: 'Control Plane', href: '/control-plane', icon: 'grid' },
      { key: 'market', label: 'Market', href: '/market', icon: 'candles' },
      { key: 'observability', label: 'Observability', href: '/observability', icon: 'activity' },
      { key: 'news', label: 'News', href: '/news', icon: 'candles' },
      { key: 'circuit-breaker', label: 'Circuit Breaker', href: '/circuit-breaker', icon: 'activity' },
      { key: 'incidents', label: 'Incidents', href: '/incidents', icon: 'activity' },
      { key: 'execution-quality', label: 'Execution Quality', href: '/execution-quality', icon: 'trend' },
      { key: 'slo', label: 'System SLO', href: '/slo', icon: 'activity' },
    ],
  },
  {
    label: 'AI',
    items: [
      { key: 'ai-control', label: 'AI Control', href: '/ai-control', icon: 'cpu' },
      { key: 'models', label: 'Models', href: '/models', icon: 'cpu' },
      { key: 'strategy', label: 'Strategy', href: '/strategy', icon: 'trend' },
    ],
  },
  {
    label: 'Research',
    items: [{ key: 'research', label: 'Research', href: '/research', icon: 'flask' }],
  },
  {
    label: 'System',
    items: [
      { key: 'overview', label: 'Overview', href: '/', icon: 'grid' },
      { key: 'environment', label: 'Environment', href: '/environment', icon: 'sliders' },
      { key: 'accounts', label: 'Accounts', href: '/accounts', icon: 'grid' },
      { key: 'certification', label: 'Certification', href: '/certification', icon: 'grid' },
      { key: 'system-readiness', label: 'System Readiness', href: '/system-readiness', icon: 'grid' },
      { key: 'settings', label: 'Settings', href: '/settings', icon: 'sliders' },
    ],
  },
];

type IconProps = { name: IconName };
function Icon({ name }: any) {
  // Reuse inline SVG definitions from the original AppShell file.
  // For brevity we keep the same paths.
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
      {name === 'candles' && (
        <>
          <path d="M7 4v3M7 17v3M17 4v3M17 15v5" />
          <rect x="4.5" y="7" width="5" height="10" rx="0.8" />
          <rect x="14.5" y="9" width="5" height="6" rx="0.8" />
        </>
      )}
    </svg>
  );
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
  const [signedIn, setSignedIn] = useState(false);
  const [realtime, setRealtime] = useState<RealtimeStatus>('OFFLINE');
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === 'undefined') return false;
    try {
      const val = localStorage.getItem('sidebar-collapsed');
      return val === 'true';
    } catch {
      return false;
    }
  });

  // Persist collapsed state
  useEffect(() => {
    try {
      localStorage.setItem('sidebar-collapsed', collapsed.toString());
    } catch {}
  }, [collapsed]);

  // Toggle button (placed in topbar actions)
  const toggleSidebar = () => setCollapsed(c => !c);


  const signOut = () => {
    try {
      localStorage.removeItem('ea-bot-token');
    } catch {}
    setSignedIn(false);
    setTerminal(null);
    setAccount(null);
    setNeedsToken(true);
    setRealtime('OFFLINE');
  };

  // Fetch MT5 terminal & account info – read‑only, no state mutation.
  useEffect(() => {
    setSignedIn(Boolean(getAuthToken()));
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch('/mt5/terminals');
        if (res.status === 401) {
          if (!cancelled) setNeedsToken(true);
          return;
        }
        if (res.ok) {
          const data = await res.json();
          const list: Record<string, unknown>[] = Array.isArray(data?.terminals) ? data.terminals : [];
          const selected = list.find(t => t?.selected) ?? list[0];
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
      } catch {}
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
      } catch {}
    })();
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  // Mock realtime status changes – in production hook to websocket.
  useEffect(() => {
    // Simple demo: flip LIVE every 12s, otherwise DEGRADED.
    const interval = setInterval(() => {
      setRealtime(prev => (prev === 'LIVE' ? 'DEGRADED' : 'LIVE'));
    }, 12000);
    return () => clearInterval(interval);
  }, []);

  // Helper: map trade mode to badge enum.
  function toEnvironment(mode: AccountMode | null | undefined): Environment {
  switch (mode) {
    case 'LIVE':
      return 'PRODUCTION';
    case 'DEMO':
      return 'DEMO';
    case 'CONTEST':
      return 'PAPER';
    default:
      return 'UNKNOWN';
  }
}

// MT5 trade_mode: 0 = DEMO, 1 = CONTEST, 2 = REAL. Nilai lain (mis. simulasi
// "FULL") sengaja dipetakan ke null agar badge tidak menyesatkan.


  // Keyboard shortcut for command palette.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        setPaletteOpen(o => !o);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  return (
    <div className={styles.shell} data-collapsed={collapsed}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <span className={styles.brandMark}>EA</span>
          <div>
            <strong>EA BOT</strong>
            <small>TRADING COMMAND</small>
          </div>
        </div>

        <nav className={styles.nav}>
          {NAV_GROUPS.map(group => (
            <div key={group.label} className={styles.navGroup}>
              <div className={styles.navLabel}>{group.label}</div>
              {group.items.map(item => (
                <Link
                  key={item.key}
                  href={item.href}
                  className={`${styles.navItem} ${activeKey === item.key ? styles.navActive : ''}`}
                  aria-current={activeKey === item.key ? 'page' : undefined}
                >
                  <Icon name={item.icon as IconName} />
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
                <StatusIndicator
                  status={terminal.running ? ('RUNNING' as UiStatus) : ('OFFLINE' as UiStatus)}
                  hideDot={false}
                />
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
                    <EnvironmentBadge
                      environment={account.mode as Environment}
                      className={styles.modeBadge}
                    />
                  )}
                </div>
              ) : (
                <div className={styles.accountHint}>Account info unavailable.</div>
              )}
            </div>
          ) : needsToken ? (
            <div className={styles.accountHint}>
              <Link href="/login" className={styles.loginLink}>
                Sign in to view MT5 account →
              </Link>
            </div>
          ) : terminalKnown ? (
            <div className={styles.accountHint}>MT5 not detected.</div>
          ) : (
            <div className={styles.accountHint}>MT5 status unavailable.</div>
          )}

          {signedIn && (
            <button type="button" className={styles.logoutBtn} onClick={signOut}>
              Sign out
            </button>
          )}
          <button
            type="button"
            className={cn(styles.logoutBtn, 'ml-2')}
            onClick={toggleSidebar}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? '→' : '←'}
          </button>
          {/* Realtime indicator always visible at bottom */}
          <div className={styles.accountHint}>
            <RealtimeIndicator status={realtime} />
          </div>
        </div>
      </aside>

      <main className={styles.main}>
        <header className={styles.topbar}>
          <div>
            <div className={styles.eyebrow}>{eyebrow}</div>
            <h1>{title}</h1>
          </div>
          <div className={styles.actions}>
            {actions}
            <ThemeToggle />
            {/* Environment badge for the whole app */}
            <EnvironmentBadge environment={toEnvironment(account?.mode)} />
          </div>
        </header>
        {children}
      </main>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}
