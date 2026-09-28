/**
 * labels.ts — peta label manusiawi (Bahasa Indonesia) untuk nilai/identifier
 * teknis yang ditampilkan di dashboard.
 *
 * Prinsip: UI tidak boleh menampilkan kunci mentah (snake_case) sebagai label
 * utama. Setiap identifier yang muncul punya judul manusiawi di sini; bila
 * belum dipetakan, `humanize()` jadi fallback yang tetap terbaca (mis.
 * `missing_in_broker` -> "Missing in broker"). Kunci teknis aslinya boleh
 * tetap ditampilkan kecil (kode) sebagai jejak audit — tapi bukan sebagai
 * satu-satunya teks yang dilihat operator.
 */

/** Ubah snake_case / kebab-case menjadi frasa berjudul yang terbaca. */
export function humanize(key: string): string {
  if (!key) return '';
  const spaced = key
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .trim();
  if (!spaced) return key;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Ambil label dari `map`, atau `humanize(key)` bila tidak ada. */
export function labelFor(map: Record<string, string>, key: string): string {
  return map[key] ?? humanize(key);
}

// ---------------------------------------------------------------------------
// Knob runtime (Settings) — judul manusiawi + bantuan fungsi.
// Sumber kebenaran `description`/`applied_to` tetap dari backend
// (services/python/src/system/settings_store.py); di sini hanya judul singkat.
// ---------------------------------------------------------------------------
export const KNOB_LABELS: Record<string, string> = {
  supervisor_token_budget: 'Anggaran token supervisor',
  scheduler_poll_interval: 'Jeda poll scheduler (detik)',
  llm_advisor_enabled: 'Penasihat LLM aktif',
  trend_sample_interval: 'Jeda sampel grafik tren (detik)',
  risk_per_trade_pct: 'Risiko per transaksi (% equity)',
  max_lot_per_trade: 'Maksimum lot per transaksi',
  sltp_management_enabled: 'Manajemen SL/TP dinamis',
  sltp_breakeven_enabled: 'Geser SL ke break-even saat TP1',
  sltp_progressive_enabled: 'Kunci profit saat TP2',
  sltp_trailing_enabled: 'Trailing stop setelah TP2',
  fanout_enabled: 'Fan-out ke banyak terminal MT5',
  zone_entry_enabled: 'Entry tunggu zona OB/FVG',
};

/** Bantuan singkat (ditampilkan dalam tooltip) untuk knob runtime. */
export const KNOB_HELP: Record<string, string> = {
  supervisor_token_budget:
    'Batas estimasi token per siklus supervisor. Bila terlampaui, agen berikutnya dilewati. ' +
    'Menurunkan nilai = lebih ketat.',
  scheduler_poll_interval:
    'Jeda antar-poll loop scheduler (detik). Minimal 0.1 detik agar loop tidak berputar terlalu cepat.',
  llm_advisor_enabled:
    'Mengizinkan panggilan LLM 9Router sebagai penasihat. Default NONAKTIF — tidak ada token terpakai sampai diaktifkan.',
  trend_sample_interval:
    'Jeda antar-sampel grafik tren (detik). Makin besar = riwayat tren makin panjang.',
  risk_per_trade_pct:
    'Risiko per entry sebagai persen dari equity/balance. Ukuran lot dihitung dari jarak stop loss.',
  max_lot_per_trade:
    'Batas maksimum ukuran lot per entry — pengaman agar tidak over-sized.',
  sltp_management_enabled:
    'Saklar induk manajemen SL dinamis. Saat NONAKTIF tidak ada modifikasi SL yang dikirim ke broker.',
  sltp_breakeven_enabled:
    'Saat harga mencapai TP1 (1R), SL digeser ke break-even plus buffer kecil (anti rugi).',
  sltp_progressive_enabled:
    'Saat harga mencapai TP2 (2R), SL dinaikkan ke level TP1 (profit terkunci).',
  sltp_trailing_enabled:
    'Trailing stop berbasis ATR — hanya aktif setelah harga melewati TP2.',
  fanout_enabled:
    'Satu analisa dikirim ke SEMUA terminal MT5 yang running + execution:true + di-arm. ' +
    'Default NONAKTIF. Uji di DEMO dulu sebelum dipakai di akun LIVE.',
  zone_entry_enabled:
    'Entry menunggu harga masuk zona Order Block / Fair Value Gap searah bias ' +
    '(M30/H1 untuk bias, M5 untuk zona) sebelum order dikirim. Default NONAKTIF.',
};

// ---------------------------------------------------------------------------
// Batas risiko (read-only, dari RiskGate / RiskEngine).
// ---------------------------------------------------------------------------
export const RISK_LABELS: Record<string, string> = {
  max_drawdown: 'Maksimum drawdown (fraksi ekuitas)',
  daily_loss_limit: 'Batas rugi harian (fraksi ekuitas)',
  max_exposure: 'Maksimum exposure (fraksi ekuitas)',
  margin_threshold: 'Ambang margin',
  max_positions: 'Maksimum posisi terbuka',
  max_spread_pips: 'Maksimum spread (pips)',
  min_rr: 'Minimum risk/reward',
};

// ---------------------------------------------------------------------------
// Parameter strategi / backtest.
// ---------------------------------------------------------------------------
export const PARAM_LABELS: Record<string, string> = {
  fast_ema_period: 'Periode EMA cepat',
  slow_ema_period: 'Periode EMA lambat',
  rsi_period: 'Periode RSI',
  rsi_overbought: 'Ambang RSI overbought',
  rsi_oversold: 'Ambang RSI oversold',
  macd_fast_period: 'Periode MACD cepat',
  macd_slow_period: 'Periode MACD lambat',
  macd_signal_period: 'Periode sinyal MACD',
  atr_period: 'Periode ATR',
  atr_stop_multiplier: 'Pengali stop ATR',
  reward_risk_ratio: 'Rasio reward/risk',
  fast_period: 'Periode cepat',
  slow_period: 'Periode lambat',
  signal_period: 'Periode sinyal',
  lookback: 'Jendela lookback',
  threshold: 'Ambang batas',
  max_hold_bars: 'Maksimum bar posisi ditahan',
};

// ---------------------------------------------------------------------------
// Kolom tabel (walk-forward, dll) yang berasal dari kunci JSON mentah.
// ---------------------------------------------------------------------------
export const COLUMN_LABELS: Record<string, string> = {
  window: 'Jendela',
  index: 'Indeks',
  train_start: 'Mulai latih',
  train_end: 'Selesai latih',
  test_start: 'Mulai uji',
  test_end: 'Selesai uji',
  train_bars: 'Bar latih',
  test_bars: 'Bar uji',
  in_sample: 'In-sample',
  out_of_sample: 'Out-of-sample',
  trades: 'Transaksi',
  trades_total: 'Total transaksi',
  win_rate: 'Rasio menang',
  pnl: 'P&L',
  net_pnl: 'P&L bersih',
  profit_factor: 'Profit factor',
  sharpe: 'Sharpe',
  sortino: 'Sortino',
  max_drawdown: 'Drawdown maksimum',
  return_pct: 'Return (%)',
  expectancy: 'Ekspektasi',
  total_return: 'Total return',
  start: 'Mulai',
  end: 'Selesai',
  symbol: 'Simbol',
  timeframe: 'Timeframe',
  status: 'Status',
  strategy_type: 'Tipe strategi',
  created_at: 'Dibuat',
  updated_at: 'Diperbarui',
};

// ---------------------------------------------------------------------------
// Kode enum.
// ---------------------------------------------------------------------------

/** Tingkat circuit breaker (multi-level breaker). */
export const BREAKER_LEVEL_LABELS: Record<string, string> = {
  normal: 'Normal',
  caution: 'Waspada',
  risk_reduced: 'Risiko dikurangi',
  entry_blocked: 'Entry diblokir',
  emergency_flatten: 'Tutup darurat semua posisi',
  halted: 'Dihentikan',
};

/** Pemicu circuit breaker. */
export const BREAKER_TRIGGER_LABELS: Record<string, string> = {
  spread_spike: 'Lonjakan spread',
  feed_stale: 'Feed data basi/terlambat',
  mt5_disconnected: 'MT5 terputus',
  daily_loss: 'Rugi harian',
  drawdown: 'Drawdown',
  reconciliation_mismatch: 'Rekonsiliasi tidak cocok',
  execution_rejection_spike: 'Lonjakan penolakan eksekusi',
  database_unavailable: 'Database tidak tersedia',
};

/** Jenis ketidakcocokan rekonsiliasi (ReconciliationReport). */
export const MISMATCH_KIND_LABELS: Record<string, string> = {
  missing_in_broker: 'Hilang di broker',
  missing_internal: 'Hilang di ledger internal',
  volume_mismatches: 'Volume tidak cocok',
  sltp_mismatches: 'SL/TP tidak cocok',
  symbol_mismatches: 'Simbol tidak cocok',
  magic_mismatches: 'Magic number tidak cocok',
  orphan_orders: 'Order yatim (tak dikenal)',
  matched: 'Cocok',
  matched_orders: 'Order cocok',
};

/** Hasil review transaksi. */
export const OUTCOME_LABELS: Record<string, string> = {
  win: 'Menang',
  loss: 'Kalah',
  breakeven: 'Impas',
  pending: 'Menunggu',
};

/** Tipe event pasar (EventTypes) — subset yang lazim tampil. */
export const EVENT_TYPE_LABELS: Record<string, string> = {
  TRADE_CLOSE: 'Posisi ditutup',
  RISK_DRAWDOWN: 'Risiko: drawdown',
  RISK_EXPOSURE: 'Risiko: exposure',
  RISK_MARGIN: 'Risiko: margin',
  TREND_BULLISH: 'Tren bullish',
  TREND_BEARISH: 'Tren bearish',
  TREND_NEUTRAL: 'Tren netral',
  TREND_STRENGTHENING: 'Tren menguat',
  TREND_WEAKENING: 'Tren melemah',
  MOMENTUM_BULLISH: 'Momentum bullish',
  MOMENTUM_BEARISH: 'Momentum bearish',
  MOMENTUM_DIVERGENCE: 'Divergensi momentum',
  VOLATILITY_EXPANDING: 'Volatilitas menguat',
  VOLATILITY_CONTRACTING: 'Volatilitas menurun',
  VOLATILITY_SPIKE: 'Lonjakan volatilitas',
  BREAKOUT: 'Breakout',
  BREAKDOWN: 'Breakdown',
  REVERSAL: 'Pembalikan arah',
  DOJI: 'Doji',
  GAP_UP: 'Gap naik',
  GAP_DOWN: 'Gap turun',
  EMA_CROSSOVER: 'Persilangan EMA',
  MACD_CROSSOVER: 'Persilangan MACD',
  RSI_OVERBOUGHT: 'RSI overbought',
  RSI_OVERSOLD: 'RSI oversold',
  STOCH_OVERBOUGHT: 'Stochastic overbought',
  STOCH_OVERSOLD: 'Stochastic oversold',
  DRAWDOWN_WARNING: 'Peringatan drawdown',
  EXPOSURE_LIMIT_REACHED: 'Batas exposure tercapai',
  LIQUIDITY_WARNING: 'Peringatan likuiditas',
};

// ---------------------------------------------------------------------------
// Label halaman (judul + eyebrow) — Bahasa Indonesia.
// Nav sidebar sengaja TIDAK diubah (kunci familiar tetap).
// ---------------------------------------------------------------------------
export const PAGE_TITLES: Record<string, string> = {
  overview: 'Pusat Komando',
  'control-plane': 'Control Panel',
  market: 'Pasar',
  news: 'Kalender Ekonomi USD',
  orders: 'Order',
  positions: 'Posisi',
  'trade-history': 'Posisi & Transaksi',
  decisions: 'Keputusan',
  'decision-replay': 'Replay Keputusan',
  'why-no-trade': 'Kenapa Tidak Trading',
  execution: 'Eksekusi',
  'risk-center': 'Pusat Risiko',
  risk: 'Pusat Risiko',
  'circuit-breaker': 'Circuit Breaker',
  incidents: 'Insiden',
  'execution-quality': 'Kualitas Eksekusi',
  reconciliation: 'Rekonsiliasi',
  observability: 'Observabilitas',
  slo: 'SLO Sistem',
  'ai-control': 'Pusat Kontrol AI',
  agents: 'Ruang Komite',
  models: 'Model & Observabilitas LLM',
  strategy: 'Strategi',
  'strategy-lab': 'Laboratorium Strategi',
  backtest: 'Backtest',
  learning: 'Pembelajaran',
  performance: 'Performa',
  research: 'Pusat Riset',
  'walk-forward': 'Walk-Forward',
  'monte-carlo': 'Monte Carlo',
  environment: 'Lingkungan',
  'system-health': 'Kesehatan Sistem',
  accounts: 'Akun & Broker',
  certification: 'Sertifikasi Produksi',
  audit: 'Jejak Audit',
  'system-readiness': 'Kesiapan Sistem',
  settings: 'Pengaturan',
};

/** Eyebrow seksi (format "Xynn / <Seksi>"). */
export const PAGE_EYEBROWS: Record<string, string> = {
  overview: 'Xynn / Ikhtisar',
  'control-plane': 'Xynn / Control Panel',
  market: 'Xynn / Pasar',
  news: 'Xynn / Berita',
  orders: 'Xynn / Order',
  positions: 'Xynn / Posisi',
  'trade-history': 'Xynn / Transaksi',
  decisions: 'Xynn / Keputusan',
  'decision-replay': 'Xynn / Keputusan',
  'why-no-trade': 'Xynn / Operasional',
  execution: 'Xynn / Eksekusi',
  'risk-center': 'Xynn / Risiko',
  risk: 'Xynn / Risiko',
  'circuit-breaker': 'Xynn / Risiko',
  incidents: 'Xynn / Insiden',
  'execution-quality': 'Xynn / Eksekusi',
  reconciliation: 'Xynn / Rekonsiliasi',
  observability: 'Xynn / Observabilitas',
  slo: 'Xynn / Observabilitas',
  'ai-control': 'Xynn / Kontrol AI',
  agents: 'Xynn / Agen',
  models: 'Xynn / AI',
  strategy: 'Xynn / Strategi',
  'strategy-lab': 'Xynn / Strategi',
  backtest: 'Xynn / Backtest',
  learning: 'Xynn / Pembelajaran',
  performance: 'Xynn / Performa',
  research: 'Xynn / Riset',
  'walk-forward': 'Xynn / Riset',
  'monte-carlo': 'Xynn / Riset',
  environment: 'Xynn / Keamanan',
  'system-health': 'Xynn / Sistem',
  accounts: 'Xynn / Sistem',
  certification: 'Xynn / Sistem',
  audit: 'Xynn / Audit',
  'system-readiness': 'Xynn / Sistem',
  settings: 'Xynn / Pengaturan',
};
