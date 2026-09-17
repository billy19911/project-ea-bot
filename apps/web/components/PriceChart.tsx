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

import { useMemo, useState } from 'react';

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
};

type Props = {
  data: ChartData;
  showEma?: boolean;
  showBollinger?: boolean;
  showRsi?: boolean;
  showMacd?: boolean;
};

// ── Layout (viewBox units; SVG scales to 100% width) ────────────────────────
const W = 920;
const PAD_L = 6;
const PAD_R = 62; // ruang label harga di kanan
const MAIN_H = 300;
const RSI_H = 74;
const MACD_H = 86;
const GAP = 14;
const X_AXIS_H = 20;

const MAIN_TOP = 8;
const MAIN_BOTTOM = MAIN_TOP + MAIN_H;
const RSI_TOP = MAIN_BOTTOM + GAP;
const RSI_BOTTOM = RSI_TOP + RSI_H;
const MACD_TOP = RSI_BOTTOM + GAP;
const MACD_BOTTOM = MACD_TOP + MACD_H;
const TOTAL_H = MACD_BOTTOM + X_AXIS_H;

const INNER_W = W - PAD_L - PAD_R;

function buildSegments(
  values: Series,
  n: number,
  x: (i: number) => number,
  y: (v: number) => number,
): string[] {
  const segs: string[] = [];
  let cur = '';
  for (let i = 0; i < n; i++) {
    const v = values[i];
    if (typeof v === 'number' && Number.isFinite(v)) {
      cur += `${cur === '' ? 'M' : 'L'}${x(i).toFixed(2)},${y(v).toFixed(2)}`;
    } else if (cur !== '') {
      segs.push(cur);
      cur = '';
    }
  }
  if (cur !== '') segs.push(cur);
  return segs;
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

export default function PriceChart({
  data,
  showEma = true,
  showBollinger = true,
  showRsi = true,
  showMacd = true,
}: Props) {
  const [hover, setHover] = useState<number | null>(null);

  const bars = data.bars ?? [];
  const n = bars.length;

  const geom = useMemo(() => {
    if (n === 0) return null;

    // Rentang harga: low/high nyata (candle) + indikator yang tampil.
    let lo = Infinity;
    let hi = -Infinity;
    for (const b of bars) {
      if (b.low < lo) lo = b.low;
      if (b.high > hi) hi = b.high;
    }
    if (showBollinger && data.overlays?.bollinger) {
      const bb = data.overlays.bollinger;
      for (let i = 0; i < n; i++) {
        const u = bb.upper[i];
        const l = bb.lower[i];
        if (typeof u === 'number' && u > hi) hi = u;
        if (typeof l === 'number' && l < lo) lo = l;
      }
    }
    const pad = (hi - lo) * 0.04 || hi * 0.001 || 1;
    lo -= pad;
    hi += pad;

    const slot = INNER_W / n;
    const bodyW = Math.max(1.2, Math.min(9, slot * 0.62));

    const x = (i: number) => PAD_L + slot * (i + 0.5);
    const yMain = (v: number) => MAIN_TOP + (1 - (v - lo) / (hi - lo)) * MAIN_H;

    // RSI 0..100 tetap (skala baku indikator).
    const yRsi = (v: number) => RSI_TOP + (1 - v / 100) * RSI_H;

    // MACD: rentang dari line + signal + histogram nyata.
    let mLo = Infinity;
    let mHi = -Infinity;
    const macd = data.panels?.macd;
    if (showMacd && macd) {
      const scan = (arr: Series) => {
        for (const v of arr) {
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

    // Label waktu: ~6 label merata.
    const timeTicks: { i: number; label: string }[] = [];
    const tickCount = Math.min(6, n);
    for (let k = 0; k < tickCount; k++) {
      const i = Math.round((k / Math.max(1, tickCount - 1)) * (n - 1));
      timeTicks.push({ i, label: fmtTime(bars[i].time, data.timeframe) });
    }

    return { lo, hi, slot, bodyW, x, yMain, yRsi, yMacd, mLo, mHi, priceLines, timeTicks };
  }, [bars, n, data.overlays, data.panels, data.timeframe, showBollinger, showMacd]);

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

  const hoverBar = hover !== null && hover >= 0 && hover < n ? bars[hover] : null;

  return (
    <div className="priceChartWrap">
      <svg
        viewBox={`0 0 ${W} ${TOTAL_H}`}
        className="priceChartSvg"
        role="img"
        aria-label={`Chart ${data.symbol} ${data.timeframe}, ${n} bar`}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const relX = ((e.clientX - rect.left) / rect.width) * W;
          const idx = Math.floor((relX - PAD_L) / geom.slot);
          setHover(idx >= 0 && idx < n ? idx : null);
        }}
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

        {/* ── Bollinger Bands (isi tipis + tepi) ── */}
        {showBollinger && bb
          ? (() => {
              const up = buildSegments(bb.upper, n, geom.x, geom.yMain);
              const loSeg = buildSegments(bb.lower, n, geom.x, geom.yMain);
              const mid = buildSegments(bb.middle, n, geom.x, geom.yMain);
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

        {/* ── Candles ── */}
        {bars.map((b, i) => {
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

        {/* ── EMA overlays ── */}
        {showEma && emaFast
          ? buildSegments(emaFast.values, n, geom.x, geom.yMain).map((d, i) => (
              <path key={`ef-${i}`} d={d} className="pcEmaFast" fill="none" />
            ))
          : null}
        {showEma && emaSlow
          ? buildSegments(emaSlow.values, n, geom.x, geom.yMain).map((d, i) => (
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
            {buildSegments(rsi.values, n, geom.x, geom.yRsi).map((d, i) => (
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
            {buildSegments(macd.line, n, geom.x, geom.yMacd).map((d, i) => (
              <path key={`ml-${i}`} d={d} className="pcMacdLine" fill="none" />
            ))}
            {buildSegments(macd.signal_line, n, geom.x, geom.yMacd).map((d, i) => (
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

        {/* ── Crosshair hover ── */}
        {hover !== null ? (
          <line
            x1={geom.x(hover)}
            y1={MAIN_TOP}
            x2={geom.x(hover)}
            y2={MACD_BOTTOM}
            className="pcCrosshair"
          />
        ) : null}
      </svg>

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
