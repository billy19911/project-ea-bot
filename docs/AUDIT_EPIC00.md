# EPIC 00 — Audit Existing Repository

**Tanggal Audit:** 2026-09-14
**Scope:** Seluruh monorepo `project-ea-bot`

---

## 1. Ringkasan Eksekutif

| Aspek | Status | Catatan |
|---|---|---|
| Struktur monorepo | ✅ Rapi | `apps/`, `services/`, `packages/`, `infrastructure/`, `docs/` sesuai PRD |
| Python service | ✅ Sebagian besar OK | 522/523 test pass, 1 fail kecil |
| Node.js backend (API) | ⚠️ Broken build | Type error `SecureWebSocket` di `src/middleware/websocket.ts` |
| Next.js frontend | ⚠️ Lint crash | ESLint flat-config conflict; build berhasil tapi lint gagal |
| Shared package | ✅ OK | `tsc` berhasil |
| CI/CD blueprint | ⚠️ Usang | Masih merujuk folder `frontend/` dan `backend/`, tidak sesuai struktur monorepo |
| Environment validation | ✅ Ada | `config-validate.js` tersedia |
| Dependencies | ⚠️ Ada mismatch | `openai` tidak terinstall di Python venv padahal diimport oleh LLM layer |

**Kesimpulan:** Sistem Python cukup mature dan well-tested. Bagian Node.js memiliki broken build dan lint yang perlu diperbaiki sebelum lanjut ke EPIC berikutnya. CI/CD blueprint perlu direvisi agar sesuai struktur monorepo.

---

## 2. Struktur Repository

```
project-ea-bot/
├── apps/
│   ├── api/          # Express + Prisma backend
│   └── web/          # Next.js dashboard
├── services/
│   └── python/       # FastAPI service
├── packages/
│   ├── eslint-config/
│   └── shared/       # TypeScript shared types
├── infrastructure/
│   ├── docker/
│   └── db/
├── .github/workflows/# CI/CD blueprint
├── docs/
├── scripts/
└── telegram/
```

### Statistik Kode

| Layer | File | Jumlah |
|---|---|---|
| API (`apps/api/src`) | `.ts` | 9 |
| Web (`apps/web/app`) | `.tsx` | 5 |
| Python service | `.py` | 68 |
| Python tests | `.py` | 30 |

---

## 3. Hasil Build & Test

### 3.1 Node.js Build (`npm run build`)

**Status:** ❌ Gagal

```text
apps/api: error TS2344: Type 'SecureWebSocket' does not satisfy constraint 'typeof WebSocket'.
  at src/middleware/websocket.ts(99,48)
```

`SecureWebSocket` kemungkinan bertipe instance bukan class constructor. Diperlukan cast atau penggunaan tipe `WebSocket` bawaan library `ws`.

### 3.2 Next.js Build

**Status:** ⚠️ Build OK, lint gagal

```text
✓ Compiled successfully
✓ Generating static pages (7/7)
✓ Finalizing page optimization

ESLint: Invalid Options — unknown options: useEslintrc, extensions
```

Penyebab: proyek menggunakan ESLint v9 tetapi masih memakai format `.eslintrc.*` atau konfigurasi Next.js lama. ESLint v9 memerlukan flat config (`eslint.config.js`).

### 3.3 Node.js Lint (`npm run lint`)

**Status:** ❌ Gagal di semua workspace Node.js

- `apps/api`: tidak menemukan `eslint.config.(js|mjs|cjs)`
- `apps/web`: unknown options ESLint legacy
- `packages/shared`: tidak menemukan `eslint.config.(js|mjs|cjs)`

Rekomendasi: migrasi semua konfigurasi ESLint ke flat config.

### 3.4 Python Tests

**Status:** ⚠️ 1 failure

```text
collected 523 items
FAILED tests/test_mt5.py::test_timeframe_map_populated
1 failed, 522 passed, 6 warnings
```

#### Failure Detail
Assertion di `tests/test_mt5.py` mengharapkan `TIMEFRAME_MAP` populated tetapi ternyata kosong/tidak sesuai. Perlu inspeksi lebih lanjut terhadap `services/python/src/mt5/_constants.py`.

#### Import Error jika Menjalankan Test LLM
```text
ModuleNotFoundError: No module named 'openai'
```

`openai` belum terinstall di `.venv` meskipun `src/llm/nine_router.py` mengimportnya. Harus ditambahkan ke `requirements.txt` atau optional dependency group.

---

## 4. Temuan Keamanan & Konfigurasi

| No | Temuan | Risiko | Rekomendasi |
|---|---|---|---|
| 1 | `.env.example` mengandung placeholder lemah/defaults | Credential leak potensial | Gunakan placeholder eksplisit seperti `REPLACE_ME` dan validasi non-default di runtime |
| 2 | `postinstall` api: `prisma skills sync` — typo? | Install failure | Ganti menjadi `prisma generate` atau hapus jika tidak dipakai |
| 3 | CI/CD masih merujuk `frontend/`, `backend/` | Workflow tidak akan jalan di repo saat ini | Update path ke `apps/web`, `apps/api`, `services/python` |
| 4 | `requirements.txt` tidak mengandung `openai` | LLM layer tidak bisa di-import | Tambahkan `openai` dan versikan |
| 5 | FastAPI `on_event("startup")` deprecated | Future breakage | Ganti ke `lifespan` context manager |
| 6 | `starlette.testclient` membutuhkan `httpx2` | Test warning | Update dependency sesuai warning |
| 7 | `cache-dependency-path` di CI merujut `frontend/package-lock.json` yang tidak ada | Cache miss | Gunakan `package-lock.json` root atau masing-masing workspace |

---

## 5. Rekomendasi Prioritas

### P0 — Sebelum lanjut development
1. Perbaiki TypeScript error `SecureWebSocket` di `apps/api/src/middleware/websocket.ts`.
2. Migrasi ESLint ke flat config (`eslint.config.js`) untuk semua workspace Node.js.
3. Tambahkan `openai` ke `requirements.txt` dan install ulang venv.
4. Perbaiki failing test `test_timeframe_map_populated`.

### P1 — Dalam waktu dekat
5. Update CI/CD blueprint agar path dan command sesuai monorepo.
6. Ganti `@app.on_event("startup")` dengan FastAPI `lifespan`.
7. Perbaiki `postinstall` script di `apps/api/package.json`.
8. Audit `.env.example` agar tidak ada default credential.

### P2 — Nice to have
9. Tambahkan test command untuk web (Next.js) dan api (Jest/Vitest).
10. Dokumentasikan minimum `.env` values di `docs/development-setup.md`.

---

## 6. Aset yang Bagus & Harus Dijaga

- Python service sangat well-tested (522 passing tests, 30 test files).
- Struktur monorepo sudah rapi dan sesuai PRD.
- Safety-first design: Risk Gate, mode trading, live-readiness gate sudah ada.
- README dan CHANGELOG baru saja diperbarui dan akurat.

---

*Audit ini adalah titik awal sebelum memulai EPIC development berikutnya.*
