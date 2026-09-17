'use client';

// Halaman "Pasar" (Fase 1) — chart candlestick multi-timeframe.
//
// Sumber data: /chart/candles (Python → MT5 read-only). Nol data karangan:
// bila terminal tidak live atau simbol tidak punya bar, chart menampilkan
// alasan yang jujur alih-alih menggambar sesuatu yang tidak nyata.

import { useCallback, useEffect, useRef, useState } from 'react';
import styles from './page.module.css';
import { apiFetch } from '../../lib/api';
import AppShell from '../../components/AppShell';
import PriceChart, { ChartData } from '../../components/PriceChart';

const TIMEFRAMES = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1', 'MN1'] as const;
type Timeframe = (typeof TIMEFRAMES)[number];

const DEFAULT_SYMBOLS = ['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'BTCUSD'];

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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const reqSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++reqSeq.current;
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({
        symbol,
        timeframe,
        bars: String(bars),
      });
      const res = await apiFetch(`/chart/candles?${qs.toString()}`);
      if (!res.ok) {
        // 401 = belum login; pesan jujur, bukan chart kosong.
        const msg =
          res.status === 401
            ? 'Sesi tidak terautentikasi. Masuk dulu lewat halaman Masuk.'
            : `Permintaan chart gagal (HTTP ${res.status}).`;
        if (seq === reqSeq.current) setError(msg);
        return;
      }
      const body: ChartData = await res.json();
      if (seq !== reqSeq.current) return;
      setData(body);
      setUpdatedAt(new Date());
      if (body.ok && body.symbol) {
        setSymbols((prev) => (prev.includes(body.symbol!) ? prev : [...prev, body.symbol!]));
      }
    } catch {
      if (seq === reqSeq.current) setError('Tidak bisa menghubungi API. Cek apakah Node :3001 hidup.');
    } finally {
      if (seq === reqSeq.current) setLoading(false);
    }
  }, [symbol, timeframe, bars]);

  useEffect(() => {
    load();
  }, [load]);

  const submitSymbol = (e: React.FormEvent) => {
    e.preventDefault();
    const s = symbolInput.trim().toUpperCase();
    if (s) setSymbol(s);
  };

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
      {/* ── Kontrol: simbol + timeframe + jumlah bar ── */}
      <section className={styles.controls}>
        <form className={styles.symbolForm} onSubmit={submitSymbol}>
          <label htmlFor="symbolInput" className={styles.ctlLabel}>
            Simbol
          </label>
          <div className={styles.symbolRow}>
            <input
              id="symbolInput"
              className={styles.symbolInput}
              value={symbolInput}
              onChange={(e) => setSymbolInput(e.target.value)}
              placeholder="mis. XAUUSD"
              spellCheck={false}
            />
            <button type="submit" className={styles.goBtn}>
              Tampilkan
            </button>
          </div>
          <div className={styles.symbolChips}>
            {symbols.map((s) => (
              <button
                key={s}
                type="button"
                className={`${styles.chip} ${s === symbol ? styles.chipActive : ''}`}
                onClick={() => {
                  setSymbol(s);
                  setSymbolInput(s);
                }}
              >
                {s}
              </button>
            ))}
          </div>
        </form>

        <div className={styles.tfBlock}>
          <span className={styles.ctlLabel}>Timeframe</span>
          <div className={styles.tfRow} role="group" aria-label="Pilih timeframe">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                type="button"
                className={`${styles.tfBtn} ${tf === timeframe ? styles.tfActive : ''}`}
                aria-pressed={tf === timeframe}
                onClick={() => setTimeframe(tf)}
              >
                {tf}
              </button>
            ))}
          </div>
          <label className={styles.barsRow}>
            <span className={styles.ctlLabel}>Jumlah bar</span>
            <select
              className={styles.barsSelect}
              value={bars}
              onChange={(e) => setBars(Number(e.target.value))}
            >
              {[100, 200, 300, 500].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className={styles.toggleBlock}>
          <span className={styles.ctlLabel}>Indikator</span>
          <div className={styles.toggleRow}>
            <label className={styles.toggle}>
              <input type="checkbox" checked={showEma} onChange={(e) => setShowEma(e.target.checked)} />
              <span>EMA 20/50</span>
            </label>
            <label className={styles.toggle}>
              <input
                type="checkbox"
                checked={showBollinger}
                onChange={(e) => setShowBollinger(e.target.checked)}
              />
              <span>Bollinger 20</span>
            </label>
            <label className={styles.toggle}>
              <input type="checkbox" checked={showRsi} onChange={(e) => setShowRsi(e.target.checked)} />
              <span>RSI 14</span>
            </label>
            <label className={styles.toggle}>
              <input type="checkbox" checked={showMacd} onChange={(e) => setShowMacd(e.target.checked)} />
              <span>MACD 12/26/9</span>
            </label>
          </div>
        </div>
      </section>

      {/* ── Provenance: dari mana data ini ── */}
      <div className={styles.metaRow}>
        <span className={styles.metaItem}>
          {data?.symbol ?? symbol} · {data?.timeframe ?? timeframe}
        </span>
        {prov ? (
          <span className={styles.metaItem}>
            {barCount} bar · sumber {prov.source} · mode {prov.mode}
          </span>
        ) : null}
        {updatedAt ? (
          <span className={styles.metaItem}>
            diperbarui {updatedAt.toLocaleTimeString('id-ID')}
          </span>
        ) : null}
      </div>

      {error ? <div className={styles.errorBox}>{error}</div> : null}

      {/* ── Chart ── */}
      {data ? (
        <PriceChart
          data={data}
          showEma={showEma}
          showBollinger={showBollinger}
          showRsi={showRsi}
          showMacd={showMacd}
        />
      ) : (
        <div className={styles.loadingBox}>{loading ? 'Memuat chart…' : 'Chart belum tersedia.'}</div>
      )}

      <p className={styles.note}>
        Data bar diambil read-only dari terminal MT5 aktif. Indikator dihitung dari bar yang sama
        dengan yang dipakai mesin trading (EMA/RSI/MACD/Bollinger), sehingga angka di sini tidak
        bisa berbeda dari perhitungan engine. Warm-up indikator tampil sebagai garis putus — bukan
        nilai nol.
      </p>
    </AppShell>
  );
}
