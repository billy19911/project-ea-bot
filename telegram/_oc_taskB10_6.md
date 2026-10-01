# TASK B-10 #6 — Full suite + dokumentasi (E2E smoke oleh verifier)

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. BACA dulu: `docs/tasks/B-10-auto-detect-active-terminals.md` section "TASK 6".
Prasyarat: TASK 1–5 SUDAH selesai & lulus gate masing-masing (kode + test + UI sudah berubah di working tree).

Safety: DILARANG `git commit`/`git push`; DILARANG start/stop/restart server apa pun (`:4321`, `:5302`, `:3789`, `:8787`); DILARANG menyentuh `services/python/mt5_terminals.json`; DILARANG mengirim order nyata. E2E smoke via HTTP `:8787` TIDAK kamu lakukan (butuh restart server) — dijalankan terpisah oleh verifier setelah restart; JANGAN klaim E2E sudah dijalankan di dokumen mana pun; tulis status E2E sebagai "pending verifier (pasca-restart)" bila perlu menyebutnya.

## GOAL
1. Jalankan FULL SUITE Python atas working tree B-10 → target **≥ 3118 passed, 0 failed** (baseline 3110 + 8 test baru B-10).
2. Update `CHANGELOG.md` (entri B-10, ikuti gaya entri B-9 yang sudah ada di file — lihat atas file).
3. Update footer status di `docs/tasks/B-10-auto-detect-active-terminals.md` (baris terakhir: `Status: PLAN — ...` → `Status: IMPLEMENTED — TASK 1–5 selesai & terverifikasi; TASK 6 full-suite hijau; E2E smoke: pending verifier (pasca-restart :8787)`).
4. Tulis laporan `telegram/_oc_taskB10_report.md` (format di bawah).

## LANGKAH
1. Full suite (fresh basetemp, JANGAN pakai basetemp lama yang terkunci):
```
cd services/python && .venv/Scripts/python.exe -m pytest tests -q --basetemp="C:\Users\billy\AppData\Local\Temp\pa_b10_t6" 2>&1 | tail -6
```
Catat jumlah passed/failed/waktu. Jika ada failure: analisis akar masalah. Fix HANYA bila jelas disebabkan perubahan B-10 (arm gate / sizing fallback / badge UI / sapuan test TASK 3), dan hanya di file yang relevan B-10; jalankan ulang test terkait + full suite. Jika akar masalah TIDAK jelas / di luar scope B-10 → tulis BLOCKED + bukti, STOP.
2. `CHANGELOG.md`: baca 60 baris pertama, lalu tambah entri baru paling atas (setelah header) bergaya sama: judul "B-10 — Auto-Detect Terminal Aktif (Tanpa Gate Live/Demo, Arm Manual per Akun)", tanggal 2026-10-01, poin: (a) arm eligibility = terminal running saja; field `"execution"` di `mt5_terminals.json` tidak lagi dibaca (file tidak disentuh); (b) terminal auto-detect kini armable; (c) API field `execution_allowed` → `armable`; (d) UI: badge `eligible`/`data-only` dihapus, tombol Arm nonaktif hanya bila terminal tidak running; (e) sizing fallback `fixed_lot` → `risk_per_trade_pct` → volume sinyal (clamp min/max/step broker); (f) default tetap DISARMED; `execution_permitted()` tetap butuh armed+attached; (g) test baru `test_b10_auto_detect_terminals.py` (8 skenario); full suite N passed (isi N hasil langkah 1).
3. Update status doc (langkah 3 GOAL) — 1 baris footer.
4. Tulis `telegram/_oc_taskB10_report.md` (~60–100 baris, Indonesia): ringkasan eksekusi 6 task serial (1 opencode per task), daftar file berubah (kode/test/UI/dokumen), hasil STOP GATE per task (127/57/117/8+72/full suite), kepatuhan safety (default DISARMED; JSON tidak disentuh; tanpa order nyata; tanpa commit), catatan E2E smoke = pending verifier.

## VERIFIKASI (STOP GATE)
1. Output full suite: 0 failed, jumlah ≥ 3118 (tempel angka persis).
2. `grep -n "B-10" CHANGELOG.md` → entri baru ada di 20 baris pertama.
3. `grep -n "Status:" docs/tasks/B-10-auto-detect-active-terminals.md` → status baru.
4. `ls -la telegram/_oc_taskB10_report.md` → ada.

## COMPLETION REPORT (Indonesia, format sama sebelumnya)
```
TASK: B-10 #6 / STATUS: PASS atau BLOCKED
FILES CHANGED / ROOT CAUSE / FIX / TESTS (full suite angka) / RUNTIME VERIFICATION / REMAINING ISSUES / NEXT TASK: E2E smoke oleh verifier
```
