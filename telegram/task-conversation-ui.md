# Task: Ruang Komite — animasi percakapan antar-agent (Discord-style) + pelajaran

Repo: C:/xampp/htdocs/project-ea-bot. Web: apps/web (Next.js, design tokens di app/globals.css).
Edit files only; DO NOT restart services; jangan tambah dependency npm; jangan ubah halaman lain.

## Tujuan (permintaan user)

User ingin melihat percakapan antar organisasi/agent seperti tampilan Discord:
- Supervisor "bertanya" minta analisa market → agent terkait "nyala" (menyala/beranimasi) dan
  memberi hasil analisanya → agent lain merespon melengkapi data → sampai keputusan entry/tidak.
- Tiap entry yang dihasilkan (TP ataupun SL) dianalisa ulang → hasil analisa menjadi bekal
  pembelajaran pola market (tampilkan daftar pelajaran).

## Data (SUDAH tersedia, jangan bikin endpoint baru)

1. `GET /decisions?limit=20` (via `apiFetch`) →
   `{ decisions: DecisionRecord[], count, source }`.
   DecisionRecord = hasil `PipelineResult.to_dict()`:
   `event_id, task_id, decision_id, proposal_id, execution_id, client_order_id, strategy_version,
   decision (BUY/SELL/WAIT/NO_TRADE), status (EXECUTED/BLOCKED/NO_TRADE/WAIT/ERROR),
   risk_approved, risk_reason, executed, execution_result (dict|null, ada `ticket`),
   trace (list {stage,status,detail}), error, event_type, confidence, summary, trace_id, symbol,
   levels (dict|null: {direction, entry, sl, tp1, tp2, tpmax, risk_distance, rr, source}),
   agent_results (dict: { "<agent_name>": { agent, signal, confidence, reasoning, reasons[], evidence[] } }),
   supervisor_summary (str)`.
   PENTING: bila `agent_results` kosong/tidak ada → tampilkan empty state
   "Belum ada data komite pada siklus ini." (defensif, jangan crash).
2. `GET /ai-control/status` → `{ supervisor: {status, routing_policy, max_concurrency, token_budget,
   token_used, uptime}, agents: [{name, type, status ('active'|'idle'), priority, invocations,
   errors, errorRate, avgConfidence, lastActive, signalCounts}], models, tasks, errors, source }`.
3. `GET /learning/analytics` → `{ available, source, lessons: [{id, category, outcome, symbol, text}],
   by_outcome: {outcome: count}, total }`.

## File 1: `apps/web/app/agents/page.tsx` (GANTI placeholder)

Pola WAJIB (tiru `apps/web/app/observability/page.tsx` + `apps/web/app/trade-history/page.tsx`):
- `'use client'`; `AppShell activeKey="agents" eyebrow="Xynn / Agents" title="Ruang Komite"`.
- `import styles from './page.module.css'`.
- `const load = useCallback(async () => {...}, []); useAutoRefresh(load);`
- Fetch 3 endpoint di atas dengan `Promise.allSettled`; state terpisah per sumber; error inline
  (teks kecil merah, JANGAN blocking); "Memuat…" HANYA saat initial (state `loaded` false).
- Jangan pernah `setLoading(true)` per poll.

Layout (grid 2 kolom; kolom kiri utama, kanan sidebar; responsive: 1 kolom < 1000px):

A. Baris ringkasan atas: kartu kecil — "Total siklus", "Siklus terakhir (HH:MM)", "Agent aktif".

B. Kolom kiri — PERCAKAPAN (untuk `selected` decision; default = decisions[0]):
   1. Bubble Supervisor (paling atas):
      `🧠 Supervisor` — teks: `"Minta analisa {symbol} — event {event_type}. Menunggu penilaian tiap departemen."`
      + chip `routing: {supervisor.routing_policy}` bila tersedia.
   2. Untuk tiap entry `agent_results` (urut sesuai urutan object; gunakan `Object.entries`):
      bubble agent berisi:
      - Avatar bulat dengan inisial nama (huruf pertama). Untuk decision TERBARU (decisions[0]) avatar
        diberi class `avatarLive` (animasi pulse ring) — efek "agent nyala".
      - Nama agent + chip type (dari `agents[].type` di /ai-control/status bila nama cocok; fallback '-').
      - Badge signal: BULLISH/BUY → class `trendUp`, BEARISH/SELL → class `trendDown`,
        NEUTRAL/lainnya → chip netral (class `chipMuted`).
      - Bar confidence: bar kecil (lebar = `confidence*100%`, clamp 0-100) + teks `conf 0.86`.
      - Teks `reasoning` (wrap).
      - `evidence` (list): tampilkan maks 3 item sebagai bullet; bila >3 tambah `+N lagi`.
      - Animasi masuk: class `bubbleIn` + `style={{ animationDelay: `${index * 120}ms` }}`.
   3. Bubble Sintesis (paling bawah):
      `🧩 Sintesis Komite` — `decision` + badge status:
      EXECUTED → hijau (class `badgeOk`), BLOCKED → merah (`badgeBlock`), NO_TRADE/WAIT → netral (`badgeMuted`).
      Bila `levels` ada: tabel rapi `Entry / SL / TP1 / TP2 / TPmax` (mono font, 1 kolom label + 1 kolom angka).
      Bila `risk_reason` ada → baris kecil `⛔ {risk_reason}`. Bila `execution_result?.ticket` ada →
      `🎫 ticket {ticket}`. Bila `trace_id` ada → `🔎 trace {trace_id}` (teks muted, kecil).

