'use client';

// Halaman "Pasar" (Fase 1) — chart candlestick multi-timeframe + indikator MT5.
// Data sumber: /chart/candles (candles) & /chart/analysis (engine analysis).
// Semua data read‑only; tidak ada nilai palsu, nilai null → garis putus.

import { useCallback, useEffect, useRef, useState } from 'react';
import styles from './page.module.css';
import { apiFetch } from '../../lib/api';
import AppShell from '../../components/AppShell';
import PriceChart, { ChartData, ChartLevel } from '../../components/PriceChart';

const TIMEFRAMES = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1', 'MN1'] as const;
type Timeframe = (typeof TIMEFRAMES)[number];

const DEFAULT_SYMBOLS = ['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'BTCUSD'];

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

  const reqSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++reqSeq.current;
    setLoading(true);
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
      if (seq === reqSeq.current) setError('Tidak bisa menghubungi API. Periksa Node pada :3001.');
    } finally {
      if (seq === reqSeq.current) setLoading(false);
    }
  }, [symbol, timeframe, bars]);

  useEffect(() => { load(); }, [load]);

  const submitSymbol = (e: React.FormEvent) => { e.preventDefault(); const s = symbolInput.trim().toUpperCase(); if (s) setSymbol(s); };

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

  const barCount = data?.bars?.length ?? 0;
  const prov = data?.provenance;

  return (
    <AppShell
      activeKey="market"
      eyebrow="EA BOT / PASAR"
      title="Pasar"
      actions={
        <button type="button" className={styles.refreshBtn} onClick={load} disabled={loading}>
          {loading ? 'Memuat…' : 'Muat ulang'}
        </button>
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
        {prov ? (<span className={styles.metaItem}>{barCount} bar · sumber {prov.source} · mode {prov.mode}</span>) : null}
        {updatedAt ? (<span className={styles.metaItem}>diperbarui {updatedAt.toLocaleTimeString('id-ID')}</span>) : null}
      </div>

      {error && <div className={styles.errorBox}>{error}</div>}

      {/* Chart */}
      {data ? (
        <PriceChart data={data} showEma={showEma} showBollinger={showBollinger} showRsi={showRsi} showMacd={showMacd} levels={chartLevels} />
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
              <span className={styles.levelValue}>{analysis.analysis.close.toFixed(2)}</span>
            </div>
          </div>
          <p className={styles.analysisReason}>{analysis.analysis.reason}</p>
          {analysis.provenance && (
            <p className={styles.analysisProv}>SL {analysis.provenance.stop_multiplier}×ATR · TP {analysis.provenance.reward_risk_ratio}:1 (≈{(analysis.provenance.stop_multiplier * analysis.provenance.reward_risk_ratio).toFixed(0)}×ATR) · mesin {analysis.provenance.engine} · read‑only</p>
          )}
        </section>
      )}

      {/* Open positions table */}
      {analysis?.positions && analysis.positions.length > 0 && (
        <section className={styles.posBox}>
          <h2 className={styles.posTitle}>Posisi terbuka · {analysis?.symbol ?? symbol}</h2>
          <div className={styles.posTableWrap}>
            <table className={styles.posTable}>
              <thead>
                <tr>
                  <th>Ticket</th><th>Arah</th><th>Lot</th><th>Entry</th><th>Kini</th><th>SL</th><th>TP</th><th>Profit</th>
                </tr>
              </thead>
              <tbody>
                {analysis.positions.map(p => (
                  <tr key={p.ticket}>
                    <td className={styles.posMono}>{p.ticket}</td>
                    <td><span className={`${styles.sideBadge} ${p.side === 'BUY' ? styles.sideBuy : styles.sideSell}`}>{p.side}</span></td>
                    <td className={styles.posMono}>{p.volume}</td>
                    <td className={styles.posMono}>{p.entry.toFixed(2)}</td>
                    <td className={styles.posMono}>{p.current.toFixed(2)}</td>
                    <td className={styles.posMono}>{p.sl !== null ? p.sl.toFixed(2) : '—'}</td>
                    <td className={styles.posMono}>{p.tp !== null ? p.tp.toFixed(2) : '—'}</td>
                    <td className={p.profit >= 0 ? styles.positive : styles.negative}>{p.profit.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </AppShell>
  );
}
