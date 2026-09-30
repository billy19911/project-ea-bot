'use client';

// OpsAlertBanner — a single, always-visible system-status strip pinned above
// page content. Answers the operator's first question at a glance:
//   "is anything wrong right now?"
//
// It reads the Phase-7 ops read models (/ops/health + /ops/alerts) through the
// Node API proxy. It NEVER fabricates: when the API is unreachable it says so
// plainly instead of rendering a reassuring green bar.
//
// Design: one hairline row, colour-coded by the worst active severity. Click a
// row to jump to the page that explains it. A muted "all systems nominal" line
// is shown when nothing needs attention — calm is information too.

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';
import styles from './AppShell.module.css';

type Severity = 'CRITICAL' | 'HIGH' | 'WARNING' | 'INFO';

type OpsAlert = {
  category?: string;
  severity?: string;
  message?: string;
};

type HealthComponent = {
  name?: string;
  status?: string;
  last_error?: string;
};

const SEVERITY_RANK: Record<string, number> = {
  CRITICAL: 4,
  HIGH: 3,
  WARNING: 2,
  INFO: 1,
};

/** Where each alert category is best explained, so the banner is actionable. */
const CATEGORY_HREF: Record<string, string> = {
  RECONCILIATION: '/reconciliation',
  EXECUTION: '/execution',
  MARKET_DATA: '/market',
  RISK: '/risk-center',
  RESEARCH: '/research',
  STRATEGY: '/strategy',
  MODEL: '/models',
  BUDGET: '/ai-control',
  SYSTEM: '/system-health',
};

/** Health components that, when not healthy, deserve a top-banner mention. */
const HEALTH_LABEL: Record<string, string> = {
  reconciliation: 'Reconciliation',
  mt5: 'MT5 link',
  engine: 'Trading engine',
  scheduler: 'Scheduler',
  research_queue: 'Research worker',
};

type BannerItem = {
  severity: Severity;
  category: string;
  message: string;
  href?: string;
};

function worstSeverity(items: BannerItem[]): Severity | null {
  let worst: Severity | null = null;
  for (const it of items) {
    if (worst === null || SEVERITY_RANK[it.severity] > SEVERITY_RANK[worst]) {
      worst = it.severity;
    }
  }
  return worst;
}

export function OpsAlertBanner() {
  const [items, setItems] = useState<BannerItem[]>([]);
  const [reachable, setReachable] = useState<boolean | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      const collected: BannerItem[] = [];
      let anyOk = false;

      // 1) Structured alerts (Phase 7 alert evaluator).
      try {
        const res = await apiFetch('/ops/alerts');
        if (res.ok) {
          anyOk = true;
          const body = await res.json();
          const raw: OpsAlert[] = Array.isArray(body?.data?.alerts) ? body.data.alerts : [];
          for (const a of raw) {
            const sev = String(a.severity ?? 'INFO').toUpperCase();
            if (sev === 'INFO') continue; // keep the banner quiet for informational noise
            const category = String(a.category ?? 'SYSTEM');
            collected.push({
              severity: (SEVERITY_RANK[sev] ? sev : 'WARNING') as Severity,
              category,
              message: String(a.message ?? ''),
              href: CATEGORY_HREF[category],
            });
          }
        }
      } catch {
        /* handled by reachable below */
      }

      // 2) Component health — surface non-healthy critical components.
      try {
        const res = await apiFetch('/ops/health');
        if (res.ok) {
          anyOk = true;
          const body = await res.json();
          const comps: HealthComponent[] = Array.isArray(body?.data?.components)
            ? body.data.components
            : [];
          for (const c of comps) {
            const status = String(c.status ?? 'UNKNOWN').toUpperCase();
            if (status === 'HEALTHY') continue;
            const name = String(c.name ?? '');
            const label = HEALTH_LABEL[name];
            if (!label) continue; // only components an operator can act on
            if (name === 'mt5' && status === 'DEGRADED') continue; // simulated mode is expected in dev
            collected.push({
              severity: status === 'FAILED' ? 'CRITICAL' : 'WARNING',
              category: 'SYSTEM',
              message: `${label}: ${status.toLowerCase()}`,
              href: '/system-health',
            });
          }
        }
      } catch {
        /* handled by reachable below */
      }

      if (!cancelled) {
        setReachable(anyOk);
        setItems(collected);
        setLoaded(true);
      }
    };

    void load();
    const interval = setInterval(load, 20000);
    const onVisible = () => {
      if (typeof document !== 'undefined' && !document.hidden) void load();
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
  }, []);

  if (!loaded) return null;

  // API unreachable — say so plainly rather than showing a false all-clear.
  if (reachable === false) {
    return (
      <div className={`${styles.banner} ${styles.bannerCritical}`} role="status">
        <span className={styles.bannerDot} aria-hidden="true" />
        <span className={styles.bannerText}>
          <strong>Control plane unreachable</strong> — status cannot be verified right now.
        </span>
      </div>
    );
  }

  const worst = worstSeverity(items);

  if (worst === null) {
    return (
      <div className={`${styles.banner} ${styles.bannerOk}`} role="status">
        <span className={styles.bannerDot} aria-hidden="true" />
        <span className={styles.bannerText}>All systems nominal</span>
        <span className={styles.bannerMeta}>live health checked</span>
      </div>
    );
  }

  const sevClass =
    worst === 'CRITICAL'
      ? styles.bannerCritical
      : worst === 'HIGH'
        ? styles.bannerHigh
        : styles.bannerWarning;

  const shown = items.slice(0, 3);
  const extra = items.length - shown.length;

  return (
    <div className={`${styles.banner} ${sevClass}`} role="alert">
      <span className={styles.bannerDot} aria-hidden="true" />
      <span className={styles.bannerText}>
        {shown.map((it, i) => (
          <span key={`${it.category}-${i}`}>
            {it.href ? (
              <Link href={it.href} className={styles.bannerLink}>
                {it.message || it.category}
              </Link>
            ) : (
              it.message || it.category
            )}
            {i < shown.length - 1 ? <span className={styles.bannerSep}> · </span> : null}
          </span>
        ))}
        {extra > 0 ? <span className={styles.bannerMeta}>+{extra} more</span> : null}
      </span>
    </div>
  );
}
