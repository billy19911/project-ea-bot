'use client';

import { useState, useEffect, useCallback } from 'react';
import AppShell from '../../components/AppShell';
import { apiFetch } from '../../lib/api';
import styles from './page.module.css';

export default function NewsPage() {
  const [source, setSource] = useState('all');
  const [news, setNews] = useState<Array<any>>([]);
  const [summary, setSummary] = useState<any>(null);
  const [symbol, setSymbol] = useState('XAUUSD');

  const loadNews = useCallback(async () => {
    const res = await apiFetch(`/market/news?source=${source}`);
    if (res.ok) setNews((await res.json()).news);
  }, [source]);

  const loadSummary = useCallback(async () => {
    const res = await apiFetch(`/market/sentiment?symbol=${symbol}`);
    if (res.ok) setSummary(await res.json());
  }, [symbol]);

  const loadBrief = useCallback(async () => {
    const res = await apiFetch(`/market/summary?symbol=${symbol}`);
    if (res.ok) setSummary(await res.json());
  }, [symbol]);

  useEffect(() => {
    loadNews();
    loadSummary();
  }, [loadNews, loadSummary]);

  return (
    <AppShell activeKey="market" eyebrow="EA BOT / NEWS" title="Berita Pasar">
      <section className={styles.controls}>
        <label className={styles.ctlLabel}>Sumber</label>
        <select value={source} onChange={e => setSource(e.target.value)} className={styles.select}>
          <option value="all">Semua</option>
          <option value="Yahoo Finance">Yahoo Finance</option>
          <option value="CNBC">CNBC</option>
        </select>
      </section>

      <section className={styles.newsList}>
        {news.map((n, i) => (
          <article key={i} className={styles.card}>
            <h4>{n.headline}</h4>
            <p>{n.source}</p>
            <p>Sentimen: {n.sentiment}</p>
            <p>Impact: {n.impact}</p>
          </article>
        ))}
      </section>

      {summary && (
        <section className={styles.summaryBox}>
          <h3>Ringkasan {summary.symbol ?? symbol}</h3>
          <p>Avg sentimen: {summary.avg_sentiment}</p>
          <p>High‑impact events: {summary.high_impact_events}</p>
          <p>Positif: {summary.top_positive?.join(' | ')}</p>
          <p>Negatif: {summary.top_negative?.join(' | ')}</p>
        </section>
      )}
    </AppShell>
  );
}
