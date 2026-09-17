# UI/UX Redesign Plan — EA Bot Dashboard

Status: **menunggu persetujuan**
Tanggal audit: 2026-09-17
Prinsip: **konsolidasi, bukan akumulasi.** Simpel, fungsional maksimal, profesional.

---

## 1. Masalah yang terverifikasi (bukan opini)

### Struktur & duplikasi

| # | Masalah | Bukti konkret |
|---|---------|---------------|
| 1 | **5 sidebar berbeda, di-hardcode per halaman** | `app/page.tsx` (6 item), `control-plane/page.tsx` (15 item), `ai-control`, `strategy`, `observability` — masing-masing punya blok `styles.sidebar` sendiri; item tidak konsisten antar halaman |
| 2 | **Nol shared component** | `components/` kosong — 4.675 baris JSX+CSS terduplikasi |
| 3 | **120+ warna hex, tanpa design token** | `:root` di `globals.css` tidak punya satu pun custom property; tiap CSS module punya 25–29 hex unik sendiri |
| 4 | **Selector bocor (sisa CSS-module mangling)** | `globals.css:30-37` menyasar `span.formTitle-p`, `span.registry-span`, `div.resultList-p` — kelas yang **tidak pernah ada** di JSX mana pun |
| 5 | **Navigasi tidak konsisten** | Control-plane punya 15 section yang hanya ada di halaman itu; home punya "System Settings" yang tidak ada di halaman lain |

### UX & visual (dari audit screenshot)

| # | Masalah | Bukti |
|---|---------|-------|
| 6 | **Empty state buruk** | `"Tidak ada data overview."` polos — halaman terasa rusak, bukan kosong |
| 7 | **Duplikasi indikator mode** | Badge `PAPER` di header **dan** "Paper mode" di sidebar footer |
| 8 | **Bahasa campur ID/EN** | "Research Center", "Backtest" vs "Eksperimen", "Hasil Riset", "Sistem aktif" |
| 9 | **Emoji sebagai ikon** | ▦ ⚙ 🧠 📡 📊 ✈️ — render beda per OS/browser, tidak profesional |
| 10 | **Terminal switcher tersembunyi** | Panel MT5 ada di dalam tab "System Overview"; **tidak menampilkan info akun** (login/server/demo-live) — padahal user punya 2 terminal (1 LIVE, 1 DEMO) |
| 11 | **Hierarki tipografi lemah** | H1 halaman dominan; H2 section tenggelam. Tab aktif hanya beda background |

---

## 2. Solusi per fase

### F1 — Design tokens (1 file, dampak ke semua halaman)

`app/globals.css` menjadi sumber tunggal:

- **Warna semantic**: `--bg`, `--surface`, `--border`, `--text`, `--text-muted`, `--primary`, `--success`, `--warning`, `--danger`, `--accent-demo`, `--accent-live`
- **Spacing scale**: `--sp-1` … `--sp-8` (4/8/12/16/24/32/48/64 px)
- **Radius / shadow / font-size scale**
- **Hapus selector bocor** (masalah #4)

Tanpa mengubah JSX; halaman langsung konsisten.

### F2 — AppShell tunggal (2 file baru, menggantikan 5 duplikasi)

`components/AppShell.tsx` + `AppShell.module.css`:

- **Sidebar tergrup**: Operasional (Control Plane, Observability) · AI (AI Control, Strategy) · Riset (Research Center) · Sistem (Settings)
- **Ikon SVG inline** — bukan emoji (masalah #9)
- **Footer sidebar**: status akun MT5 aktif — login + badge **DEMO** (hijau) / **LIVE** (merah) — selalu terlihat di semua halaman
- **Header**: breadcrumb + judul + slot aksi kontekstual
- Hapus 5 sidebar duplikat → **satu sumber** (masalah #1, #2, #5)

### F3 — Terminal & akun MT5 (permintaan langsung user)

**Backend** (`services/python/src/mt5/`):

- `GET /mt5/terminals` — **enrich** tiap terminal dengan info akun bila tersedia (login, server, trade_mode). Additive, tidak mengubah kontrak lama.
- `POST /mt5/terminals/probe` — **probe on-demand, read-only**: attach ke tiap terminal yang running → baca `account_info()` (login, server, trade_mode, balance, currency) → **restore ke terminal asli** (wajib `finally`) → simpan cache + timestamp. Tidak ada order, tidak ada arm.
- Test baru dengan mock (CI tidak punya MT5 nyata).

**UI**:

- Panel "MT5 Terminals" dipromosikan ke **posisi teratas Control Plane** (bukan terkubur di tab)
- Tabel: Terminal · Status · **Akun (login)** · **Server** · **Mode (DEMO/LIVE)** · Balance · Aksi (Pilih)
- Tombol **"Cek akun"** (probe on-demand) + timestamp pengecekan terakhir
- Arm/Disarm dipisah visual ke **Zona Berbahaya** — hanya muncul saat terminal terpilih `execution_allowed`; tetap OFF default, switch terminal tetap reset arm (safety tidak berubah)

### F4 — Rapikan 5 halaman

- Semua halaman pakai AppShell (hapus duplikasi)
- **Aturan bahasa**: label UI & pesan = Indonesia; istilah teknis baku (Backtest, Sharpe, Drawdown, Pipeline) tetap Inggris — ditulis sebagai komentar di kode
- **Empty state jujur**: pesan + langkah berikutnya (tanpa angka fabrikasi)
- Hapus badge duplikat (#7), perbaiki hierarki tipografi (#11)

### F5 — Verifikasi (tidak ada klaim tanpa bukti)

- `tsc --noEmit` 0 error · ESLint bersih · `next build` sukses
- Test Python baru (probe) hijau + suite penuh tidak regresi
- **Screenshot before/after** tiap halaman
- CI hijau

---

## 3. Yang TIDAK dikerjakan (anti-slop)

- ❌ **Tidak menambah framework UI** (Tailwind/MUI/shadcn) — untuk 5 halaman, token + CSS module cukup; dependency baru = kompleksitas baru
- ❌ **Tidak menambah dark mode** — tidak diminta
- ❌ **Tidak rewrite halaman dari nol** — perubahan bertarget; test yang ada harus tetap hijau
- ❌ **Tidak menyentuh logika safety** — arm/guard/reset tidak berubah, tetap fail-closed
- ❌ **Tidak fabrikasi data** — angka kosong tetap kosong dengan pesan jelas

## 4. Estimasi

| Fase | File | Dependency baru |
|------|------|-----------------|
| F1 | 1 CSS | — |
| F2 | 2 baru + 5 diubah | — |
| F3 | 2 backend + 1 test + panel UI | — |
| F4 | 5 halaman + 5 CSS | — |
| F5 | verifikasi | — |

Total ~16 file. **Nol dependency baru.**

## 5. Urutan eksekusi + checkpoint

1. **F1 + F2** → screenshot halaman Control Plane sebagai pilot → *checkpoint review*
2. **F3** → uji probe ke 2 terminal nyata (read-only) → *checkpoint review*
3. **F4** → sisa halaman konsisten
4. **F5** → verifikasi penuh + commit + push

Setiap checkpoint: user melihat hasil nyata sebelum lanjut. Tidak ada "big bang" yang sulit di-rollback.
