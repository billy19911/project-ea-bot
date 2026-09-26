'use client';

import { useEffect, useState } from 'react';
import styles from './page.module.css';
import { apiFetch } from '../../lib/api';
import AppShell from '../../components/AppShell';

// ── Types matching the real API contract (research/endpoints.py) ──────────

type StrategyInfo = {
  id: string;
  name: string;
  description: string;
  parameters: string[];
};

type Metrics = {
  total_trades: number;
  win_rate: number | null;
  profit_factor: number | null;
  sharpe_ratio: number | null;
  max_drawdown: number | null;
  expectation: number | null;
  net_pnl: number | null;
};

type Provenance = {
  symbol: string;
  symbol_resolved?: string | null;
  timeframe: string;
  bars: number;
  requested_bars?: number | null;
  mode?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  first_bar_time?: string | null;
  last_bar_time?: string | null;
  ran_at: string;
  source: string;
  account: { login: number | null; server: string | null; currency: string | null } | null;
};

type BacktestResponse = {
  ok: boolean;
  reason?: string;
  experiment?: { id: string; name: string };
  metrics?: Metrics | null;
  provenance?: Provenance | null;
  walk_forward?: { enabled: boolean; windows?: any[] } | null;
  trades_total?: number;
  trades_preview?: Array<Record<string, unknown>>;
};

// ── Strategy-specific default parameters ───────────────────────────────────

const DEFAULT_PARAMS: Record<string, Record<string, number>> = {
  ema_crossover: {
    fast_ema_period: 3,
    slow_ema_period: 8,
    atr_period: 14,
    atr_stop_multiplier: 2.0,
    reward_risk_ratio: 2.0,
  },
  rsi_reversal: {
    rsi_period: 14,
    rsi_overbought: 70,
    rsi_oversold: 30,
    atr_period: 14,
    atr_stop_multiplier: 2.0,
    reward_risk_ratio: 2.0,
  },
  macd_crossover: {
    macd_fast_period: 12,
    macd_slow_period: 26,
    macd_signal_period: 9,
    atr_period: 14,
    atr_stop_multiplier: 2.0,
    reward_risk_ratio: 2.0,
  },
};

// Human-readable labels for parameter keys
const PARAM_LABELS: Record<string, string> = {
  fast_ema_period: 'Fast EMA Period',
  slow_ema_period: 'Slow EMA Period',
  rsi_period: 'RSI Period',
  rsi_overbought: 'RSI Overbought',
  rsi_oversold: 'RSI Oversold',
  macd_fast_period: 'MACD Fast Period',
  macd_slow_period: 'MACD Slow Period',
  macd_signal_period: 'MACD Signal Period',
  atr_period: 'ATR Period',
  atr_stop_multiplier: 'ATR Stop Multiplier',
  reward_risk_ratio: 'Reward/Risk Ratio',
};

function fmt(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toFixed(digits);
}

function fmtPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${value.toFixed(digits)}%`;
}

export default function BacktestPage() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [strategyType, setStrategyType] = useState('ema_crossover');
  const [symbol, setSymbol] = useState('XAUUSD');
  const [timeframe, setTimeframe] = useState('H1');
  const [bars, setBars] = useState(500);
  const [dataMode, setDataMode] = useState<'bars' | 'range'>('bars');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [parameters, setParameters] = useState<Record<string, number>>(
    DEFAULT_PARAMS['ema_crossover'],
  );
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [error, setError] = useState('');
  const [loadingStrategies, setLoadingStrategies] = useState(true);

  // Load supported strategy types from GET /research/strategies
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await apiFetch('/research/strategies');
        if (!res.ok) return;
        const data = await res.json();
        if (active && Array.isArray(data?.strategies) && data.strategies.length > 0) {
          setStrategies(data.strategies);
          setStrategyType(data.strategies[0].id);
          setParameters(DEFAULT_PARAMS[data.strategies[0].id] ?? {});
        }
      } catch {
        // keep defaults if fetch fails
      } finally {
        if (active) setLoadingStrategies(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const handleStrategyChange = (id: string) => {
    setStrategyType(id);
    setParameters(DEFAULT_PARAMS[id] ? { ...DEFAULT_PARAMS[id] } : {});
  };

  const handleParamChange = (key: string, value: string) => {
    setParameters({ ...parameters, [key]: Number(value) });
  };

  const runBacktest = async () => {
    setError('');
    setResult(null);
    setRunning(true);

    try {
      // Step 1: Create an experiment with the selected strategy parameters.
      // The ExperimentCreate schema has fixed EMA fields, but strategy_type
      // selects the signal logic; RSI/MACD params ride along as overrides
      // via the version_key/parameters merge.
      const expPayload: Record<string, number | string> = {
        strategy_type: strategyType,
        ...parameters,
      };

      const expRes = await apiFetch('/research/experiments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(expPayload),
      });

      if (!expRes.ok) {
        const data = await expRes.json().catch(() => ({ detail: `HTTP ${expRes.status}` }));
        throw new Error(data.detail || data.error || 'Gagal membuat eksperimen');
      }

      const expData = await expRes.json();
      const experimentId = expData.experiment?.id;
      if (!experimentId) {
        throw new Error('Experiment ID tidak ditemukan dalam respons');
      }

      // Step 2: Run the backtest over real MT5 bars.
      // Build request body: bar-count or date-range mode.
      const btBody: Record<string, number | string> = {
        symbol: symbol.trim().toUpperCase(),
        timeframe,
      };
      if (dataMode === 'range' && startDate && endDate) {
        btBody.start_date = startDate;
        btBody.end_date = endDate;
      } else {
        btBody.bars = Number(bars) || 500;
      }

      const btRes = await apiFetch(`/research/experiments/${encodeURIComponent(experimentId)}/backtest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(btBody),
      });

      if (!btRes.ok) {
        const data = await btRes.json().catch(() => ({ detail: `HTTP ${btRes.status}` }));
        throw new Error(data.detail || data.error || 'Gagal menjalankan backtest');
      }

      const btData: BacktestResponse = await btRes.json();
      setResult(btData);
      if (!btData.ok && btData.reason) {
        setError(btData.reason);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Gagal menjalankan backtest');
    } finally {
      setRunning(false);
    }
  };

  const paramKeys = strategies.find((s) => s.id === strategyType)?.parameters ?? Object.keys(parameters);

  return (
    <AppShell activeKey="backtest" eyebrow="EA BOT / BACKTEST" title="Backtest Runner">
      <div className={styles.pageBody}>
        {error && <div className={styles.errorCard}>{error}</div>}

        <section className={styles.card}>
          <h2>Konfigurasi Backtest</h2>
          <p className={styles.notice}>
            Backtest berjalan di atas bar harga nyata dari terminal MT5 yang terhubung.
            Pastikan mode data live aktif.
          </p>

          <div className={styles.form}>
            <div className={styles.formRow}>
              <div className={styles.formGroup}>
                <label htmlFor="strategy">Strategi</label>
                {loadingStrategies ? (
                  <select disabled>
                    <option>Memuat strategi…</option>
                  </select>
                ) : strategies.length > 0 ? (
                  <select
                    id="strategy"
                    value={strategyType}
                    onChange={(e) => handleStrategyChange(e.target.value)}
                  >
                    {strategies.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <select
                    value={strategyType}
                    onChange={(e) => handleStrategyChange(e.target.value)}
                  >
                    <option value="ema_crossover">EMA Crossover</option>
                    <option value="rsi_reversal">RSI Reversal</option>
                    <option value="macd_crossover">MACD Crossover</option>
                  </select>
                )}
              </div>

              <div className={styles.formGroup}>
                <label htmlFor="symbol">Symbol</label>
                <input
                  id="symbol"
                  type="text"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                  placeholder="XAUUSD"
                />
              </div>

              <div className={styles.formGroup}>
                <label htmlFor="timeframe">Timeframe</label>
                <select
                  id="timeframe"
                  value={timeframe}
                  onChange={(e) => setTimeframe(e.target.value)}
                >
                  <option value="M1">M1</option>
                  <option value="M5">M5</option>
                  <option value="M15">M15</option>
                  <option value="M30">M30</option>
                  <option value="H1">H1</option>
                  <option value="H4">H4</option>
                  <option value="D1">D1</option>
                </select>
              </div>

              <div className={styles.formGroup}>
                <label htmlFor="dataMode">Data Mode</label>
                <select
                  id="dataMode"
                  value={dataMode}
                  onChange={(e) => setDataMode(e.target.value as 'bars' | 'range')}
                >
                  <option value="bars">Bar Count (last N)</option>
                  <option value="range">Date Range</option>
                </select>
              </div>

              {dataMode === 'bars' ? (
                <div className={styles.formGroup}>
                  <label htmlFor="bars">Bars</label>
                  <input
                    id="bars"
                    type="number"
                    min="100"
                    max="100000"
                    value={bars}
                    onChange={(e) => setBars(Number(e.target.value))}
                  />
                </div>
              ) : (
                <>
                  <div className={styles.formGroup}>
                    <label htmlFor="startDate">Start Date (UTC)</label>
                    <input
                      id="startDate"
                      type="datetime-local"
                      value={startDate}
                      onChange={(e) => setStartDate(e.target.value)}
                      placeholder="2023-01-01T00:00"
                    />
                  </div>
                  <div className={styles.formGroup}>
                    <label htmlFor="endDate">End Date (UTC)</label>
                    <input
                      id="endDate"
                      type="datetime-local"
                      value={endDate}
                      onChange={(e) => setEndDate(e.target.value)}
                      placeholder="2024-12-31T23:59"
                    />
                  </div>
                </>
              )}
            </div>

            <div className={styles.paramSection}>
              <h3>Parameter Strategi</h3>
              <div className={styles.paramGrid}>
                {paramKeys.map((key) => (
                  <div key={key} className={styles.formGroup}>
                    <label htmlFor={key}>{PARAM_LABELS[key] ?? key.replace(/_/g, ' ')}</label>
                    <input
                      id={key}
                      type="number"
                      step={typeof parameters[key] === 'number' && !Number.isInteger(parameters[key]) ? '0.1' : '1'}
                      value={parameters[key] ?? 0}
                      onChange={(e) => handleParamChange(key, e.target.value)}
                    />
                  </div>
                ))}
              </div>
            </div>

            <div className={styles.formActions}>
              <button
                type="button"
                onClick={runBacktest}
                disabled={running}
                className={styles.btnPrimary}
              >
                {running ? 'Menjalankan…' : 'Jalankan Backtest'}
              </button>
            </div>
          </div>
        </section>

        {result && result.metrics && (
          <section className={styles.card}>
            <h2>Hasil Backtest</h2>
            <div className={styles.metricsGrid}>
              <div className={styles.metricCard}>
                <small>Net PnL</small>
                <strong className={(result.metrics.net_pnl ?? 0) >= 0 ? styles.positive : styles.negative}>
                  {fmt(result.metrics.net_pnl, 2)}
                </strong>
              </div>
              <div className={styles.metricCard}>
                <small>Win Rate</small>
                <strong>{fmtPct(result.metrics.win_rate)}</strong>
              </div>
              <div className={styles.metricCard}>
                <small>Profit Factor</small>
                <strong>{fmt(result.metrics.profit_factor, 4)}</strong>
              </div>
              <div className={styles.metricCard}>
                <small>Sharpe Ratio</small>
                <strong>{fmt(result.metrics.sharpe_ratio, 4)}</strong>
              </div>
              <div className={styles.metricCard}>
                <small>Max Drawdown</small>
                <strong className={styles.negative}>{fmt(result.metrics.max_drawdown, 2)}</strong>
              </div>
              <div className={styles.metricCard}>
                <small>Expectation</small>
                <strong>{fmt(result.metrics.expectation, 4)}</strong>
              </div>
              <div className={styles.metricCard}>
                <small>Total Trades</small>
                <strong>{result.metrics.total_trades ?? '—'}</strong>
              </div>
            </div>

            {result.provenance && (
              <div className={styles.provenance}>
                <h3>Provenance</h3>
                <table className={styles.table}>
                  <tbody>
                    <tr><td>Symbol</td><td>{result.provenance.symbol_resolved || result.provenance.symbol}</td></tr>
                    <tr><td>Timeframe</td><td>{result.provenance.timeframe}</td></tr>
                    <tr><td>Mode</td><td>{result.provenance.mode === 'date_range' ? 'Date Range' : 'Bar Count'}</td></tr>
                    <tr><td>Bars</td><td>{result.provenance.bars}</td></tr>
                    {result.provenance.mode === 'date_range' && result.provenance.start_date && (
                      <tr><td>Start Date</td><td>{result.provenance.start_date}</td></tr>
                    )}
                    {result.provenance.mode === 'date_range' && result.provenance.end_date && (
                      <tr><td>End Date</td><td>{result.provenance.end_date}</td></tr>
                    )}
                    {result.provenance.first_bar_time && (
                      <tr><td>First Bar</td><td>{result.provenance.first_bar_time}</td></tr>
                    )}
                    {result.provenance.last_bar_time && (
                      <tr><td>Last Bar</td><td>{result.provenance.last_bar_time}</td></tr>
                    )}
                    <tr><td>Ran At</td><td>{result.provenance.ran_at}</td></tr>
                    <tr><td>Source</td><td>{result.provenance.source}</td></tr>
                    {result.provenance.account && (
                      <tr><td>Account</td><td>{result.provenance.account.login ?? '—'} / {result.provenance.account.server ?? '—'}</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}

            {result.trades_preview && result.trades_preview.length > 0 && (
              <div className={styles.tradesSection}>
                <h3>Trade Preview ({result.trades_total ?? result.trades_preview.length} total)</h3>
                <div className={styles.tableWrapper}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Side</th>
                        <th>Entry</th>
                        <th>Exit</th>
                        <th>PnL</th>
                        <th>Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.trades_preview.map((trade, idx) => {
                        const pnl = Number(trade.pnl ?? 0);
                        const side = String(trade.side ?? trade.type ?? '—');
                        return (
                          <tr key={idx}>
                            <td>{idx + 1}</td>
                            <td>
                              <span className={side.toUpperCase().includes('BUY') || side.toUpperCase().includes('LONG') ? styles.badgeBuy : styles.badgeSell}>
                                {side}
                              </span>
                            </td>
                            <td>{trade.entry_price != null ? Number(trade.entry_price).toFixed(5) : '—'}</td>
                            <td>{trade.exit_price != null ? Number(trade.exit_price).toFixed(5) : '—'}</td>
                            <td className={pnl >= 0 ? styles.positive : styles.negative}>
                              {fmt(pnl, 2)}
                            </td>
                            <td>{String(trade.exit_reason ?? '—')}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </section>
        )}

        {result && !result.ok && result.reason && !error && (
          <section className={styles.card}>
            <h2>Hasil Backtest</h2>
            <p className={styles.notice}>{result.reason}</p>
          </section>
        )}
      </div>
    </AppShell>
  );
}
