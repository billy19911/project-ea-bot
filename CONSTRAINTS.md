# Environment Constraints

Dokumentasi kendala lingkungan development/project ini dan rekomendasi solusi.

---

## Status: Dokumen Ini Relevan

Environment saat ini memiliki kendala signifikan yang menghalangi development dan CI/CD berjalan normal.

---

## Kendala yang Ditemukan

### 1. Docker Tidak Tersedia

| Detail | Informasi |
|--------|-----------|
| Gejala | Perintah `docker` tidak ditemukan di PATH |
| Dampak | Semua service yang mengandalkan Docker Compose (database, cache, queue) tidak bisa dijalankan |
| Lokasi | Environment development Windows |

**Dampak:**
- Tidak bisa menjalankan PostgreSQL, Redis, atau service lain via container
- Developer harus install dependency secara native di OS
- CI/CD pipeline yang mengandalkan Docker akan gagal

**Rekomendasi Solusi:**
1. **Jangka pendek:** Install PostgreSQL dan Redis secara native di Windows (lihat `docs/development-setup.md`)
2. **Jangka menengah:** Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) untuk Windows (membutuhkan WSL2)
3. **Alternatif:** Gunakan WSL2 dengan Linux native — install Docker di dalam WSL2

---

### 2. Node.js Binary Tidak Ditemukan di PATH

| Detail | Informasi |
|--------|-----------|
| Gejala | Perintah `node` tidak ditemukan, hanya `npm` (v10.9.8) yang tersedia |
| Dampak | Script build, test, dan runtime yang menjalankan `node` langsung akan gagal |
| Penyebab | npm terinstal terpisah (mungkin melalui installer terpisah) tanpa Node.js runtime |

**Dampak:**
- `npm run build` gagal karena script build memanggil `node`
- Tidak bisa menjalankan aplikasi Node.js
- Frontend development tidak bisa dimulai

**Rekomendasi Solusi:**
1. Unduh Node.js binary (.zip) dari [nodejs.org](https://nodejs.org/)
2. Ekstrak dan tambahkan ke `PATH` environment variable
3. Verifikasi dengan `node --version` dan `npm --version`
4. Alternatif: Install via Scoop (`scoop install nodejs-lts`) atau winget

---

### 3. Database dan Cache Belum Terinstal

| Detail | Informasi |
|--------|-----------|
| PostgreSQL | Belum terinstal — perlu setup manual |
| Redis | Belum terinstal — perlu setup manual |

**Rekomendasi Solusi:**
- Ikuti panduan di `docs/development-setup.md` untuk instalasi manual PostgreSQL dan Redis di Windows
- Pertimbangkan menggunakan WSL2 untuk lingkungan yang lebih dekat dengan production

---

### 4. CI/CD Pipeline Tidak Bisa Berjalan

| Detail | Informasi |
|--------|-----------|
| Gejala | GitHub Actions workflow (`.github/workflows/ci.yml`) ada tetapi tidak bisa dijalankan di environment lokal |
| Dampak | Tidak bisa melakukan local CI test sebelum push ke remote |

**Rekomendasi Solusi:**
- Pipeline dirancang untuk berjalan di GitHub Actions runners (yang punya semua tool)
- Untuk local testing, install semua dependency sesuai `docs/development-setup.md`
- Jika ada step yang gagal di GitHub Actions, periksa log dan sesuaikan konfigurasi

---

## Ringkasan Prioritas Perbaikan

| Prioritas | Kendala | Usaha yang Dibutuhkan |
|-----------|---------|----------------------|
| 🔴 Tinggi | Node.js binary tidak ada | Install Node.js + tambah ke PATH |
| 🔴 Tinggi | PostgreSQL belum ada | Install dan setup database |
| 🟠 Sedang | Redis belum ada | Install dan jalankan server |
| 🟡 Rendah | Docker tidak ada | Install Docker Desktop atau tetap pakai native install |

---

## Catatan untuk Developer Baru

Jika kamu bergabung dengan project ini dan menemukan kendala di atas:

1. Baca `docs/development-setup.md` — ada langkah-langkah detail untuk setiap dependency
2. Baca `CONSTRAINTS.md` ini — pahami apa yang belum tersedia
3. Hubungi tim untuk koordinasi jika ada kendala yang tidak tertangani di docs

---

## FAQ

**Q: Kenapa tidak pakai Docker saja?**

A: Environment saat ini tidak memiliki Docker. Jika ingin menjalankannya, install Docker Desktop untuk Windows (membutuhkan WSL2 enabled). Dokumentasi untuk setup Docker akan ditambahkan terpisah.

**Q: Apakah npm saja cukup?**

A: Tidak. `npm` tanpa `node` binary hanya bisa menjalankan perintah package management dasar. Semua script build, test, dan runtime memerlukan `node` binary.

**Q: Apa yang terjadi jika saya mencoba run aplikasi sekarang?**

A: Aplikasi tidak akan bisa dijalankan sampai semua dependency terinstal:
- `node` — untuk frontend build dan scripting
- `python` — sudah tersedia
- `psql` — untuk database migrations dan queries
- `redis-server` — untuk caching dan session storage
