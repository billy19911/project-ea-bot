import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { apiFetch, getAuthToken } from '../lib/api';
// Inline SVG Icon component defined later
import { StatusIndicator, type UiStatus } from './ui/status-indicator';
import { EnvironmentBadge, type Environment } from './ui/environment-badge';
import { RealtimeIndicator, type RealtimeStatus } from './ui/realtime-indicator';
import { CommandPalette } from './ui/command-palette';
import { OpsAlertBanner } from './OpsAlertBanner';
import { ThemeToggle } from './ui/theme-toggle';
import styles from './AppShell.module.css';

type NavKey = string;

type AccountMode = 'LIVE' | 'DEMO' | 'CONTEST';

type TerminalState = { label: string; running: boolean; armed: boolean };
type AccountState = { login: number | null; server: string; mode: AccountMode | null };

function mapTradeMode(raw: unknown): AccountMode | null {
  // MetaTrader5 ACCOUNT_TRADE_MODE enum (returned by the connector as a string):
  //   0 = DEMO, 1 = CONTEST, 2 = REAL (a.k.a. LIVE).
  // Some surfaces instead pass a human string ("DEMO"/"LIVE"/"REAL"); handle both
  // so the environment badge can never be stuck on UNKNOWN.
  const numeric = typeof raw === 'number' ? String(raw) : typeof raw === 'string' ? raw.trim() : '';
  if (numeric === '0') return 'DEMO';
  if (numeric === '1') return 'CONTEST';
  if (numeric === '2') return 'LIVE';

  if (typeof raw !== 'string') return null;
  const value = raw.toUpperCase();
  if (value.includes('LIVE') || value.includes('REAL')) return 'LIVE';
  if (value.includes('DEMO')) return 'DEMO';
  if (value.includes('CONTEST')) return 'CONTEST';
  return null;
}

const NAV_GROUPS = [
  {
    label: 'Daily Flow',
    shortcut: true,
    items: [
      { key: 'overview', label: 'Overview', href: '/', icon: 'gauge' },
      { key: 'market', label: 'Market', href: '/market', icon: 'candles' },
      { key: 'why-no-trade', label: 'Why No Trade', href: '/why-no-trade', icon: 'alert' },
      { key: 'risk-center', label: 'Risk Center', href: '/risk-center', icon: 'shield' },
      { key: 'execution', label: 'Execution', href: '/execution', icon: 'activity' },
      { key: 'positions', label: 'Positions', href: '/positions', icon: 'activity' },
    ],
  },
  {
    label: 'Command',
    items: [
      { key: 'overview', label: 'Overview', href: '/', icon: 'gauge' },
      { key: 'control-plane', label: 'Control Panel', href: '/control-plane', icon: 'grid' },
      { key: 'market', label: 'Market', href: '/market', icon: 'candles' },
      { key: 'news', label: 'News', href: '/news', icon: 'news' },
    ],
  },
  {
    label: 'Trading',
    items: [
      { key: 'orders', label: 'Orders', href: '/orders', icon: 'bolt' },
      { key: 'positions', label: 'Positions', href: '/positions', icon: 'activity' },
      { key: 'trade-history', label: 'Trade History', href: '/trade-history', icon: 'clock' },
    ],
  },
  {
    label: 'Decisions',
    items: [
      { key: 'decisions', label: 'Decisions', href: '/decisions', icon: 'bolt' },
      { key: 'decision-replay', label: 'Decision Replay', href: '/decision-replay', icon: 'clock' },
      { key: 'why-no-trade', label: 'Why No Trade', href: '/why-no-trade', icon: 'alert' },
      { key: 'execution', label: 'Execution', href: '/execution', icon: 'activity' },
    ],
  },
  {
    label: 'Risk & Ops',
    items: [
      { key: 'risk-center', label: 'Risk Center', href: '/risk-center', icon: 'shield' },
      { key: 'circuit-breaker', label: 'Circuit Breaker', href: '/circuit-breaker', icon: 'shield' },
      { key: 'incidents', label: 'Incidents', href: '/incidents', icon: 'alert' },
      { key: 'execution-quality', label: 'Execution Quality', href: '/execution-quality', icon: 'bolt' },
      { key: 'reconciliation', label: 'Reconciliation', href: '/reconciliation', icon: 'grid' },
      { key: 'observability', label: 'Observability', href: '/observability', icon: 'activity' },
      { key: 'slo', label: 'System SLO', href: '/slo', icon: 'clock' },
    ],
  },
  {
    label: 'Intelligence',
    items: [
      { key: 'ai-control', label: 'AI Control', href: '/ai-control', icon: 'cpu' },
      { key: 'agents', label: 'Agents', href: '/agents', icon: 'users' },
      { key: 'models', label: 'Models', href: '/models', icon: 'layers' },
      { key: 'strategy', label: 'Strategy', href: '/strategy', icon: 'trend' },
      { key: 'strategy-lab', label: 'Strategy Lab', href: '/strategy-lab', icon: 'flask' },
      { key: 'backtest', label: 'Backtest', href: '/backtest', icon: 'activity' },
      { key: 'learning', label: 'Learning', href: '/learning', icon: 'cpu' },
      { key: 'performance', label: 'Performance', href: '/performance', icon: 'trend' },
    ],
  },
  {
    label: 'Research',
    items: [
      { key: 'research', label: 'Research', href: '/research', icon: 'flask' },
      { key: 'walk-forward', label: 'Walk-Forward', href: '/walk-forward', icon: 'trend' },
      { key: 'monte-carlo', label: 'Monte Carlo', href: '/monte-carlo', icon: 'activity' },
    ],
  },
  {
    label: 'System',
    items: [
      { key: 'environment', label: 'Environment', href: '/environment', icon: 'server' },
      { key: 'system-health', label: 'System Health', href: '/system-health', icon: 'gauge' },
      { key: 'accounts', label: 'Accounts', href: '/accounts', icon: 'layers' },
      { key: 'certification', label: 'Certification', href: '/certification', icon: 'check-badge' },
      { key: 'audit', label: 'Audit Trail', href: '/audit', icon: 'clock' },
      { key: 'system-readiness', label: 'Readiness', href: '/system-readiness', icon: 'shield' },
      { key: 'settings', label: 'Settings', href: '/settings', icon: 'sliders' },
    ],
  },
];

