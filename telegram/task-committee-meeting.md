# Task: Rapat Komite (Committee Meeting) — alur percakapan supervisor + semua agent → 1 keputusan

## Tujuan
UI "Ruang Komite" (`apps/web/app/agents/page.tsx`) harus terbaca sebagai **rapat dipimpin Supervisor**:
Supervisor membuka rapat → seluruh agent departemen Market memberi kontribusi → **Sintesis menyimpulkan SATU jawaban/keputusan**.
Kontribusi specialist = bahan rapat, BUKAN sinyal terpisah. Tidak ada perubahan routing EPIC 01, risk gate, engine, atau risk policy.

## Kondisi sekarang (fakta, sudah diverifikasi)
- `services/python/src/agents/supervisor.py` `analyze()` (~line 401-427) hanya dispatch ke `department_lead` (EPIC 01) → `agent_results` = `{market_lead: {...}}` → UI cuma 1 bubble agent.
- `services/python/src/market/intelligence.py` `MarketLead.analyze()` menjalankan 6 specialist (`technical_analyst`, `momentum_analyst`, `structure_analyst`, `volatility_analyst`, `news_sentiment`, `fundamental_analyst` — lihat `_build_default_specialists`, line 316-344) dan menyimpan hasilnya di key `specialist_results` pada dict return-nya (region return ~787-835), tetapi tidak pernah di-surface.
- Konsumen `agent_results` di Python: **hanya** `supervisor.py` (produsen) dan `orchestration/pipeline.py` (penyalin ke DecisionRecord ~line 341-343). `telegram/` TIDAK membaca `agent_results`. Menambah entry aman.
- `orchestration/endpoints.py` tidak mendefinisikan `/decisions`; route ada di `system/endpoints.py` (~line 267, via `runtime.recent_decisions`).
- Frontend `apps/web/app/agents/page.tsx`:
  - `agentEntries = Object.entries(selected.agent_results)` (~line 248).
  - Bubble Supervisor (fixed text, ~line 360-371) → `agentEntries.map(...)` (~line 364) → bubble "Sintesis Komite" → riwayat.
  - `agentTypeByName` dibangun dari `/ai-control/status` (~line 241-244) → specialist tidak ada di sana → label `-`.
  - Tipe `AgentResult` sudah punya `signal/confidence/reasoning/reasons/evidence` — cocok dengan bentuk hasil specialist (`signal`, `confidence`, `reasons`).

## Poin 1 — Backend: surface specialist sebagai kontribusi rapat
File: `services/python/src/agents/supervisor.py`

1. Di `analyze()`, setelah dispatch ke lead dan sebelum dict return dibentuk (region ~line 470-553):
   - Buat `agent_results` untuk DISPLAY dengan cara: mulai dari `results` (urutan lead tetap pertama), lalu **flatten** `specialist_results` dari tiap lead result yang memilikinya:
     - untuk tiap `(name, spec)` dalam `results[lead_name].get("specialist_results", {})` (dict, non-kosong): tambahkan `agent_results[name] = spec`.
     - Skip bila `spec` bukan dict.
     - Normalisasi minimal defensive: pastikan `signal` (default `"NEUTRAL"`), `confidence` (float, default `0.0`, clamp 0..1), `reasons` (list of str — bila `reasoning` string saja, bungkus jadi `[reasoning]`), `agent` (default = key `name`).
   - Urutan entry (penting untuk render): lead dulu (`market_lead`), lalu specialist sesuai urutan dict `specialist_results` (technical_analyst, momentum_analyst, structure_analyst, volatility_analyst, news_sentiment, fundamental_analyst).
2. **Jangan ubah input `_synthesise(...)` / `generate_proposal(...)`** — tetap `results` level-lead seperti sekarang (konsensus antar-specialist sudah terjadi di dalam MarketLead lewat adaptive evidence weight). Synthesis, risk gate, `supervisor_summary`, routing, dan EPIC 01 tetap.
3. Key lama tidak berubah; record lama tanpa specialist tetap valid (graceful).

## Poin 2 — Frontend: render sebagai rapat dengan SATU keputusan
File: `apps/web/app/agents/page.tsx`

1. Bubble Supervisor (~line 360-371): ubah framing jadi pembuka rapat, misal:
   `Rapat Komite dibuka — {symbol} · {event_type}. Semua agent Market memberi kontribusi; satu keputusan disimpulkan di Sintesis.`
   (pakai field yang memang ada di `DecisionRecord`: `symbol`, `event_type`; guard null → `—`).
2. `agentEntries` tetap `Object.entries(selected.agent_results)` — dengan Poin 1 otomatis berisi lead + 6 specialist. Jangan ubah sumber data / tambah fetch.
3. Label type per bubble: `agentTypeByName` tidak memuat specialist → fallback label di tempat (jangan ubah `/ai-control/status`):
   - key `market_lead` (atau berakhiran `_lead`) → `Market Lead`;
   - key berakhiran `_analyst` atau `news_sentiment` → `Market Analyst`;
   - selain itu → pakai `agentTypeByName` / `-`.
   Jangan tambahkan map nama yang dirakit ulang tiap render bila bisa dipecah jadi fungsi kecil murni.
4. Di/sekitar bubble **Sintesis Komite**: tambahkan baris konsensus mini yang dihitung dari `agentEntries` (tanpa library baru, tanpa backend baru):
   `{n} agent · BULLISH {x} · BEARISH {y} · NETRAL {z}`
   Klasifikasi per entry: signal uppercase mengandung `BULL`/`BUY` → BULLISH; mengandung `BEAR`/`SELL` → BEARISH; selain itu (termasuk kosong/ERROR) → NETRAL. `n` = jumlah entries.
   Pastikan teks "SATU keputusan" terlihat: bubble Sintesis menampilkan `decision` + `status` + levels seperti sekarang (sudah ada) — konsensus bar hanya pelengkap di atas/di dalam bubble Sintesis.
5. Gaya: ikuti `page.module.css` yang sudah ada; badge warna konsisten (`signalClass`, `statusBadgeClass`); tanpa animasi/skeleton baru. Polling tetap `useAutoRefresh` saja.

## Poin 3 — Verifikasi (WAJIB dijalankan, laporkan hasil asli)
Backend:
```bash
cd services/python && python -m flake8 src/agents/supervisor.py --max-line-length=100 --extend-ignore=E203,W503
python -m pytest -k "supervisor" -q   # atau test yang menyentuh supervisor/agent_results bila ada
```
Frontend (root repo):
```bash
npm run lint
npm run build
```

## Batasan keras
- Jangan ubah `gate.py`/`engine.py`/risk policy/`market/intelligence.py` (kecuali sangat perlu — default: tidak).
- Jangan ubah input synthesis/risk gate; jangan ubah format record DecisionRecord selain nilai `agent_results`.
- Jangan tambah dependency; jangan tambah polling; jangan sentuh `.env*`/kredensial; MT5 read-only.
- Jangan commit/push.

## Output yang diharapkan
1. Diff final kedua file (supervisor.py, page.tsx).
2. Log verifikasi asli (flake8, pytest, lint, build) — bukan simulasi.
3. Ringkasan singkat perubahan.
