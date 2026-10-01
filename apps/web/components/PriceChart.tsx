'use client';

/**
 * PriceChart — chart candlestick SVG inline (Fase 1 "Pasar", nol dependency).
 *
 * Menggambar bar NYATA dari `/chart/candles` (sumber: MT5 read-only):
 * - Candlestick + overlay EMA (fast/slow) + Bollinger Bands.
 * - Sub-panel RSI (garis 30/70) dan MACD (line + signal + histogram).
 * - Crosshair + tooltip OHLC saat hover.
 *
 * Aturan jujur:
 * - Nilai `null` (indikator belum terdefinisi / data gagal) = GARIS PUTUS,
 *   bukan 0 palsu.
 * - Bila tidak ada bar valid, tampilkan pesan kosong — bukan chart karangan.
 * - Rentang sumbu Y dihitung dari harga nyata (low/high), bukan skala tetap.
 */

import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { nextViewport } from '../lib/viewport';
import { chartSignature } from '../lib/chartSignature';

export type ChartBar = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

type Series = (number | null)[];

export type ChartData = {
  ok: boolean;
  reason?: string;
  symbol?: string;
  timeframe?: string;
  bars?: ChartBar[];
  overlays?: {
    ema_fast: { period: number; values: Series };
    ema_slow: { period: number; values: Series };
    bollinger: {
      period: number;
      std: number;
      upper: Series;
      middle: Series;
      lower: Series;
    } | null;
  };
  panels?: {
    rsi: { period: number; values: Series } | null;
    macd: {
      fast: number;
      slow: number;
      signal: number;
      line: Series;
      signal_line: Series;
      histogram: Series;
    } | null;
  };
  provenance?: { source: string; mode: string; bar_count: number };
  /** True when even older bars exist on the server (chart lazy-loads them). */
  has_more?: boolean;
};

/**
 * Garis level harga nyata di atas chart (entry/SL/TP analisa atau posisi
 * terbuka). Nilai harus berasal dari server — bukan dihitung ulang di klien.
 */
export type ChartLevel = {
  label: string;
  value: number;
  kind: 'entry' | 'stop' | 'target';
};

export type ChartZone = {
  zone_id: string;
  zone_type: 'ORDER_BLOCK' | 'FVG';
  direction: 'LONG' | 'SHORT';
  timeframe: string;
  top: number;
  bottom: number;
  mitigation: string;
  gap_atr?: number;
  displacement_atr?: number;
  source?: 'scan' | 'chart';
};

type Props = {
  data: ChartData;
  levels?: ChartLevel[];
  zones?: ChartZone[];
  showEma?: boolean;
  showBollinger?: boolean;
  showRsi?: boolean;
  showMacd?: boolean;
  /** Called when the user pans to the oldest bar and more history exists. */
  onNeedMoreHistory?: () => void;
  /** True while an older-history page is being fetched. */
  loadingMore?: boolean;
  /**
   * Live last price for the charted symbol. Drawn as a "Price Now" line + tag
   * INSIDE the plot but as a plain (non-memo-blocking) element: a tick updates
   * only this line, never the candles/indicators/viewport — so the price keeps
   * showing without the chart flickering.
   */
  livePrice?: number | null;
  /** Bar open of the latest live candle, to colour the Price Now tag. */
  liveOpen?: number | null;
};

// ── Layout (viewBox units; SVG scales to 100% width) ────────────────────────
const W = 920;
const PAD_L = 6;
const PAD_R = 62; // ruang label harga di kanan
const RSI_H = 74;
const MACD_H = 86;
const GAP = 14;
const X_AXIS_H = 20;

// Tinggi panel harga (candle) bisa diubah operator (drag) — lihat `mainH` state.
const MAIN_H_MIN = 120;
const MAIN_H_MAX = 720;
const MAIN_H_DEFAULT = 300;

const MAIN_TOP = 8;

const INNER_W = W - PAD_L - PAD_R;

/** Derive every panel's vertical position from the (resizable) price height. */
function layoutFor(mainH: number) {
  const MAIN_H = mainH;
  const MAIN_BOTTOM = MAIN_TOP + MAIN_H;
  const RSI_TOP = MAIN_BOTTOM + GAP;
  const RSI_BOTTOM = RSI_TOP + RSI_H;
  const MACD_TOP = RSI_BOTTOM + GAP;
  const MACD_BOTTOM = MACD_TOP + MACD_H;
  const TOTAL_H = MACD_BOTTOM + X_AXIS_H;
  return { MAIN_H, MAIN_BOTTOM, RSI_TOP, RSI_BOTTOM, MACD_TOP, MACD_BOTTOM, TOTAL_H };
}

