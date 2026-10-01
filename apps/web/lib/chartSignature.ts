/**
 * chartSignature — cheap structural fingerprint of a chart/analysis payload.
 *
 * Why: the Market page auto-refreshes every ~10s. `/chart/candles` frequently
 * returns the SAME payload (no new bar has closed yet), yet the JSON parse
 * always yields a NEW object reference. Assigning it via `setData` makes
 * `PriceChart` (memoised) re-render and rebuild its entire SVG — a visible
 * "kedip"/flicker for zero data change.
 *
 * The signature captures everything that would visibly change the chart or the
 * analysis panel:
 *  - symbol / timeframe identity,
 *  - bar count + the oldest & newest bar time AND close (a still-open bar can
 *    change its close without a new bar appearing),
 *  - the analysis verdict (signal/confidence/entry/SL/TP) so the levels refresh
 *    when the engine changes its mind,
 *  - the open-positions snapshot (tickets + SL/TP) that feeds the levels.
 *
 * When two consecutive payloads share a signature, the consumer should keep the
 * existing object (no re-render). When they differ, it should adopt the new one.
 */

type SigBar = { time?: string; close?: number };
type SigSeries = (number | null)[] | undefined;

type SigChart = {
  ok?: boolean;
  symbol?: string;
  timeframe?: string;
  bars?: SigBar[];
  overlays?: {
    ema_fast?: { values?: SigSeries };
    ema_slow?: { values?: SigSeries };
    bollinger?: { upper?: SigSeries; middle?: SigSeries; lower?: SigSeries } | null;
  };
  panels?: {
    rsi?: { values?: SigSeries } | null;
    macd?: { line?: SigSeries; signal_line?: SigSeries; histogram?: SigSeries } | null;
  };
};

type SigAnalysis = {
  ok?: boolean;
  reason?: string;
  symbol?: string;
  timeframe?: string;
  bar_count?: number;
  analysis?: {
    signal?: string;
    confidence?: number;
    entry?: number;
    stop_loss?: number | null;
    take_profit?: number | null;
    atr?: number | null;
    reason?: string;
    close?: number;
    timestamp?: string | null;
  };
  positions?: {
    ticket?: number | string;
    side?: string;
    volume?: number | string;
    entry?: number;
    sl?: number | null;
    tp?: number | null;
  }[];
  zones?: {
    scan_timeframe?: string;
    scan?: SigZone[];
    chart_timeframe?: string;
    chart?: SigZone[];
  };
};

type SigZone = {
  zone_id?: string;
  zone_type?: string;
  direction?: string;
  timeframe?: string;
  top?: number;
  bottom?: number;
  mitigation?: string;
};

/** Last N values of a series, joined — enough to detect an indicator shift. */
function tail(series: SigSeries, count = 3): string {
  if (!Array.isArray(series) || series.length === 0) return '';
  const from = Math.max(0, series.length - count);
  let out = '';
  for (let i = from; i < series.length; i++) {
    const v = series[i];
    out += (typeof v === 'number' ? v.toFixed(6) : 'n') + ',';
  }
  return out;
}

/** Fingerprint of a `/chart/candles` response. */
export function chartSignature(d: SigChart | null | undefined): string {
  if (!d) return '';
  const bars = d.bars ?? [];
  const n = bars.length;
  const first = n > 0 ? `${bars[0].time ?? ''}@${bars[0].close ?? ''}` : '';
  const last = n > 0 ? `${bars[n - 1].time ?? ''}@${bars[n - 1].close ?? ''}` : '';
  const ov = d.overlays;
  const pn = d.panels;
  return [
    d.ok ? '1' : '0',
    d.symbol ?? '',
    d.timeframe ?? '',
    n,
    first,
    last,
    tail(ov?.ema_fast?.values),
    tail(ov?.ema_slow?.values),
    tail(ov?.bollinger?.upper),
    tail(ov?.bollinger?.middle),
    tail(ov?.bollinger?.lower),
    tail(pn?.rsi?.values),
    tail(pn?.macd?.line),
    tail(pn?.macd?.signal_line),
    tail(pn?.macd?.histogram),
  ].join('|');
}

/** Fingerprint of a `/chart/analysis` response (verdict + levels + positions). */
export function analysisSignature(a: SigAnalysis | null | undefined): string {
  if (!a) return '';
  const an = a.analysis;
  const pos = (a.positions ?? [])
    .map((p) => `${p.ticket ?? ''}:${p.side ?? ''}:${p.volume ?? ''}:${p.sl ?? ''}:${p.tp ?? ''}`)
    .join(',');
  const zones = [...(a.zones?.scan ?? []), ...(a.zones?.chart ?? [])]
    .map((z) => `${z.zone_id ?? ''}:${z.zone_type ?? ''}:${z.direction ?? ''}:${z.timeframe ?? ''}:${z.top ?? ''}:${z.bottom ?? ''}:${z.mitigation ?? ''}`)
    .join(',');
  return [
    a.ok ? '1' : '0',
    a.reason ?? '',
    a.symbol ?? '',
    a.timeframe ?? '',
    a.bar_count ?? '',
    a.zones?.scan_timeframe ?? '',
    a.zones?.chart_timeframe ?? '',
    an
      ? [
          an.signal ?? '',
          an.confidence ?? '',
          an.entry ?? '',
          an.stop_loss ?? '',
          an.take_profit ?? '',
          an.atr ?? '',
          an.close ?? '',
          an.timestamp ?? '',
          an.reason ?? '',
        ].join(';')
      : '',
    pos,
    zones,
  ].join('|');
}