C. Riwayat siklus (di bawah percakapan): daftar `decisions` (maks 20) baris ringkas:
   `HH:MM · symbol · decision · status`. Klik → set `selected` (percakapan atas berganti; gunakan
   `key={selected.decision_id}` pada wrapper percakapan agar animasi bubbleIn diputar ulang).
   Baris terpilih diberi highlight class `historyActive`.

D. Kolom kanan — SIDEBAR:
   1. Panel "👥 Anggota" (dari /ai-control/status.agents):
      tiap baris: dot status (class `dotLive` + animasi blink bila status 'active', else `dotIdle`),
      nama, type (chip kecil), `invocations` kali, `avgConfidence` (format 2 desimal bila ada),
      `lastActive` (format jam:menit lokal bila ada).
   2. Panel "📚 Pelajaran" (dari /learning/analytics.lessons, maks 10):
      tiap item: chip outcome (TP/SL/outcome apa pun — pakai class `badgeOk` bila outcome
      mengandung "tp"/"win"/"profit", `badgeBlock` bila "sl"/"loss", else `badgeMuted`),
      symbol, teks `text` (maks 2 baris dengan ellipsis).
      Bila `available` false / lessons kosong → "Belum ada pelajaran terekam."

Format angka harga: `toFixed(2)` bila > 100 (XAUUSD), `toFixed(5)` bila <= 100; null/undefined → '—'.
Format jam: `new Date(...).toLocaleTimeString('id-ID', {hour:'2-digit',minute:'2-digit'})` bila field ada
(epoch detik untuk lastActive? gunakan new Date(Number(x)*1000) bila angka; bila string ISO → langsung).

## File 2: `apps/web/app/agents/page.module.css` (baru)

Gaya mengikuti design system (token dari globals.css): pakai `var(--surface)`, `var(--surface-muted)`,
`var(--border)`, `var(--border-strong)`, `var(--text)`, `var(--text-muted)`, `var(--danger)` bila ada;
JANGAN hard-code hex. Font numerik: `font-family: var(--font-mono)`.

Wajib berisi minimal keyframes + class:
```css
@keyframes bubbleIn {
  from { opacity: 0; transform: translateY(8px) scale(0.98); }
  to   { opacity: 1; transform: none; }
}
@keyframes pulseRing {
  0%   { box-shadow: 0 0 0 0 rgba(120, 180, 255, 0.45); }
  70%  { box-shadow: 0 0 0 8px rgba(120, 180, 255, 0); }
  100% { box-shadow: 0 0 0 0 rgba(120, 180, 255, 0); }
}
@keyframes dotBlink {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.25; }
}
.bubbleIn { animation: bubbleIn 0.35s ease-out backwards; }
.avatarLive { animation: pulseRing 1.8s ease-out infinite; }
.dotLive { animation: dotBlink 1.2s ease-in-out infinite; }
```
Plus class: `.wrap` (grid 2 kolom + gap, responsive), `.summaryRow`, `.card`, `.bubble`, `.avatar`,
`.bubbleHead`, `.chip`, `.chipMuted`, `.badgeOk`, `.badgeBlock`, `.badgeMuted`, `.confBar`/`.confFill`,
`.evidence`, `.levels`, `.history`, `.historyRow`, `.historyActive`, `.dotIdle`, `.sidebar`, `.panel`,
`.muted`, `.mono`. (Nama bebas selama konsisten dipakai di page.tsx.)

## File 3: `apps/web/components/AppShell.tsx` (kecil saja)

- Tambah item nav di grup "Intelligence":
  `{ key: 'agents', label: 'Agents', href: '/agents', icon: 'users' }` (setelah 'ai-control').
- Tambah case icon 'users' di komponen `Icon` (svg stroke, mirip gaya icon lain), contoh path:
  `M17 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2` + `M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z` +
  `M23 21v-2a4 4 0 0 0-3-3.87` + `M16 3.13a4 4 0 0 1 0 7.75`.
- JANGAN ubah item lain.

## Verifikasi (jalankan, laporkan ringkas)

```
cd apps/web
npx tsc --noEmit
npx eslint app/agents/page.tsx components/AppShell.tsx
```
Bila `npx tsc --noEmit` gagal karena konfigurasi, jalankan `npx tsc --noEmit -p tsconfig.json`.
Bila eslint workspace tidak jalan, jalankan dari root repo: `npm run lint`.

Laporan akhir: file diubah + hasil tsc/eslint + catatan deviasi.
