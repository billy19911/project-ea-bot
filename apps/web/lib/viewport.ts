/**
 * viewport — pure logic for how the candlestick window reacts to new data.
 *
 * Flicker fix: previously the PriceChart reset `visibleCount`/`viewEnd`/`hover`
 * whenever the newest bar's time changed — which happens on every auto-refresh
 * (10s) and can happen on a tick, yanking the viewport back and killing hover.
 *
 * The corrected rule: reset ONLY when the data identity changes (symbol /
 * timeframe). Otherwise:
 *  - older bars prepended  → shift the window forward by the prepended count so
 *    the same candles stay on screen (no visual jump);
 *  - new bar(s) appended and the user is at the right edge ("follow latest") →
 *    shift the window forward so it stays anchored to the latest bar;
 *  - appended while the user is browsing history → keep the position exactly.
 */

export type ViewportState = {
  /** Data identity, e.g. `${symbol}/${timeframe}`. */
  key: string;
  /** Total bars in the dataset. */
  n: number;
  /** Number of candles currently on screen. */
  visibleCount: number;
  /** Exclusive index of the right edge of the window. */
  viewEnd: number;
};

export type ViewportIncoming = {
  key: string;
  n: number;
  /** Bars appended at the END (0 when history was prepended). */
  appendCount: number;
};

export function nextViewport(
  prev: ViewportState,
  incoming: ViewportIncoming,
): { visibleCount: number; viewEnd: number } {
  const { n } = incoming;

  if (n <= 0) return { visibleCount: 1, viewEnd: 0 };

  // New dataset (symbol/timeframe/refresh with a different identity): show the
  // latest bars.
  if (prev.key !== incoming.key) {
    return { visibleCount: n, viewEnd: n };
  }

  // Data shrank (e.g. fewer bars requested): clamp to the latest window.
  if (n < prev.n) {
    return { visibleCount: Math.min(prev.visibleCount, n) || n, viewEnd: n };
  }

  const prepended = n - prev.n - incoming.appendCount;

  // Older history prepended: keep the same bars on screen (no jump).
  if (prepended > 0) {
    const visibleCount = Math.min(prev.visibleCount, n);
    const viewEnd = Math.min(prev.viewEnd + prepended, n);
    return { visibleCount, viewEnd };
  }

  // New bar(s) appended.
  if (incoming.appendCount > 0) {
    const atEdge = prev.viewEnd >= prev.n;
    const viewEnd = atEdge ? Math.min(prev.viewEnd + incoming.appendCount, n) : prev.viewEnd;
    return { visibleCount: Math.min(prev.visibleCount, n), viewEnd };
  }

  return { visibleCount: Math.min(prev.visibleCount, n), viewEnd: Math.min(prev.viewEnd, n) };
}
