'use client';

import { useCallback, useEffect, useState } from 'react';
import AppShell from '../../components/AppShell';
import { apiFetch } from '../../lib/api';
import styles from './page.module.css';

type NewsItem = {
  headline: string;
  source: string;
  link?: string;
  published?: string;
  sentiment: number;
  impact: string;
};

type EconEvent = {
  title: string;
  country: string;
  date: string;
  datetime_utc?: string;
  impact: string;
  forecast?: string;
  previous?: string;
};

type Pattern = {
  event_key: string;
  samples: number;
  up: number;
  down: number;
  avg_return: number;
  reliable: boolean;
  status: string;
  bias: string;
};

type Summary = {
  symbol?: string;
  avg_sentiment?: number;
  high_impact_events?: number;
  top_positive?: string[];
  top_negative?: string[];
};

function impactClass(impact: string): string {
  switch ((impact || '').toUpperCase()) {
    case 'HIGH':
    case 'CRITICAL':
      return 'pillDanger';
    case 'MEDIUM':
      return 'pillWarn';
    default:
      return 'pillNeutral';
  }
}

function sentimentLabel(s: number): { text: string; cls: string } {
  if (s > 0.15) return { text: 'BULLISH', cls: 'pillOk' };
  if (s < -0.15) return { text: 'BEARISH', cls: 'pillDanger' };
  return { text: 'NEUTRAL', cls: 'pillNeutral' };
}

