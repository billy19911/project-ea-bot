'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import styles from './page.module.css';
import { apiFetch } from '../../lib/api';
import AppShell from '../../components/AppShell';

// ── Strategy type definitions matching the backtest engine ─────────────────

type ParamDef = {
  key: string;
  label: string;
  default: number;
  step?: string;
  min?: number;
  max?: number;
};

type StrategyType = {
  id: string;
  label: string;
  description: string;
  parameters: ParamDef[];
};

const STRATEGY_TYPES: StrategyType[] = [
  {
    id: 'ema_crossover',
    label: 'EMA Crossover',
    description: 'Sinyal dari perpotongan EMA cepat & lambat.',
    parameters: [
      { key: 'fast_ema_period', label: 'Fast EMA Period', default: 3, min: 1 },
      { key: 'slow_ema_period', label: 'Slow EMA Period', default: 8, min: 2 },
      { key: 'atr_period', label: 'ATR Period', default: 14, min: 2 },
      { key: 'atr_stop_multiplier', label: 'ATR Stop Multiplier', default: 2.0, step: '0.1', min: 0.1 },
      { key: 'reward_risk_ratio', label: 'Reward/Risk Ratio', default: 2.0, step: '0.1', min: 0.1 },
    ],
  },
  {
    id: 'rsi_reversal',
    label: 'RSI Reversal',
    description: 'Entry mean-reversion dari RSI oversold/overbought.',
    parameters: [
      { key: 'rsi_period', label: 'RSI Period', default: 14, min: 1 },
      { key: 'rsi_overbought', label: 'RSI Overbought', default: 70, min: 50, max: 100 },
      { key: 'rsi_oversold', label: 'RSI Oversold', default: 30, min: 0, max: 50 },
      { key: 'atr_period', label: 'ATR Period', default: 14, min: 2 },
      { key: 'atr_stop_multiplier', label: 'ATR Stop Multiplier', default: 2.0, step: '0.1', min: 0.1 },
      { key: 'reward_risk_ratio', label: 'Reward/Risk Ratio', default: 2.0, step: '0.1', min: 0.1 },
    ],
  },
  {
    id: 'macd_crossover',
    label: 'MACD Crossover',
    description: 'Entry dari perpotongan MACD line/signal.',
    parameters: [
      { key: 'macd_fast_period', label: 'MACD Fast Period', default: 12, min: 1 },
      { key: 'macd_slow_period', label: 'MACD Slow Period', default: 26, min: 2 },
      { key: 'macd_signal_period', label: 'MACD Signal Period', default: 9, min: 1 },
      { key: 'atr_period', label: 'ATR Period', default: 14, min: 2 },
      { key: 'atr_stop_multiplier', label: 'ATR Stop Multiplier', default: 2.0, step: '0.1', min: 0.1 },
      { key: 'reward_risk_ratio', label: 'Reward/Risk Ratio', default: 2.0, step: '0.1', min: 0.1 },
    ],
  },
];

function defaultParamsFor(typeId: string): Record<string, number> {
  const type = STRATEGY_TYPES.find((t) => t.id === typeId) ?? STRATEGY_TYPES[0];
  const params: Record<string, number> = {};
  for (const p of type.parameters) params[p.key] = p.default;
  return params;
}

export default function StrategyLabPage() {
  const router = useRouter();
  const [name, setName] = useState('');
  const [version, setVersion] = useState('v1.0.0');
  const [description, setDescription] = useState('');
  const [strategyType, setStrategyType] = useState('ema_crossover');
  const [parameters, setParameters] = useState<Record<string, number>>(
    defaultParamsFor('ema_crossover'),
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const activeType = STRATEGY_TYPES.find((t) => t.id === strategyType) ?? STRATEGY_TYPES[0];

  const handleTypeChange = (id: string) => {
    setStrategyType(id);
    setParameters(defaultParamsFor(id));
  };

  const handleParamChange = (key: string, value: string) => {
    setParameters({ ...parameters, [key]: Number(value) });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setSubmitting(true);

    try {
      const payload = {
        name: name.trim(),
        version: version.trim(),
        description: description.trim(),
        parameters: {
          strategy_type: strategyType,
          ...parameters,
        },
      };

      const res = await apiFetch('/strategies', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
        const detail =
          data.reason || data.detail || data.error || `Gagal membuat strategi (HTTP ${res.status})`;
        throw new Error(detail);
      }

      const data = await res.json();
      setSuccess(
        `Strategi ${data.strategy?.name ?? payload.name} v${data.strategy?.version ?? payload.version} berhasil dibuat! Mengalihkan…`,
      );

      setTimeout(() => {
        router.push('/strategy');
      }, 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Gagal membuat strategi');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AppShell
      activeKey="strategy-lab"
      eyebrow="EA BOT / LABORATORIUM STRATEGI"
      title="Laboratorium Strategi"
    >
      <div className={styles.pageBody}>
        {error && <div className={styles.errorCard}>{error}</div>}
        {success && <div className={styles.notice}>{success}</div>}

        <section className={styles.card}>
          <h2>Buat Strategi Baru</h2>
          <p className={styles.hint}>
            Strategi baru tersimpan sebagai versi DRAFT di registry. Validasi lewat backtest
            sebelum mengaktifkannya dari halaman Pusat Strategi.
          </p>

          <form onSubmit={handleSubmit} className={styles.form}>
            <div className={styles.formSection}>
              <h3>Informasi Dasar</h3>
              <div className={styles.formGroup}>
                <label htmlFor="name">Nama Strategi *</label>
                <input
                  id="name"
                  type="text"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g., EMA-XAUUSD-H1"
                />
              </div>

              <div className={styles.formGroup}>
                <label htmlFor="version">Versi *</label>
                <input
                  id="version"
                  type="text"
                  required
                  value={version}
                  onChange={(e) => setVersion(e.target.value)}
                  placeholder="v1.0.0"
                />
              </div>

              <div className={styles.formGroup}>
                <label htmlFor="description">Deskripsi</label>
                <textarea
                  id="description"
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Jelaskan logika entry/exit dan konteks regime pasar strategi ini"
                />
              </div>
            </div>

            <div className={styles.formSection}>
              <h3>Tipe Strategi</h3>
              <div className={styles.typeGrid}>
                {STRATEGY_TYPES.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    className={t.id === strategyType ? styles.typeCardActive : styles.typeCard}
                    onClick={() => handleTypeChange(t.id)}
                  >
                    <strong>{t.label}</strong>
                    <small>{t.description}</small>
                  </button>
                ))}
              </div>
            </div>

            <div className={styles.formSection}>
              <h3>Parameter {activeType.label}</h3>
              <div className={styles.paramGrid}>
                {activeType.parameters.map((p) => (
                  <div key={p.key} className={styles.formGroup}>
                    <label htmlFor={p.key}>{p.label}</label>
                    <input
                      id={p.key}
                      type="number"
                      step={p.step ?? '1'}
                      min={p.min}
                      max={p.max}
                      value={parameters[p.key] ?? p.default}
                      onChange={(e) => handleParamChange(p.key, e.target.value)}
                    />
                  </div>
                ))}
              </div>
            </div>

            <div className={styles.formActions}>
              <button
                type="button"
                onClick={() => router.push('/strategy')}
                className={styles.btnSecondary}
              >
                Batal
              </button>
              <button type="submit" disabled={submitting} className={styles.btnPrimary}>
                {submitting ? 'Membuat…' : 'Buat Strategi'}
              </button>
            </div>
          </form>
        </section>
      </div>
    </AppShell>
  );
}