function fmtPrice(v: number): string {
  if (Math.abs(v) >= 1000) return v.toFixed(1);
  if (Math.abs(v) >= 10) return v.toFixed(2);
  return v.toFixed(5);
}

function fmtTime(iso: string, timeframe?: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (x: number) => String(x).padStart(2, '0');
  const day = `${pad(d.getDate())}/${pad(d.getMonth() + 1)}`;
  if (timeframe === 'D1' || timeframe === 'W1' || timeframe === 'MN1') {
    return day;
  }
  return `${day} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function PriceChart({
  data,
  levels = [],
  zones = [],
  showEma = true,
  showBollinger = true,
  showRsi = true,
  showMacd = true,
  onNeedMoreHistory,
  loadingMore = false,
  livePrice = null,
  liveOpen = null,
}: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  // Tinggi panel harga (resizable). Disimpan di state supaya operator bisa
  // memperbesar/memperkecil area candle; sub-panel RSI/MACD tetap.
  const [mainH, setMainH] = useState<number>(MAIN_H_DEFAULT);
  const LAY = layoutFor(mainH);
  const { MAIN_BOTTOM, RSI_TOP, RSI_BOTTOM, MACD_TOP, MACD_BOTTOM, TOTAL_H } = LAY;

  const bars = data.bars ?? [];
  const n = bars.length;

  // ── Viewport (pan/zoom) ────────────────────────────────────────────────
  // The full dataset stays in memory; only [viewStart, viewEnd) is drawn.
  // This is what keeps panning smooth and the SVG light no matter how many
  // bars were fetched. `visibleCount` = number of candles on screen.
  const MIN_VISIBLE = 20;
  const [visibleCount, setVisibleCount] = useState<number>(n || 1);
  const [viewEnd, setViewEnd] = useState<number>(n); // exclusive index
  const dragRef = useRef<{ x: number; startEnd: number } | null>(null);

  // Clamp helper so the window always stays inside [0, n].
  const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

  // Identity of the *dataset* (symbol/timeframe) — resets the viewport ONLY when
  // the instrument changes. A refresh/tick keeps the same identity, so the
  // viewport and hover are never yanked back (the flicker this fixes).
  const dataKey = `${data.symbol ?? ''}/${data.timeframe ?? ''}`;
  const oldestTime = n > 0 ? bars[0].time : '';
  const prevRef = useRef<{ key: string; n: number; oldestTime: string }>({
    key: dataKey,
    n,
    oldestTime,
  });

  useEffect(() => {
    const prev = prevRef.current;
    // How many bars were appended at the end: the total grew and the oldest bar
    // is unchanged. Anything else that adds bars is a history prepend.
    const appended = n > prev.n && prev.oldestTime === oldestTime ? n - prev.n : 0;
    const next = nextViewport(
      { key: prev.key, n: prev.n, visibleCount, viewEnd },
      { key: dataKey, n, appendCount: appended },
    );
    setVisibleCount((c) => (c === next.visibleCount ? c : next.visibleCount));
    setViewEnd((e) => (e === next.viewEnd ? e : next.viewEnd));
    // Only clear the hover when the dataset identity actually changed (or the
    // data shrank); a mere append/refresh must not drop the crosshair.
    if (prev.key !== dataKey || n < prev.n) setHover(null);
    prevRef.current = { key: dataKey, n, oldestTime };
    // `visibleCount`/`viewEnd` are intentionally read but not deps: this effect
    // reacts to incoming data, not to the user's pan/zoom (which update them).
  }, [dataKey, n, oldestTime]);

  const zoom = (nextCount: number) => {
    if (n === 0) return;
    const count = clamp(Math.round(nextCount), Math.min(MIN_VISIBLE, n), n);
    setVisibleCount(count);
    setViewEnd((end) => clamp(end, count, n));
    setHover(null);
  };

  const end = clamp(viewEnd, 0, n);
  const start = clamp(end - visibleCount, 0, Math.max(0, n - visibleCount));
  const vEnd = start + Math.min(visibleCount, n - start);
  // Memoised so the geometry memo below gets a stable reference (a fresh array
  // each render would invalidate it and force a full SVG re-render every tick).
  const visibleBars = useMemo(() => bars.slice(start, vEnd), [bars, start, vEnd]);
  const vn = visibleBars.length;

  // Lazily pull older history when the user reaches the oldest bar.
  useEffect(() => {
    if (start === 0 && data.has_more && !loadingMore && onNeedMoreHistory) {
      onNeedMoreHistory();
    }
  }, [start, data.has_more, loadingMore, onNeedMoreHistory]);

  const geom = useMemo(() => {
    if (n === 0 || vn === 0) return null;

    // Rentang harga: low/high nyata dari bar yang terlihat + indikator tampil.
    let lo = Infinity;
    let hi = -Infinity;
    for (const b of visibleBars) {
      if (b.low < lo) lo = b.low;
      if (b.high > hi) hi = b.high;
    }
    if (showBollinger && data.overlays?.bollinger) {
      const bb = data.overlays.bollinger;
      for (let i = start; i < vEnd; i++) {
        const u = bb.upper[i];
        const l = bb.lower[i];
        if (typeof u === 'number' && u > hi) hi = u;
        if (typeof l === 'number' && l < lo) lo = l;
      }
    }
    // Level nyata (SL/TP/entry) ikut menentukan rentang supaya tidak terpotong.
    // Guard: hanya level > 0 yang masuk akal untuk harga (mengabaikan 0 yang
    // bisa datang dari feed broker tanpa `last`, agar skala tidak melebar
    // sampai 0 dan membuat candle "gepeng").
    for (const lv of levels) {
      if (!Number.isFinite(lv.value) || lv.value <= 0) continue;
      if (lv.value < lo) lo = lv.value;
      if (lv.value > hi) hi = lv.value;
    }
    const pad = (hi - lo) * 0.04 || hi * 0.001 || 1;
    lo -= pad;
    hi += pad;

    const slot = INNER_W / vn;
    const bodyW = Math.max(1.2, Math.min(9, slot * 0.62));

    // x() takes an ABSOLUTE bar index; only bars in [start, vEnd) are drawn.
    const x = (i: number) => PAD_L + slot * (i - start + 0.5);
    const yMain = (v: number) => MAIN_TOP + (1 - (v - lo) / (hi - lo)) * mainH;

    // RSI 0..100 tetap (skala baku indikator).
    const yRsi = (v: number) => RSI_TOP + (1 - v / 100) * RSI_H;

    // MACD: rentang dari line + signal + histogram nyata (bar terlihat).
    let mLo = Infinity;
    let mHi = -Infinity;
    const macd = data.panels?.macd;
    if (showMacd && macd) {
      const scan = (arr: Series) => {
        for (let i = start; i < vEnd; i++) {
          const v = arr[i];
          if (typeof v === 'number' && Number.isFinite(v)) {
            if (v < mLo) mLo = v;
            if (v > mHi) mHi = v;
          }
        }
      };
      scan(macd.line);
      scan(macd.signal_line);
      scan(macd.histogram);
    }
    if (!Number.isFinite(mLo) || !Number.isFinite(mHi)) {
      mLo = -1;
      mHi = 1;
    }
    const mPad = (mHi - mLo) * 0.08 || 0.0001;
    mLo -= mPad;
    mHi += mPad;
    const yMacd = (v: number) => MACD_TOP + (1 - (v - mLo) / (mHi - mLo)) * MACD_H;

    // Grid harga: 5 garis horizontal dengan label nyata.
    const priceLines = [0, 1, 2, 3, 4].map((k) => {
      const v = lo + ((hi - lo) * k) / 4;
      return { v, y: yMain(v) };
    });

    // Label waktu: ~6 label merata pada window yang terlihat.
    const timeTicks: { i: number; label: string }[] = [];
    const tickCount = Math.min(6, vn);
    for (let k = 0; k < tickCount; k++) {
      const i = start + Math.round((k / Math.max(1, tickCount - 1)) * (vn - 1));
      timeTicks.push({ i, label: fmtTime(bars[i].time, data.timeframe) });
    }

    return { lo, hi, slot, bodyW, x, yMain, yRsi, yMacd, mLo, mHi, priceLines, timeTicks };
  }, [bars, n, start, vEnd, vn, data.overlays, data.panels, data.timeframe, showBollinger, showMacd, levels, mainH]);

  // ── Wheel zoom (non-passive so we can preventDefault page scroll) ───────
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (n === 0) return;
      e.preventDefault();
      // Keep the bar under the cursor roughly anchored: zoom around the
      // pointer's x position within the plot.
      const rect = el.getBoundingClientRect();
      const relX = ((e.clientX - rect.left) / rect.width) * W;
      const frac = clamp((relX - PAD_L) / INNER_W, 0, 1);
      const anchorAbs = start + frac * vn;

      const factor = e.deltaY > 0 ? 1.15 : 1 / 1.15;
      const count = clamp(Math.round(visibleCount * factor), Math.min(MIN_VISIBLE, n), n);
      // Recompute so the anchor stays at the same fractional screen position.
      const newStart = clamp(Math.round(anchorAbs - frac * count), 0, Math.max(0, n - count));
      setVisibleCount(count);
      setViewEnd(newStart + count);
      setHover(null);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [n, visibleCount, start, vn]);

  // ── Drag to pan ─────────────────────────────────────────────────────────
  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (n === 0 || vn >= n) return;
    dragRef.current = { x: e.clientX, startEnd: vEnd };
    (e.currentTarget as SVGSVGElement).setPointerCapture?.(e.pointerId);
  };  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const d = dragRef.current;
    if (!d) return;
    const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
    const barsPerPx = vn / (rect.width * (INNER_W / W));
    const deltaBars = Math.round((e.clientX - d.x) * barsPerPx);
    const nextEnd = clamp(d.startEnd - deltaBars, visibleCount, n);
    setViewEnd(nextEnd);
  };
  const endDrag = (e: React.PointerEvent<SVGSVGElement>) => {
    dragRef.current = null;
    (e.currentTarget as SVGSVGElement).releasePointerCapture?.(e.pointerId);
  };

  // ── Resize the price panel (drag the divider between candle & RSI) ───────
  const resizeRef = useRef<{ y: number; startH: number } | null>(null);
  const onResizeDown = (e: React.PointerEvent<HTMLDivElement>) => {
    resizeRef.current = { y: e.clientY, startH: mainH };
    (e.currentTarget as HTMLDivElement).setPointerCapture?.(e.pointerId);
    e.preventDefault();
  };
  const onResizeMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = resizeRef.current;
    if (!d) return;
    const rect = svgRef.current?.getBoundingClientRect();
    // Convert screen pixels → SVG units using the rendered scale.
    const scale = rect && rect.width > 0 ? W / rect.width : 1;
    const deltaUnits = (e.clientY - d.y) * scale;
    setMainH(clamp(Math.round(d.startH + deltaUnits), MAIN_H_MIN, MAIN_H_MAX));
  };
  const onResizeUp = (e: React.PointerEvent<HTMLDivElement>) => {
    resizeRef.current = null;
    (e.currentTarget as HTMLDivElement).releasePointerCapture?.(e.pointerId);
  };

  if (!data.ok || n === 0 || !geom) {
    return (
      <div className="priceChartEmpty" role="img" aria-label="Chart: belum ada data">
        <strong>Chart belum bisa digambar.</strong>
        <span>{data.reason ?? 'Tidak ada bar dari terminal MT5 untuk simbol/timeframe ini.'}</span>
      </div>
    );
  }

  const emaFast = data.overlays?.ema_fast;
  const emaSlow = data.overlays?.ema_slow;
  const bb = data.overlays?.bollinger ?? null;
  const rsi = data.panels?.rsi ?? null;
  const macd = data.panels?.macd ?? null;

  const hoverBar =
    hover !== null && hover >= start && hover < vEnd ? bars[hover] : null;

  // Build indicator segments ONLY over the visible window, using absolute
  // indices so the line stays aligned with the candles after panning.
  const seg = (values: Series, y: (v: number) => number) => {
    const segs: string[] = [];
    let cur = '';
    for (let i = start; i < vEnd; i++) {
      const v = values[i];
      if (typeof v === 'number' && Number.isFinite(v)) {
        cur += `${cur === '' ? 'M' : 'L'}${geom.x(i).toFixed(2)},${y(v).toFixed(2)}`;
      } else if (cur !== '') {
        segs.push(cur);
        cur = '';
      }
    }
    if (cur !== '') segs.push(cur);
    return segs;
  };

  const canPan = vn < n;

  return (
    <div className="priceChartWrap">
      {/* Viewport controls: zoom in/out, follow-latest, reset. Client-side
          only — never refetches. */}
      <div className="pcControls" role="group" aria-label="Kontrol chart">
        <button
          type="button"
          className="pcCtrlBtn"
          onClick={() => zoom(visibleCount / 1.4)}
          disabled={vn <= Math.min(MIN_VISIBLE, n)}
          title="Perbesar (zoom in)"
        >
          +
        </button>
        <button
          type="button"
          className="pcCtrlBtn"
          onClick={() => zoom(visibleCount * 1.4)}
          disabled={vn >= n}
          title="Perkecil (zoom out)"
        >
          −
        </button>
        <button
          type="button"
          className="pcCtrlBtn"
          onClick={() => { setVisibleCount(n); setViewEnd(n); setHover(null); }}
          disabled={!canPan && vn >= n}
          title="Tampilkan semua bar"
        >
          Semua
        </button>
        <button
          type="button"
          className="pcCtrlBtn"
          onClick={() => { setViewEnd(n); setHover(null); }}
          disabled={vEnd >= n}
          title="Lompat ke bar terbaru"
        >
          Terbaru
        </button>
        <span className="pcCtrlSep" aria-hidden />
        <button
          type="button"
          className="pcCtrlBtn"
          onClick={() => setMainH((h) => clamp(h - 60, MAIN_H_MIN, MAIN_H_MAX))}
          disabled={mainH <= MAIN_H_MIN}
          title="Perkecil tinggi area harga"
        >
          ↕−
        </button>
        <button
          type="button"
          className="pcCtrlBtn"
          onClick={() => setMainH((h) => clamp(h + 60, MAIN_H_MIN, MAIN_H_MAX))}
          disabled={mainH >= MAIN_H_MAX}
          title="Perbesar tinggi area harga"
        >
          ↕+
        </button>
        <span className="pcCtrlInfo">
          {loadingMore ? 'memuat bar lama… · ' : ''}
          {start + 1}–{vEnd} / {n} bar
        </span>
      </div>
      <div className="pcPlot">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${TOTAL_H}`}
        className={`priceChartSvg${canPan ? ' pcPannable' : ''}`}
        role="img"
        aria-label={`Chart ${data.symbol} ${data.timeframe}, menampilkan ${vn} dari ${n} bar`}
        style={{ touchAction: canPan ? 'none' : undefined }}
        onMouseLeave={() => setHover(null)}
        onPointerDown={onPointerDown}
        onPointerMove={(e) => {
          onPointerMove(e);
          if (dragRef.current) return; // don't move the crosshair while dragging
          const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const relX = ((e.clientX - rect.left) / rect.width) * W;
          const idx = start + Math.floor((relX - PAD_L) / geom.slot);
          setHover(idx >= start && idx < vEnd ? idx : null);
        }}
        onPointerUp={endDrag}        onPointerCancel={endDrag}
      >
        {/* ── Panel utama: grid + label harga ── */}
        {geom.priceLines.map((pl, i) => (
          <g key={`pl-${i}`}>
            <line x1={PAD_L} y1={pl.y} x2={PAD_L + INNER_W} y2={pl.y} className="pcGrid" />
            <text x={PAD_L + INNER_W + 6} y={pl.y + 3.5} className="pcAxisLabel">
              {fmtPrice(pl.v)}
            </text>
          </g>
        ))}

        {/* OB/FVG price bands from the scanner and the displayed chart TF. */}
        {zones.map((zone) => {
          if (
            !Number.isFinite(zone.top) ||
            !Number.isFinite(zone.bottom) ||
            zone.top <= zone.bottom ||
            zone.bottom > geom.hi ||
            zone.top < geom.lo
          ) return null;
          const rawTop = geom.yMain(zone.top);
          const rawBottom = geom.yMain(zone.bottom);
          const y = Math.max(MAIN_TOP, Math.min(MAIN_BOTTOM, rawTop));
          const bottom = Math.max(MAIN_TOP, Math.min(MAIN_BOTTOM, rawBottom));
          const direction = zone.direction === 'LONG' ? 'long' : 'short';
          const kind = zone.zone_type === 'ORDER_BLOCK' ? 'ob' : 'fvg';
          const source = zone.source === 'chart' ? 'chart' : 'scan';
          const label = `${source.toUpperCase()} ${zone.timeframe} · ${kind.toUpperCase()} ${direction.toUpperCase()}`;
          return (
            <g key={`${source}-${zone.zone_id}`} className={`pcZone pcZone${direction} pcZone${kind} pcZone${source}`}>
              <rect
                x={PAD_L}
                y={y}
                width={INNER_W}
                height={Math.max(1, bottom - y)}
                className="pcZoneBand"
              />
              <line x1={PAD_L} y1={y} x2={PAD_L + INNER_W} y2={y} className="pcZoneEdge" />
              <line x1={PAD_L} y1={bottom} x2={PAD_L + INNER_W} y2={bottom} className="pcZoneEdge" />
              <text x={PAD_L + 4} y={Math.min(MAIN_BOTTOM - 3, y + 11)} className="pcZoneLabel">
                {label}
              </text>
            </g>
          );
        })}

        {/* ── Bollinger Bands (isi tipis + tepi) ── */}
        {showBollinger && bb
          ? (() => {
              const up = seg(bb.upper, geom.yMain);
              const loSeg = seg(bb.lower, geom.yMain);
              const mid = seg(bb.middle, geom.yMain);
              return (
                <g>
                  {up.map((d, i) => (
                    <path key={`bbu-${i}`} d={d} className="pcBbEdge" fill="none" />
                  ))}
                  {loSeg.map((d, i) => (
                    <path key={`bbl-${i}`} d={d} className="pcBbEdge" fill="none" />
                  ))}
                  {mid.map((d, i) => (
                    <path key={`bbm-${i}`} d={d} className="pcBbMid" fill="none" />
                  ))}
                </g>
              );
            })()
          : null}

        {/* ── Candles (hanya bar pada window yang terlihat) ── */}
        {bars.slice(start, vEnd).map((b, k) => {
          const i = start + k;
          const up = b.close >= b.open;
          const xc = geom.x(i);
          const yO = geom.yMain(b.open);
          const yC = geom.yMain(b.close);
          const yH = geom.yMain(b.high);
          const yL = geom.yMain(b.low);
          const top = Math.min(yO, yC);
          const h = Math.max(1, Math.abs(yC - yO));
          return (
            <g key={`c-${i}`} className={up ? 'pcUp' : 'pcDown'}>
              <line x1={xc} y1={yH} x2={xc} y2={yL} strokeWidth={1} className="pcWick" />
              <rect
                x={xc - geom.bodyW / 2}
                y={top}
                width={geom.bodyW}
                height={h}
                className="pcBody"
              />
            </g>
          );
        })}

        {/* ── Garis level nyata: entry / SL / TP ── */}
        {levels.map((lv, i) => {
          if (!Number.isFinite(lv.value) || lv.value <= 0) return null;
          const y = geom.yMain(lv.value);
          if (y < MAIN_TOP - 1 || y > MAIN_BOTTOM + 1) return null;
          const cls =
            lv.kind === 'stop' ? 'pcLevelStop' : lv.kind === 'target' ? 'pcLevelTarget' : 'pcLevelEntry';
          const anchorRight = i % 2 === 1; // hindari label saling tumpuk
          return (
            <g key={`lv-${i}`} className={cls}>
              <line x1={PAD_L} y1={y} x2={PAD_L + INNER_W} y2={y} className="pcLevelLine" />
              <text
                x={anchorRight ? PAD_L + INNER_W - 4 : PAD_L + 4}
                y={y - 3.5}
                className="pcLevelLabel"
                textAnchor={anchorRight ? 'end' : 'start'}
              >
                {lv.label} · {fmtPrice(lv.value)}
              </text>
            </g>
          );
        })}

        {/* ── EMA overlays ── */}
        {showEma && emaFast
          ? seg(emaFast.values, geom.yMain).map((d, i) => (
              <path key={`ef-${i}`} d={d} className="pcEmaFast" fill="none" />
            ))
          : null}
        {showEma && emaSlow
          ? seg(emaSlow.values, geom.yMain).map((d, i) => (
              <path key={`es-${i}`} d={d} className="pcEmaSlow" fill="none" />
            ))
          : null}

        {/* ── RSI panel ── */}
        {showRsi && rsi ? (
          <g>
            <line x1={PAD_L} y1={RSI_TOP} x2={PAD_L + INNER_W} y2={RSI_TOP} className="pcGrid" />
            <line
              x1={PAD_L}
              y1={RSI_BOTTOM}
              x2={PAD_L + INNER_W}
              y2={RSI_BOTTOM}
              className="pcGrid"
            />
            <line
              x1={PAD_L}
              y1={geom.yRsi(70)}
              x2={PAD_L + INNER_W}
              y2={geom.yRsi(70)}
              className="pcBand70"
            />
            <line
              x1={PAD_L}
              y1={geom.yRsi(30)}
              x2={PAD_L + INNER_W}
              y2={geom.yRsi(30)}
              className="pcBand30"
            />
            {seg(rsi.values, geom.yRsi).map((d, i) => (
              <path key={`rsi-${i}`} d={d} className="pcRsiLine" fill="none" />
            ))}
            <text x={PAD_L + INNER_W + 6} y={geom.yRsi(70) + 3.5} className="pcAxisLabel">
              70
            </text>
            <text x={PAD_L + INNER_W + 6} y={geom.yRsi(30) + 3.5} className="pcAxisLabel">
              30
            </text>
            <text x={PAD_L} y={RSI_TOP - 3} className="pcPanelTitle">
              RSI ({rsi.period})
            </text>
          </g>
        ) : null}

        {/* ── MACD panel ── */}
        {showMacd && macd ? (
          <g>
            <line x1={PAD_L} y1={MACD_TOP} x2={PAD_L + INNER_W} y2={MACD_TOP} className="pcGrid" />
            <line
              x1={PAD_L}
              y1={MACD_BOTTOM}
              x2={PAD_L + INNER_W}
              y2={MACD_BOTTOM}
              className="pcGrid"
            />
            <line
              x1={PAD_L}
              y1={geom.yMacd(0)}
              x2={PAD_L + INNER_W}
              y2={geom.yMacd(0)}
              className="pcZeroLine"
            />
            {/* Histogram: batang dari garis nol. */}
            {macd.histogram.map((v, i) => {
              if (i < start || i >= vEnd) return null;
              if (typeof v !== 'number' || !Number.isFinite(v)) return null;
              const y0 = geom.yMacd(0);
              const y1 = geom.yMacd(v);
              const xc = geom.x(i);
              return (
                <rect
                  key={`mh-${i}`}
                  x={xc - geom.bodyW / 2}
                  y={Math.min(y0, y1)}
                  width={geom.bodyW}
                  height={Math.max(1, Math.abs(y1 - y0))}
                  className={v >= 0 ? 'pcHistUp' : 'pcHistDown'}
                />
              );
            })}
            {seg(macd.line, geom.yMacd).map((d, i) => (
              <path key={`ml-${i}`} d={d} className="pcMacdLine" fill="none" />
            ))}
            {seg(macd.signal_line, geom.yMacd).map((d, i) => (
              <path key={`ms-${i}`} d={d} className="pcMacdSignal" fill="none" />
            ))}
            <text x={PAD_L} y={MACD_TOP - 3} className="pcPanelTitle">
              MACD ({macd.fast}/{macd.slow}/{macd.signal})
            </text>
          </g>
        ) : null}

        {/* ── Sumbu waktu ── */}
        {geom.timeTicks.map((t, i) => (
          <text
            key={`t-${i}`}
            x={geom.x(t.i)}
            y={TOTAL_H - 6}
            className="pcTimeLabel"
            textAnchor={i === 0 ? 'start' : i === geom.timeTicks.length - 1 ? 'end' : 'middle'}
          >
            {t.label}
          </text>
        ))}

        {/* ── Crosshair hover (vertikal + horizontal putus-putus) ── */}
        {hover !== null ? (
          <line
            x1={geom.x(hover)}
            y1={MAIN_TOP}
            x2={geom.x(hover)}
            y2={MACD_BOTTOM}
            className="pcCrosshair"
          />
        ) : null}
        {hover !== null && hoverBar ? (
          <>
            <line
              x1={PAD_L}
              y1={geom.yMain(hoverBar.close)}
              x2={PAD_L + INNER_W}
              y2={geom.yMain(hoverBar.close)}
              className="pcCrosshairH"
            />
            <text
              x={PAD_L + INNER_W + 6}
              y={geom.yMain(hoverBar.close) + 3.5}
              className="pcCrosshairLabel"
            >
              {fmtPrice(hoverBar.close)}
            </text>
          </>
        ) : null}

        {/* ── Price Now: live last price (tanpa mengganggu memo chart) ──
            Only the y of this line/tag changes on a tick; candles, indicators
            and the viewport are untouched, so nothing flickers. */}
        {typeof livePrice === 'number' && Number.isFinite(livePrice) && livePrice > 0
          ? (() => {
              const yNow = geom.yMain(livePrice);
              if (yNow < MAIN_TOP - 1 || yNow > MAIN_BOTTOM + 1) return null;
              const up = liveOpen == null ? null : livePrice >= liveOpen;
              const cls = up == null ? '' : up ? 'up' : 'down';
              return (
                <g className="pcPriceNowGroup">
                  <line
                    x1={PAD_L}
                    y1={yNow}
                    x2={PAD_L + INNER_W}
                    y2={yNow}
                    className="pcPriceNowLine"
                  />
                  <rect
                    x={PAD_L + INNER_W + 2}
                    y={yNow - 8}
                    width={PAD_R - 6}
                    height={16}
                    rx={3}
                    className={`pcPriceNowTagBox ${cls}`}
                  />
                  <text
                    x={PAD_L + INNER_W + PAD_R / 2}
                    y={yNow + 4}
                    textAnchor="middle"
                    className="pcPriceNowTagText"
                  >
                    {fmtPrice(livePrice)}
                  </text>
                </g>
              );
            })()
          : null}
      </svg>

      {/* Divider drag handle: resize the price panel height. Positioned as a
          fraction of the SVG's own coordinate height so it tracks the
          responsive scale exactly. */}
      <div
        className="pcResizeHandle"
        style={{ top: `${(MAIN_BOTTOM / TOTAL_H) * 100}%` }}
        onPointerDown={onResizeDown}
        onPointerMove={onResizeMove}
        onPointerUp={onResizeUp}
        onPointerCancel={onResizeUp}
        role="separator"
        aria-orientation="horizontal"
        aria-label="Tarik untuk mengubah tinggi area harga"
        title="Tarik untuk mengubah tinggi area harga"
      >
        <span className="pcResizeGrip" aria-hidden />
      </div>
      </div>

      {/* Tooltip OHLC + indikator (nilai nyata dari bar hover). */}
      {hoverBar ? (
        <div className="pcTooltip" role="status">
          <div className="pcTtTime">{fmtTime(hoverBar.time, data.timeframe)}</div>
          <div className="pcTtGrid">
            <span>O</span>
            <b>{fmtPrice(hoverBar.open)}</b>
            <span>H</span>
            <b>{fmtPrice(hoverBar.high)}</b>
            <span>L</span>
            <b>{fmtPrice(hoverBar.low)}</b>
            <span>C</span>
            <b className={hoverBar.close >= hoverBar.open ? 'pcUpText' : 'pcDownText'}>
              {fmtPrice(hoverBar.close)}
            </b>
          </div>
          {showEma && emaFast && emaSlow && hover !== null ? (
            <div className="pcTtInd">
              EMA {emaFast.period}:{' '}
              {typeof emaFast.values[hover] === 'number' ? fmtPrice(emaFast.values[hover]!) : '—'}{' '}
              · EMA {emaSlow.period}:{' '}
              {typeof emaSlow.values[hover] === 'number' ? fmtPrice(emaSlow.values[hover]!) : '—'}
            </div>
          ) : null}
          {showRsi && rsi && hover !== null ? (
            <div className="pcTtInd">
              RSI: {typeof rsi.values[hover] === 'number' ? rsi.values[hover]!.toFixed(1) : '—'}
            </div>
          ) : null}
          {showMacd && macd && hover !== null ? (
            <div className="pcTtInd">
              MACD: {typeof macd.line[hover] === 'number' ? macd.line[hover]!.toFixed(5) : '—'} · Sig:{' '}
              {typeof macd.signal_line[hover] === 'number'
                ? macd.signal_line[hover]!.toFixed(5)
                : '—'}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// Memoised with an explicit comparator: the parent re-renders on every live Web
// tick (~2.5s) and auto-refresh (~10s), but the chart only needs to re-draw when
// the DATA actually changed. A plain memo compares `data` by reference — and a
// JSON refetch always yields a new object — so it would rebuild the entire SVG
// every refresh (the "kedip"). We compare the structural signature instead, plus
// the toggle flags, the levels, and the loading flag. Callbacks are assumed
// stable (memoised with useCallback in the parent).
function levelsSignature(levels: ChartLevel[]): string {
  let out = '';
  for (const l of levels) out += `${l.kind}:${l.label}:${l.value};`;
  return out;
}

function zonesSignature(zones: ChartZone[]): string {
  let out = '';
  for (const zone of zones) {
    out += `${zone.source}:${zone.zone_id}:${zone.top}:${zone.bottom}:${zone.mitigation};`;
  }
  return out;
}

export default memo(PriceChart, (prev, next) => {
  if (chartSignature(prev.data) !== chartSignature(next.data)) return false;
  if (levelsSignature(prev.levels ?? []) !== levelsSignature(next.levels ?? [])) return false;
  if (zonesSignature(prev.zones ?? []) !== zonesSignature(next.zones ?? [])) return false;
  // Live price/open are compared so the "Price Now" line moves on a tick, but
  // they do NOT reset the viewport or rebuild geometry (both key on the data
  // signature), so this re-render is a cheap diff, not a flicker.
  if (prev.livePrice !== next.livePrice) return false;
  if (prev.liveOpen !== next.liveOpen) return false;
  return (
    prev.showEma === next.showEma &&
    prev.showBollinger === next.showBollinger &&
    prev.showRsi === next.showRsi &&
    prev.showMacd === next.showMacd &&
    prev.loadingMore === next.loadingMore &&
    prev.onNeedMoreHistory === next.onNeedMoreHistory
  );
});