function fmtDate(value?: string): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function NewsPage() {
  const [source, setSource] = useState('all');
  const [news, setNews] = useState<NewsItem[]>([]);
  const [upcoming, setUpcoming] = useState<EconEvent[]>([]);
  const [patterns, setPatterns] = useState<Pattern[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [symbol, setSymbol] = useState('XAUUSD');
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [newsRes, upRes, patRes, sumRes] = await Promise.all([
        apiFetch(`/market/news?source=${encodeURIComponent(source)}`),
        apiFetch(`/market/upcoming?currency=USD&limit=15`),
        apiFetch(`/market/patterns`),
        apiFetch(`/market/summary?symbol=${encodeURIComponent(symbol)}`),
      ]);
      if (newsRes.ok) setNews(((await newsRes.json()).news as NewsItem[]) ?? []);
      if (upRes.ok) setUpcoming(((await upRes.json()).events as EconEvent[]) ?? []);
      if (patRes.ok) setPatterns(((await patRes.json()).patterns as Pattern[]) ?? []);
      if (sumRes.ok) setSummary(await sumRes.json());
      if (!newsRes.ok && !upRes.ok) setError('Data berita tidak tersedia (service tidak merespons).');
    } catch {
      setError('Tidak bisa menghubungi API.');
    } finally {
      setLoaded(true);
    }
  }, [source, symbol]);

  useEffect(() => {
    load();
  }, [load]);

  const senti = summary ? sentimentLabel(summary.avg_sentiment ?? 0) : null;

  return (
    <AppShell activeKey="news" eyebrow="EA BOT / NEWS" title="Berita & Kalender">
      <div className={styles.wrap}>
        <section className={styles.controls}>
          <div className={styles.controlGroup}>
            <label className={styles.ctlLabel}>Symbol</label>
            <select
              value={symbol}
              onChange={e => setSymbol(e.target.value)}
              className={styles.select}
            >
              <option value="XAUUSD">XAUUSD</option>
              <option value="EURUSD">EURUSD</option>
              <option value="GBPUSD">GBPUSD</option>
              <option value="USDJPY">USDJPY</option>
            </select>
          </div>
          <div className={styles.controlGroup}>
            <label className={styles.ctlLabel}>Sumber</label>
            <select
              value={source}
              onChange={e => setSource(e.target.value)}
              className={styles.select}
            >
              <option value="all">Semua</option>
              <option value="Yahoo Finance">Yahoo Finance</option>
              <option value="CNBC">CNBC</option>
            </select>
          </div>
          <button type="button" className={styles.refresh} onClick={load}>
            Refresh
          </button>
        </section>

        {error && <div className={styles.error}>{error}</div>}

        {/* Ringkasan sentimen */}
        {summary && (
          <section className={styles.summaryBox}>
            <div className={styles.summaryHead}>
              <h3>Ringkasan {summary.symbol ?? symbol}</h3>
              {senti && <span className={`${styles.pill} ${styles[senti.cls]}`}>{senti.text}</span>}
            </div>
            <div className={styles.summaryStats}>
              <div className={styles.stat}>
                <span className={styles.statLabel}>Avg Sentimen</span>
                <span className={styles.statValue}>{(summary.avg_sentiment ?? 0).toFixed(3)}</span>
              </div>
              <div className={styles.stat}>
                <span className={styles.statLabel}>High Impact</span>
                <span className={styles.statValue}>{summary.high_impact_events ?? 0}</span>
              </div>
            </div>
          </section>
        )}

        {/* Kalender USD akan datang */}
        <section className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Kalender USD — Akan Datang</span>
            <span className={styles.panelHint}>US / USD only</span>
          </div>
          {upcoming.length === 0 ? (
            <div className={styles.empty}>
              {loaded ? 'Belum ada event USD akan datang.' : 'Memuat…'}
            </div>
          ) : (
            <ul className={styles.eventList}>
              {upcoming.map((e, i) => (
                <li key={i} className={styles.eventRow}>
                  <div className={styles.eventWhen}>{fmtDate(e.datetime_utc ?? e.date)}</div>
                  <div className={styles.eventBody}>
                    <div className={styles.eventTitle}>
                      <span className={`${styles.pill} ${styles[impactClass(e.impact)]}`}>
                        {(e.impact || 'LOW').toUpperCase()}
                      </span>
                      <span>{e.title}</span>
                    </div>
                    <div className={styles.eventMeta}>
                      <span className={styles.countryTag}>{e.country || 'USD'}</span>
                      {e.forecast && <span>Forecast: {e.forecast}</span>}
                      {e.previous && <span>Prev: {e.previous}</span>}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Pola historis yang dipelajari agent news */}
        <section className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Pola Historis (dipelajari)</span>
            <span className={styles.panelHint}>advisory — bukan perintah order</span>
          </div>
          {patterns.length === 0 ? (
            <div className={styles.empty}>
              {loaded
                ? 'Belum ada pola terbentuk. Agent news akan mengumpulkan sampel dari hasil event.'
                : 'Memuat…'}
            </div>
          ) : (
            <div className={styles.patternGrid}>
              {patterns.map(p => (
                <div key={p.event_key} className={styles.patternCard}>
                  <div className={styles.patternKey}>{p.event_key}</div>
                  <div className={styles.patternBias}>
                    <span
                      className={`${styles.pill} ${
                        p.bias === 'BULLISH'
                          ? styles.pillOk
                          : p.bias === 'BEARISH'
                            ? styles.pillDanger
                            : styles.pillNeutral
                      }`}
                    >
                      {p.bias}
                    </span>
                    {!p.reliable && (
                      <span className={`${styles.pill} ${styles.pillNeutral}`}>LOW SAMPLE</span>
                    )}
                  </div>
                  <div className={styles.patternMeta}>
                    {p.samples} sampel · {p.up}↑ / {p.down}↓ · avg{' '}
                    {(p.avg_return * 100).toFixed(2)}%
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Headline feed */}
        <section className={styles.newsList}>
          {news.map((n, i) => (
            <article key={i} className={styles.card}>
              <h4>{n.headline}</h4>
              <div className={styles.cardMeta}>
                <span className={styles.sourceTag}>{n.source}</span>
                <span className={`${styles.pill} ${styles[impactClass(n.impact)]}`}>
                  {(n.impact || 'LOW').toUpperCase()}
                </span>
                <span className={styles.sentimentText}>
                  sentimen {n.sentiment > 0 ? '+' : ''}
                  {n.sentiment.toFixed(2)}
                </span>
              </div>
            </article>
          ))}
        </section>
      </div>
    </AppShell>
  );
}