/**
 * Flat list of navigable pages for the command palette (Ctrl/⌘ K), derived
 * from NAV_GROUPS so the two can never drift apart. Shortcut groups (Daily
 * Flow) are excluded here because their items already appear in the main
 * navigation groups.
 */
const COMMAND_ITEMS = NAV_GROUPS.filter(g => !(g as { shortcut?: boolean }).shortcut).flatMap(
  group =>
    group.items.map(item => ({
      key: item.key,
      label: item.label,
      href: item.href,
      group: group.label,
    }))
);

type IconProps = { name: string };
function Icon({ name }: IconProps) {
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
      {name === 'gauge' && (
        <>
          <path d="M12 14l4-4" />
          <path d="M3.5 18a9 9 0 1 1 17 0" />
          <circle cx="12" cy="14" r="1" />
        </>
      )}
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
      {name === 'shield' && (
        <>
          <path d="M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6z" />
          <path d="M9 12l2 2 4-4" />
        </>
      )}
      {name === 'bolt' && <path d="M13 2L3 14h7l-1 8 10-12h-7z" />}
      {name === 'alert' && (
        <>
          <path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
          <path d="M12 9v4M12 17h.01" />
        </>
      )}
      {name === 'clock' && (
        <>
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 2" />
        </>
      )}
      {name === 'server' && (
        <>
          <rect x="2" y="3" width="20" height="7" rx="1.5" />
          <rect x="2" y="14" width="20" height="7" rx="1.5" />
          <path d="M6 6.5h.01M6 17.5h.01" />
        </>
      )}
      {name === 'layers' && (
        <>
          <path d="M12 2l9 5-9 5-9-5z" />
          <path d="M3 12l9 5 9-5M3 17l9 5 9-5" />
        </>
      )}
      {name === 'check-badge' && (
        <>
          <path d="M12 2l2.4 1.8 3-.2 1 2.8 2.6 1.5-1 2.9 1 2.9-2.6 1.5-1 2.8-3-.2L12 22l-2.4-1.8-3 .2-1-2.8L3 16.1l1-2.9-1-2.9 2.6-1.5 1-2.8 3 .2z" />
          <path d="M9 12l2 2 4-4" />
        </>
      )}
      {name === 'news' && (
        <>
          <path d="M4 5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" />
          <path d="M8 7h8M8 11h8M8 15h5" />
        </>
      )}
      {name === 'users' && (
        <>
          <path d="M17 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2" />
          <path d="M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z" />
          <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
          <path d="M16 3.13a4 4 0 0 1 0 7.75" />
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
  const router = useRouter();
  const [terminal, setTerminal] = useState<TerminalState | null>(null);
  const [terminalKnown, setTerminalKnown] = useState(false);
  const [account, setAccount] = useState<AccountState | null>(null);
  const [needsToken, setNeedsToken] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [realtime, setRealtime] = useState<RealtimeStatus>('OFFLINE');
  const [paletteOpen, setPaletteOpen] = useState(false);
  // Always start expanded so the first client render matches the server HTML.
  // Reading localStorage in the initializer made the client's first render
  // differ from the server (hydration mismatch: server renders
  // `data-collapsed="false"` while the client rendered `true`). The persisted
  // value is applied after mount, in the effect below.
  const [collapsed, setCollapsed] = useState(false);
  const [collapsedReady, setCollapsedReady] = useState(false);
  // Mobile drawer state (independent from desktop collapse).
  const [drawerOpen, setDrawerOpen] = useState(false);
  // Ref to the active nav link so the sidebar can scroll it into view.
  const activeLinkRef = useRef<HTMLAnchorElement | null>(null);

  // Accordion nav: only ONE group is open at a time (the one holding the active
  // page by default), so the sidebar stays compact. The operator can open a
  // different group; clicking the open one closes it.
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [groupTouched, setGroupTouched] = useState(false);
  // Inline menu filter — faster than the palette for mouse users, and it keeps
  // the 40+ item catalogue searchable without leaving the sidebar.
  const [navFilter, setNavFilter] = useState('');

  // The group that contains the currently active page.
  const activeGroupLabel = useMemo(
    () => NAV_GROUPS.find(g => g.items.some(it => it.key === activeKey))?.label ?? null,
    [activeKey],
  );

  // Which group is open: the operator's explicit choice once they touch it,
  // otherwise the group of the active page.
  const effectiveOpenGroup = groupTouched ? openGroup : activeGroupLabel;

  // Whenever the route changes, follow the active group again (unless the
  // operator is mid-navigation inside their chosen group — safe to reset).
  useEffect(() => {
    setGroupTouched(false);
    setOpenGroup(null);
  }, [pathname]);

  const toggleGroup = (label: string) => {
    setGroupTouched(true);
    setOpenGroup(prev => (prev === label ? null : label));
  };

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  // Client-side auth guard: if a protected page is visited with no token in
  // localStorage, send the user to /login (preserving the attempted path).
  // This runs after mount (localStorage is unavailable during SSR). It is a
  // UX guard only — data is still protected server-side by the JWT check.
  useEffect(() => {
    if (pathname === '/login') return;
    if (!getAuthToken()) {
      router.replace(`/login?next=${encodeURIComponent(pathname || '/')}`);
    }
  }, [pathname, router]);

  // Apply the persisted collapse state after mount (hydration-safe), then
  // persist subsequent changes. Guarded by collapsedReady so the initial
  // `false` default can never overwrite the stored value.
  useEffect(() => {
    try {
      const val = localStorage.getItem('sidebar-collapsed');
      if (val !== null) setCollapsed(val === 'true');
    } catch {}
    setCollapsedReady(true);
  }, []);

  useEffect(() => {
    if (!collapsedReady) return;
    try {
      localStorage.setItem('sidebar-collapsed', collapsed.toString());
    } catch {}
  }, [collapsed, collapsedReady]);

  // Keep the active nav item visible: with 36 items the active one is often
  // below the fold, forcing a manual scroll. Scroll it to the centre whenever
  // the route changes (mirrors the command palette's behaviour).
  useEffect(() => {
    const el = activeLinkRef.current;
    if (!el) return;
    try {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    } catch {
      // Older engines: ignore.
    }
  }, [pathname]);

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

  // Realtime status driven by a REAL health poll (no mock). Maps the API's
  // reachability + status to the badge: reachable+ok → LIVE, reachable but not
  // ok → DEGRADED, unreachable → OFFLINE. Polls every 15s and on focus.
  useEffect(() => {
    let cancelled = false;
    let inFlight = false;

    const poll = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const res = await apiFetch('/health');
        if (cancelled) return;
        if (!res.ok) {
          setRealtime('DEGRADED');
          return;
        }
        let ok = true;
        try {
          const data = await res.json();
          // The Node API reports health as "healthy" (see /health in
          // apps/api/src/index.ts) — not "ok". Accept any known-healthy value so
          // a healthy service never reads as DEGRADED; anything explicitly
          // unhealthy ("degraded"/"down"/"unhealthy"/"error") is DEGRADED.
          const status = String(data?.status ?? 'healthy').toLowerCase();
          ok = ['ok', 'healthy', 'up'].includes(status);
        } catch {
          ok = true; // reachable but non-JSON — still online
        }
        setRealtime(ok ? 'LIVE' : 'DEGRADED');
      } catch {
        if (!cancelled) setRealtime('OFFLINE');
      } finally {
        inFlight = false;
      }
    };

    void poll();
    const interval = setInterval(poll, 15000);
    const onVisible = () => {
      if (typeof document !== 'undefined' && !document.hidden) void poll();
    };
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', onVisible);
    }
    return () => {
      cancelled = true;
      clearInterval(interval);
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', onVisible);
      }
    };
  }, [pathname]);

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
      {/* Mobile scrim — tap to close the drawer. */}
      <div
        className={`${styles.scrim} ${drawerOpen ? styles.scrimOpen : ''}`}
        onClick={() => setDrawerOpen(false)}
        aria-hidden="true"
      />
      <aside className={`${styles.sidebar} ${drawerOpen ? styles.sidebarOpen : ''}`}>
        <div className={styles.brand}>
          <span className={styles.brandMark}>EA</span>
          <div className={styles.brandText}>
            <strong>EA BOT</strong>
            <small>TRADING COMMAND</small>
          </div>
          <button
            type="button"
            className={styles.collapseBtn}
            onClick={toggleSidebar}
            title={collapsed ? 'Perluas sidebar' : 'Perkecil sidebar'}
            aria-label={collapsed ? 'Perluas sidebar' : 'Perkecil sidebar'}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              {collapsed ? <path d="M9 18l6-6-6-6" /> : <path d="M15 18l-6-6 6-6" />}
            </svg>
          </button>
          <button
            type="button"
            className={styles.drawerClose}
            onClick={() => setDrawerOpen(false)}
            aria-label="Close menu"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        {!collapsed && (
          <div className={styles.navSearchWrap}>
            <svg
              className={styles.navSearchIcon}
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <circle cx="11" cy="11" r="7" />
              <path d="M21 21l-4.3-4.3" />
            </svg>
            <input
              type="search"
              className={styles.navSearch}
              placeholder="Filter menu…"
              value={navFilter}
              onChange={e => setNavFilter(e.target.value)}
              aria-label="Filter menu"
            />
          </div>
        )}

        <nav className={styles.nav}>
          {NAV_GROUPS.map(group => {
            // While a filter is typed, flatten the match across all groups so
            // the operator finds any page from one input — no expanding needed.
            const q = navFilter.trim().toLowerCase();
            const searching = q.length > 0;
            const visibleItems = searching
              ? group.items.filter(it => it.label.toLowerCase().includes(q))
              : group.items;
            if (searching && visibleItems.length === 0) return null;
            // A search forces groups open; otherwise the accordion rule applies.
            const open = searching || effectiveOpenGroup === group.label;
            const groupHasActive = group.items.some(it => it.key === activeKey);
            const isShortcut = Boolean((group as { shortcut?: boolean }).shortcut);
            return (
              <div key={group.label} className={styles.navGroup}>
                <button
                  type="button"
                  className={`${styles.navLabel} ${groupHasActive ? styles.navLabelActive : ''} ${isShortcut ? styles.navLabelShortcut : ''}`}
                  aria-expanded={open}
                  onClick={() => toggleGroup(group.label)}
                >
                  <span>{group.label}</span>
                  <svg
                    className={`${styles.navChevron} ${open ? styles.navChevronOpen : ''}`}
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path d="M6 9l6 6 6-6" />
                  </svg>
                </button>
                {/* Always rendered so the open/close can animate smoothly
                    (grid-template-rows 0fr→1fr). */}
                <div className={`${styles.navItemsWrap} ${open ? styles.navItemsOpen : ''}`}>
                  <div className={styles.navItemsInner}>
                    <div className={styles.navItems}>
                      {visibleItems.map(item => {
                        const isActive = activeKey === item.key;
                        return (
                          <Link
                            key={`${group.label}-${item.key}`}
                            href={item.href}
                            ref={isActive ? activeLinkRef : undefined}
                            className={`${styles.navItem} ${isActive ? styles.navActive : ''}`}
                            aria-current={isActive ? 'page' : undefined}
                            title={collapsed ? item.label : undefined}
                            onClick={() => setDrawerOpen(false)}
                          >
                            <Icon name={item.icon} />
                            <span className={styles.navItemText}>{item.label}</span>
                          </Link>
                        );
                      })}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
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
          {/* Realtime indicator always visible at bottom */}
          <div className={styles.accountHint}>
            <RealtimeIndicator status={realtime} />
          </div>
        </div>
      </aside>

      <main className={styles.main}>
        <OpsAlertBanner />
        <header className={styles.topbar}>
          <button
            type="button"
            className={styles.menuBtn}
            onClick={() => setDrawerOpen(true)}
            aria-label="Open menu"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <path d="M3 6h18M3 12h18M3 18h18" />
            </svg>
          </button>
          <div className={styles.topbarText}>
            <div className={styles.eyebrow}>{eyebrow}</div>
            <h1>{title}</h1>
          </div>
          <div className={styles.actions}>
            {/* Page-supplied controls stay in the row and wrap together with the
             * global theme toggle + environment badge — never hidden (invariant
             * 23: critical status must remain visible at every width). */}
            <span className={styles.pageActions}>{actions}</span>
            <ThemeToggle />
            <EnvironmentBadge environment={toEnvironment(account?.mode)} />
          </div>
        </header>
        {children}
      </main>
      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        items={COMMAND_ITEMS}
      />
    </div>
  );
}
