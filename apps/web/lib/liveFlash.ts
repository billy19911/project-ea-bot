/**
 * liveFlash — decided whether a live value should visually flash.
 *
 * Flicker fix: the market page ticks every ~2.5s (WebSocket) and auto-refreshes
 * every ~10s. Flashing on EVERY change — including sub-cent noise — makes the
 * numbers "kedip-kedip". We only flash when the change is *meaningful* relative
 * to the previous value (default: >= 0.05%).
 */
export function shouldFlash(prev: number, next: number, minRelDelta = 0.0005): boolean {
  if (!Number.isFinite(prev) || !Number.isFinite(next) || prev === next) return false;
  // Relative to |prev|; when prev is 0 fall back to 1 so the metric is an
  // absolute delta (a sub-cent move from 0 stays quiet, a real move flashes).
  const base = Math.abs(prev) || 1;
  return Math.abs(next - prev) / base >= minRelDelta;
}
