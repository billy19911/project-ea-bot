'use client';

// Halaman "Pasar" (Fase 1) — chart candlestick multi-timeframe + indikator MT5.
// Data sumber: /chart/candles (candles) & /chart/analysis (engine analysis).
// Semua data read‑only; tidak ada nilai palsu, nilai null → garis putus.

import { useCallback, useEffect, useRef, useState } from 'react';
import styles from './page.module.css';
import { apiFetch } from '../../lib/api';
import { useAutoRefresh } from '../../lib/useAutoRefresh';
import { useLiveQuotes, type LivePosition } from '../../lib/useLiveQuotes';
import AppShell from '../../components/AppShell';
import Pagination from '../../components/ui/pagination';
import PriceChart, { ChartData, ChartLevel } from '../../components/PriceChart';

const TIMEFRAMES = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1', 'MN1'] as const;
type Timeframe = (typeof TIMEFRAMES)[number];

const DEFAULT_SYMBOLS = ['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'BTCUSD'];

// Price formatter that adapts decimals to magnitude (like the chart axis).
function fmtLive(v: number): string {
  if (!Number.isFinite(v)) return '—';
  if (Math.abs(v) >= 1000) return v.toFixed(1);
  if (Math.abs(v) >= 10) return v.toFixed(2);
  return v.toFixed(5);
}

// Analysis response shape (additional to candles)
type AnalysisData = {
  ok: boolean;
  reason?: string;
  symbol?: string;
  timeframe?: string;
  bar_count?: number;
  analysis?: {
    signal: 'BUY' | 'SELL' | 'HOLD';
    confidence: number;
    entry: number;
    stop_loss: number | null;
    take_profit: number | null;
    atr: number | null;
    position_size: number;
    reason: string;
    close: number;
    timestamp: string | null;
  };
  positions?: {
    ticket: number;
    symbol: string;
    side: string;
    volume: number;
    entry: number;
    current: number;
    sl: number | null;
    tp: number | null;
    profit: number;
  }[];
  provenance?: {
    source: string;
    mode: string;
    engine: string;
    stop_multiplier: number;
    reward_risk_ratio: number;
    risk_percent: number;
  };
};

// Renders a numeric value that briefly flashes when it changes — gives the
// "angka bergerak" feel without re-rendering the whole table.
function LiveNumber({ value, format, className }: { value: number; format: (v: number) => string; className?: string }) {
  const [flash, setFlash] = useState(false);
  const prev = useRef<number>(value);
  useEffect(() => {
    if (prev.current !== value) {
      prev.current = value;
      setFlash(true);
      const t = setTimeout(() => setFlash(false), 900);
      return () => clearTimeout(t);
    }
  }, [value]);
  return <span className={`${flash ? 'liveFlash ' : ''}${className ?? ''}`.trim()}>{format(value)}</span>;
}

export default function MarketPage() {
  const [symbol, setSymbol] = useState('XAUUSD');
  const [symbolInput, setSymbolInput] = useState('XAUUSD');
  const [symbols, setSymbols] = useState<string[]>(DEFAULT_SYMBOLS);
  const [timeframe, setTimeframe] = useState<Timeframe>('H1');
  const [bars, setBars] = useState(300);
  const [showEma, setShowEma] = useState(true);
  const [showBollinger, setShowBollinger] = useState(true);
  const [showRsi, setShowRsi] = useState(true);
  const [showMacd, setShowMacd] = useState(true);

  const [data, setData] = useState<ChartData | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const [posPage, setPosPage] = useState(1);
  const [posPageSize, setPosPageSize] = useState(25);
  const [live, setLive] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);

  const reqSeq = useRef(0);
  const loadingMoreRef = useRef(false);

  // Realtime stream (WS): price quotes + open-position P&L, read-only.
  const {
    quotes: liveQuotes,
    positions: livePositions,
    status: liveStatus,
    lastUpdate: liveUpdate,
  } = useLiveQuotes({ symbols, positions: true, enabled: live });

  const load = useCallback(async () => {
    const seq = ++reqSeq.current;
    setError(null);
    try {
      const qs = new URLSearchParams({ symbol, timeframe, bars: String(bars) });
      // Parallel fetch candlestick & analysis
      const [candlesRes, analysisRes] = await Promise.all([
        apiFetch(`/chart/candles?${qs}`),
        apiFetch(`/chart/analysis?${qs}`),
      ]);
      // Handle candlestick response
      if (!candlesRes.ok) {
        const msg = candlesRes.status === 401
          ? 'Sesi tidak terautentikasi. Masuk dulu.'
          : `Permintaan chart gagal (HTTP ${candlesRes.status}).`;
        if (seq === reqSeq.current) setError(msg);
        return;
      }
      const chartBody: ChartData = await candlesRes.json();
      if (seq !== reqSeq.current) return;
      setData(chartBody);
      setUpdatedAt(new Date());
      if (chartBody.ok && chartBody.symbol) {
        setSymbols(prev => (prev.includes(chartBody.symbol!) ? prev : [...prev, chartBody.symbol!]));
      }
      // Handle analysis response (optional)
      if (analysisRes.ok) {
        const aBody: AnalysisData = await analysisRes.json();
        if (seq === reqSeq.current) setAnalysis(aBody);
      } else if (seq === reqSeq.current) {
        setAnalysis(null);
      }
    } catch {
      if (seq === reqSeq.current) setError('Tidak bisa menghubungi API. Periksa Node pada :3789.');
    } finally {
      if (seq === reqSeq.current) setLoading(false);
    }
  }, [symbol, timeframe, bars]);

  useAutoRefresh(load);

  // Lazy-load older history when the chart is panned to its left edge. Fetches
  // the previous window (`before` = oldest loaded bar) and PREPENDS it to every
  // series so the chart extends seamlessly — the viewport stays anchored on the
  // same bars (PriceChart shifts the window forward by the prepended count).
  const loadMoreHistory = useCallback(async () => {
    if (loadingMoreRef.current) return;
    const cur = data;
    const oldest = cur?.bars?.[0]?.time;
    if (!cur?.ok || !oldest || !cur.has_more) return;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const qs = new URLSearchParams({
        symbol,
        timeframe,
        bars: String(bars),
        before: oldest,
      });
      const res = await apiFetch(`/chart/candles?${qs}`);
      if (!res.ok) return;
      const older: ChartData = await res.json();
      if (!older.ok || !older.bars?.length) return;
      setData((prev) => {
        if (!prev?.ok || !prev.bars) return prev;
        // Guard against a duplicate page (e.g. double trigger).
        if (prev.bars[0]?.time === older.bars![0]?.time) return prev;
        const merge = (a?: (number | null)[], b?: (number | null)[]) => [...(b ?? []), ...(a ?? [])];
        const prevOv = prev.overlays;
        const ov = older.overlays;
        return {
          ...prev,
          bars: [...older.bars!, ...prev.bars],
          has_more: older.has_more,
          overlays: {
            ema_fast: { period: prevOv?.ema_fast.period ?? 20, values: merge(prevOv?.ema_fast.values, ov?.ema_fast.values) },
            ema_slow: { period: prevOv?.ema_slow.period ?? 50, values: merge(prevOv?.ema_slow.values, ov?.ema_slow.values) },
            bollinger: prevOv?.bollinger
              ? {
                  period: prevOv.bollinger.period,
                  std: prevOv.bollinger.std,
                  upper: merge(prevOv.bollinger.upper, ov?.bollinger?.upper),
                  middle: merge(prevOv.bollinger.middle, ov?.bollinger?.middle),
                  lower: merge(prevOv.bollinger.lower, ov?.bollinger?.lower),
                }
              : null,
          },
          panels: {
            rsi: prev.panels?.rsi ? { period: prev.panels.rsi.period, values: merge(prev.panels.rsi.values, older.panels?.rsi?.values) } : null,
            macd:
              prev.panels?.macd && older.panels?.macd
                ? {
                    fast: prev.panels.macd.fast,
                    slow: prev.panels.macd.slow,
                    signal: prev.panels.macd.signal,
                    line: merge(prev.panels.macd.line, older.panels.macd.line),
                    signal_line: merge(prev.panels.macd.signal_line, older.panels.macd.signal_line),
                    histogram: merge(prev.panels.macd.histogram, older.panels.macd.histogram),
                  }
                : prev.panels?.macd ?? null,
          },
          provenance: {
            ...prev.provenance,
            source: prev.provenance?.source ?? 'mt5',
            mode: prev.provenance?.mode ?? 'live-read-only',
            bar_count: prev.bars.length + older.bars!.length,
          },
        };
      });
    } catch {
      /* best-effort; a failed history load just leaves the current window */
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, [data, symbol, timeframe, bars]);

  const submitSymbol = (e: React.FormEvent) => { e.preventDefault(); const s = symbolInput.trim().toUpperCase(); if (s) setSymbol(s); };

  // Live quote for the charted symbol (WS). Null when the stream has no value
  // yet — never a fabricated number.
  const liveQuote = liveQuotes[symbol] ?? null;
  const livePrice = liveQuote?.last ?? liveQuote?.bid ?? null;

  // Build chart level overlays: analysis + open positions
  const chartLevels: ChartLevel[] = [];
  if (analysis?.ok && analysis.analysis) {
    const a = analysis.analysis;
    if (a.signal !== 'HOLD') chartLevels.push({ label: 'Entry', value: a.entry, kind: 'entry' });
    if (typeof a.stop_loss === 'number') chartLevels.push({ label: 'SL', value: a.stop_loss, kind: 'stop' });
    if (typeof a.take_profit === 'number') chartLevels.push({ label: 'TP', value: a.take_profit, kind: 'target' });
  }
  if (analysis?.positions) {
    for (const p of analysis.positions) {
      if (typeof p.sl === 'number') chartLevels.push({ label: `SL #${p.ticket}`, value: p.sl, kind: 'stop' });
      if (typeof p.tp === 'number') chartLevels.push({ label: `TP #${p.ticket}`, value: p.tp, kind: 'target' });
    }
  }
  // Live last price drawn as an entry-style line so it moves with the stream.
  if (typeof livePrice === 'number' && Number.isFinite(livePrice)) {
    chartLevels.push({ label: 'Harga kini', value: livePrice, kind: 'entry' });
  }

  const barCount = data?.bars?.length ?? 0;
  const prov = data?.provenance;

  // Merge open positions (from /chart/analysis) with the live stream by ticket
  // so price/profit tick without refetching the chart. Server truth wins for
  // SL/TP/entry; only the moving fields take the live value.
  const liveByTicket = new Map<string, LivePosition>();
  for (const p of livePositions ?? []) {
    if (p && p.ticket != null) liveByTicket.set(String(p.ticket), p);
  }

  const allPositions = (analysis?.positions ?? []).map((p) => {
    const lp = liveByTicket.get(String(p.ticket));
    if (!lp) return p;
    const current = typeof lp.current === 'number' ? lp.current : (typeof lp.price_current === 'number' ? lp.price_current : p.current);
    const profit = typeof lp.profit === 'number' ? lp.profit : (typeof lp.unrealized_pnl === 'number' ? lp.unrealized_pnl : p.profit);
    return { ...p, current, profit };
  });
  const posPageCount = Math.max(1, Math.ceil(allPositions.length / posPageSize));
  const safePosPage = Math.min(posPage, posPageCount);
  const visiblePositions = allPositions.slice((safePosPage - 1) * posPageSize, safePosPage * posPageSize);

  return (
    <AppShell
      activeKey="market"
      eyebrow="EA BOT / PASAR"
      title="Pasar"
      actions={
        <>
          <label className={styles.liveToggle} title="Streaming harga & P&L via WebSocket">
            <input type="checkbox" checked={live} onChange={e => setLive(e.target.checked)} />
            <span className={`liveDot ${live ? (liveStatus === 'live' ? 'liveOn' : 'liveOff') : 'liveOff'}`} />
            Live
            {live && liveStatus !== 'live' ? ` · ${liveStatus}` : ''}
          </label>
          <button type="button" className={styles.refreshBtn} onClick={load} disabled={loading}>
            {loading ? 'Memuat…' : 'Muat ulang'}
          </button>
        </>
      }
    >
      {/* Controls */}
      <section className={styles.controls}>
        <form className={styles.symbolForm} onSubmit={submitSymbol}>
          <label htmlFor="symbolInput" className={styles.ctlLabel}>Simbol</label>
          <div className={styles.symbolRow}>
            <input id="symbolInput" className={styles.symbolInput} value={symbolInput}
              onChange={e => setSymbolInput(e.target.value)} placeholder="mis. XAUUSD" spellCheck={false} />
            <button type="submit" className={styles.goBtn}>Tampilkan</button>
          </div>
          <div className={styles.symbolChips}>
            {symbols.map(s => (
              <button key={s} type="button"
                className={`${styles.chip} ${s === symbol ? styles.chipActive : ''}`}
                onClick={() => { setSymbol(s); setSymbolInput(s); }}>
                {s}
              </button>
            ))}
          </div>
        </form>

        <div className={styles.tfBlock}>
          <span className={styles.ctlLabel}>Timeframe</span>
          <div className={styles.tfRow} role="group" aria-label="Pilih timeframe">
            {TIMEFRAMES.map(tf => (
              <button key={tf} type="button" className={`${styles.tfBtn} ${tf === timeframe ? styles.tfActive : ''}`}
                aria-pressed={tf === timeframe} onClick={() => setTimeframe(tf)}>
                {tf}
              </button>
            ))}
          </div>
          <label className={styles.barsRow}>
            <span className={styles.ctlLabel}>Jumlah bar</span>
            <select className={styles.barsSelect} value={bars} onChange={e => setBars(Number(e.target.value))}>
              {[100,200,300,500].map(n => (<option key={n} value={n}>{n}</option>))}
            </select>
          </label>
        </div>

        <div className={styles.toggleBlock}>
          <span className={styles.ctlLabel}>Indikator</span>
          <div className={styles.toggleRow}>
            <label className={styles.toggle}>
              <input type="checkbox" checked={showEma} onChange={e => setShowEma(e.target.checked)} />
              <span>EMA 20/50</span>
            </label>
            <label className={styles.toggle}>
              <input type="checkbox" checked={showBollinger} onChange={e => setShowBollinger(e.target.checked)} />
              <span>Bollinger 20</span>
            </label>
            <label className={styles.toggle}>
              <input type="checkbox" checked={showRsi} onChange={e => setShowRsi(e.target.checked)} />
              <span>RSI 14</span>
            </label>
            <label className={styles.toggle}>
              <input type="checkbox" checked={showMacd} onChange={e => setShowMacd(e.target.checked)} />
              <span>MACD 12/26/9</span>
            </label>
          </div>
        </div>
      </section>

      {/* Metadata */}
      <div className={styles.metaRow}>
        <span className={styles.metaItem}>{data?.symbol ?? symbol} · {data?.timeframe ?? timeframe}</span>
        {typeof livePrice === 'number' ? (
          <span className={`${styles.metaItem} ${styles.livePrice}`}>
            <span className={`liveDot ${liveStatus === 'live' ? 'liveOn' : 'liveOff'}`} />
            {fmtLive(livePrice)}
            {liveQuote?.bid != null && liveQuote?.ask != null ? (
              <span className={styles.liveSub}> · b {fmtLive(liveQuote.bid)} / a {fmtLive(liveQuote.ask)}</span>
            ) : null}
          </span>
        ) : null}
        {prov ? (<span className={styles.metaItem}>{barCount} bar · sumber {prov.source} · mode {prov.mode}</span>) : null}
        {liveUpdate ? (<span className={styles.metaItem}>live {liveUpdate.toLocaleTimeString('id-ID')}</span>) : null}
        {updatedAt ? (<span className={styles.metaItem}>chart {updatedAt.toLocaleTimeString('id-ID')}</span>) : null}
      </div>

      {error && <div className={styles.errorBox}>{error}</div>}

      {/* Chart */}
      {data ? (
        <PriceChart data={data} showEma={showEma} showBollinger={showBollinger} showRsi={showRsi} showMacd={showMacd} levels={chartLevels} onNeedMoreHistory={loadMoreHistory} loadingMore={loadingMore} />
      ) : (
        <div className={styles.loadingBox}>{loading ? 'Memuat chart…' : 'Chart belum tersedia.'}</div>
      )}

      <p className={styles.note}>Data bar diambil read‑only dari terminal MT5 aktif. Indikator dihitung dari bar yang sama sehingga tidak ada perbedaan dengan engine.</p>

      {/* Analysis block */}
      {analysis && !analysis.ok && (
        <div className={styles.errorBox}>{analysis.reason ?? 'Analisa engine tidak tersedia.'}</div>
      )}
      {analysis?.ok && analysis.analysis && (
        <section className={styles.analysisBox}>
          <div className={styles.analysisHead}>
            <span className={`${styles.signalBadge} ${analysis.analysis.signal === 'BUY' ? styles.signalBuy : analysis.analysis.signal === 'SELL' ? styles.signalSell : styles.signalHold}`}>
              {analysis.analysis.signal}
            </span>
            <span className={styles.analysisMeta}>
              keyakinan {(analysis.analysis.confidence * 100).toFixed(0)}%{analysis.analysis.atr ? ` · ATR ${analysis.analysis.atr.toFixed(2)}` : ''}{analysis.provenance ? ` · risiko ${analysis.provenance.risk_percent}%/trade` : ''}
            </span>
          </div>
          <div className={styles.levelGrid}>
            <div className={styles.levelItem}>
              <span className={styles.levelLabel}>Entry</span>
              <span className={styles.levelValue}>{analysis.analysis.signal === 'HOLD' ? '—' : analysis.analysis.entry.toFixed(2)}</span>
            </div>
            <div className={styles.levelItem}>
              <span className={styles.levelLabel}>Stop Loss</span>
              <span className={`${styles.levelValue} ${styles.levelStop}`}>{typeof analysis.analysis.stop_loss === 'number' ? analysis.analysis.stop_loss.toFixed(2) : '—'}</span>
            </div>
            <div className={styles.levelItem}>
              <span className={styles.levelLabel}>Take Profit</span>
              <span className={`${styles.levelValue} ${styles.levelTarget}`}>{typeof analysis.analysis.take_profit === 'number' ? analysis.analysis.take_profit.toFixed(2) : '—'}</span>
            </div>
            <div className={styles.levelItem}>
              <span className={styles.levelLabel}>Harga kini</span>
              <span className={styles.levelValue}>
                {typeof livePrice === 'number'
                  ? <LiveNumber value={livePrice} format={fmtLive} />
                  : analysis.analysis.close.toFixed(2)}
              </span>
            </div>
          </div>
          <p className={styles.analysisReason}>{analysis.analysis.reason}</p>
          {analysis.provenance && (
            <p className={styles.analysisProv}>SL {analysis.provenance.stop_multiplier}×ATR · TP {analysis.provenance.reward_risk_ratio}:1 (≈{(analysis.provenance.stop_multiplier * analysis.provenance.reward_risk_ratio).toFixed(0)}×ATR) · mesin {analysis.provenance.engine} · read‑only</p>
          )}
        </section>
      )}

      {/* Open positions table (analysis + live stream merged) */}
      {allPositions.length > 0 && (
        <section className={styles.posBox}>
          <h2 className={styles.posTitle}>
            Posisi terbuka · {analysis?.symbol ?? symbol}
            {liveStatus === 'live' && livePositions && livePositions.length > 0 ? (
              <span className={styles.posLiveTag}><span className="liveDot liveOn" />live</span>
            ) : null}
          </h2>
          <div className={styles.posTableWrap}>
            <table className={styles.posTable}>
              <thead>
                <tr>
                  <th>Ticket</th><th>Arah</th><th>Lot</th><th>Entry</th><th>Kini</th><th>SL</th><th>TP</th><th>Profit</th>
                </tr>
              </thead>
              <tbody>
                {visiblePositions.map(p => (
                  <tr key={p.ticket}>
                    <td className={styles.posMono}>{p.ticket}</td>
                    <td><span className={`${styles.sideBadge} ${p.side === 'BUY' ? styles.sideBuy : styles.sideSell}`}>{p.side}</span></td>
                    <td className={styles.posMono}>{p.volume}</td>
                    <td className={styles.posMono}>{p.entry.toFixed(2)}</td>
                    <td className={styles.posMono}>
                      <LiveNumber value={p.current} format={fmtLive} />
                    </td>
                    <td className={styles.posMono}>{p.sl !== null ? p.sl.toFixed(2) : '—'}</td>
                    <td className={styles.posMono}>{p.tp !== null ? p.tp.toFixed(2) : '—'}</td>
                    <td className={p.profit >= 0 ? styles.positive : styles.negative}>
                      <LiveNumber value={p.profit} format={(v) => v.toFixed(2)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            page={safePosPage}
            pageSize={posPageSize}
            total={allPositions.length}
            onPageChange={setPosPage}
            onPageSizeChange={setPosPageSize}
            unitLabel="positions"
          />
        </section>
      )}
    </AppShell>
  );
}
