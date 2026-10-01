# TASK B-9 LANJUTAN — MULTI-ARM EXECUTION HARDENING (per-account arm/disarm)

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. HEAD = 9c61664 (FINAL CERTIFICATION, 12 task selesai, full suite 3098 passed).
BACA dulu: `docs/tasks/B-9-multi-terminal-execution.md` (desain resmi multi-terminal) + `telegram/_MASTER_PLAN.md` section 0 (invariant #2, #5, #6, #7, #8).

Safety: semua MT5 execution tetap DISARMED by default. DILARANG mengubah default arm, DILARANG enable LIVE, DILARANG mengirim order nyata, DILARANG mengubah `"execution": true|false` di `services/python/mt5_terminals.json`. DILARANG `git commit` / `git push` — verifier yang commit setelah review.

## ⚠ ENVIRONMENT
- Semua command selesai < 60 detik (full suite boleh lebih; gunakan timeout wajar).
- Web :4321, python :5302, node :3789 SUDAH JALAN — JANGAN start/stop/restart, jangan jalankan server blocking.
- Python: `services/python/.venv/Scripts/python.exe`. Test: `cd services/python && .venv/Scripts/python.exe -m pytest ...` (pakai `--basetemp` bila basetemp default terkunci).
- Lint config ada di `services/python/pyproject.toml` (ruff/black/isort/flake8, line-length mengikuti config).

## GOAL
Tutup 4 gap yang membuat multi-arm (arm manual per akun) TIDAK bisa berjalan end-to-end meski API/UI per-terminal sudah ada. Target akhir (perilaku yang harus terbukti di test):
1. Operator bisa ARM beberapa terminal sekaligus (A+B+C), TANPA harus meng-attach binding ke masing-masing saat arming.
2. Memilih (select) terminal lain TIDAK men-disarm terminal yang sudah armed — select hanya memindah fokus/binding DATA.
3. Eksekusi multi-akun (canonical fan-out) mengirim order ke SETIAP akun armed: re-attach binding ke terminal akun SEBELUM order akun itu dikirim, lalu restore binding asli di akhir (fail-safe).
4. Jalur single-terminal TIDAK boleh "nyasar": native `order_send` hanya boleh dikirim saat binding sedang attached ke terminal yang ARMED; bila ada >1 terminal armed dan jalur single dipakai → fail-closed dengan pesan yang menyuruh pakai canonical fan-out.

## 4 GAP + PERBAIKAN (WAJIB SEMUA)

### GAP #1 — `select_terminal` men-disarm SEMUA terminal
File: `services/python/src/mt5/terminals.py` — `select_terminal` (~626) / `_select_terminal_locked` (~640).
Saat ini: sebelum re-attach ada loop `for st in _terminal_states.values(): st["armed"] = False` (blok komentar "Safety: disarm ALL terminals BEFORE touching the binding").
Perbaikan: HAPUS loop disarm-all tersebut. Select hanya boleh: (a) validasi entry (not found / not running → reject seperti sekarang), (b) re-attach binding (shutdown + use_live_data_mode(path)), (c) mark selected + unmark lain, (d) `save_selection`, (e) clear symbol cache. Arm state TIDAK disentuh — baik saat sukses maupun saat re-attach GAGAL.
- Message sukses: `"Terminal '<id>' selected. Attached to: <path>. Arm state unchanged."`
- Message gagal attach: tetap "Failed to attach ... The binding is now detached — re-select a running terminal." dan TIDAK mengubah arm state.
- Return dict: `execution_armed` = nilai derived terkini (`_sync_backcompat_globals()` dulu), BUKAN `False` paksa.
- Update docstring (hapus klaim "ALWAYS disarms").

### GAP #2 — `arm_terminal` mewajibkan binding attached
File: `services/python/src/mt5/terminals.py` — `arm_terminal` (~852).
Saat ini: reject `if not entry["attached"]` ("The binding is not attached ... Select it first").
Perbaikan: HAPUS syarat attached. Syarat arm yang benar: terdaftar di registry + running + `execution: true`. (Re-attach binding terjadi otomatis saat eksekusi — fan-out re-attach per akun; jalur single divalidasi di engine, lihat GAP #4/engine.)
- Update docstring: attach BUKAN lagi syarat; alasan: binding process-wide hanya untuk DATA, eksekusi re-attach sendiri per akun.
- Disarm tetap selalu allowed (tidak berubah).

### GAP #3 — Jalur single-terminal: proteksi terhadap salah-ekspektasi multi-arm
**TEMUAN RECON (penting):** `mt5.terminals.execution_permitted()` (~985) SUDAH menegakkan "minimal satu terminal armed & ELIGIBLE & binding sedang attached ke salah satunya" (loop `armed_ids` × `entry["attached"]`, fail-closed). Engine `_native_execution_armed()` memanggil gate ini, jadi **GAP #3a/#3c sudah tertutup di kode — JANGAN tulis ulang logika itu; VERIFIKASI + tambah test**.
Yang MASIH kurang adalah proteksi "salah ekspektasi": operator meng-arm 2+ terminal tetapi menjalankan jalur single-terminal (fanout OFF) → hanya binding yang menerima order, akun lain diam-diam tidak dapat order. Ini harus FAIL-CLOSED dengan pesan jelas.
File: `services/python/src/orchestration/pipeline.py` — `_dispatch_execution` (~2570, branch single-terminal saja, yaitu `return self.execution_engine.execute_order(request)` di akhir):
- Sebelum memanggil `execute_order`, baca jumlah terminal armed: helper kecil `_armed_terminal_count()` dengan pola import ganda (`mt5.terminals` / `src.mt5.terminals`) + `get_armed_terminals()`; error/ragu → 0 (fail-closed).
- Bila `self.fanout_enabled` FALSE dan count > 1 → JANGAN kirim order; kembalikan objek adapter failure dengan `success=False` dan `error_message="MULTIPLE TERMINALS ARMED — single-terminal execution disabled. Enable canonical fan-out (canonical_fanout_enabled) or disarm all but one."` (buat helper adapter kecil di pipeline, pola seperti `_FanoutExecutionAdapter` yang sudah ada).
- Count ≤ 1 → perilaku lama tidak berubah.
- Branch fan-out (`execute_order_fanout`) dan canonical fan-out TIDAK terpengaruh.
Verifikasi tambahan (test, bukan kode baru): `execution_permitted()` dengan 2 terminal armed, binding attached ke salah satunya → True; binding attached ke terminal NON-armed → False (sudah fail-closed).
**LIMITASI yang WAJIB dicatat di docs + report (bukan diperbaiki sekarang):** `modify_position_sltp` mengganti SL/TP lewat binding yang sedang attached; bila ticket milik terminal lain, broker akan menolak (order_send ke terminal yang salah). Routing SLTP per-terminal = fase berikutnya.

### GAP #4 — `_process_account` mengirim order TANPA re-attach per akun (fan-out kanonik)
File: `services/python/src/execution/fanout.py` — `CanonicalFanout.fan_out` (~337) + `_process_account` (~640, call `execute_order` di ~698).
Saat ini: loop akun memanggil `self.execution_engine.execute_order(request)` sementara binding tetap di terminal terakhir — order akun bisa nyasar / symbol resolver membaca broker yang salah.
Perbaikan (pola SAMA dengan `engine.execute_order_fanout` / `_dispatch_to_terminal` yang sudah ada):
- Di `fan_out`: sebelum loop, simpan path binding asli (via `mt5.connector`; import lokal, best-effort) — mis. `original = _current_attached_path()`. Simpan juga apakah connector tersedia.
- Untuk SETIAP target di loop, SEBELUM `_process_account`: bila `target.get("path")` truthy → `connector.shutdown()` + `connector.use_live_data_mode(path=target["path"])`; bila gagal → dispatch status FAILED dengan pesan "gagal attach ke terminal '<id>'" dan `continue` (akun lain tetap diproses). Sukses → clear symbol cache (pola `from mt5.symbol_resolver import clear_symbol_cache`).
- `path` falsy (test double tanpa path) → skip re-attach (backward-compat dengan test lama).
- `finally` di `fan_out`: restore binding ke `original` bila ada (shutdown + use_live_data_mode(original)); best-effort, jangan pernah raise.
- JANGAN menyentuh `FanoutLedger`, `_build_request`, `_risk_gate_account`, `_normalize` selain yang diperlukan; jangan ubah `AccountExecutionStatus`.

### PENDUKUNG (kecil tapi wajib)
- `services/python/src/system/settings_store.py`: tambah Knob `canonical_fanout_enabled` (bool, default 0) — deskripsi: fan-out kanonik multi-akun (SATU sinyal kanonik → SEMUA terminal armed, re-attach per akun); default NONAKTIF. `applied_to="TradingPipeline.fanout_coordinator"` atau deskriptif. Cek apakah ada test yang menghitung jumlah knob → sesuaikan.
- `services/python/src/mt5/endpoints.py`: bila endpoint select/arm membentuk message sendiri, samakan dengan message baru (arm tidak butuh attached; select tidak mengubah arm). Cek `TerminalConfigRequest`/select handler.
- `apps/web/app/control-plane/page.tsx`: update copy yang menyatakan arm di-reset saat ganti terminal:
  - tooltip tombol Select (~1507): `'Pilih terminal ini (binding di-attach ulang, arm di-reset)'` → `'Pilih terminal ini (binding di-attach ulang; status arm tidak berubah)'`.
  - teks bantuan di Pusat Eksekusi (~1586): hapus/ubah kalimat yang menyatakan ganti terminal me-reset arm; tegaskan arm/disarm manual per baris.
- `docs/tasks/B-9-multi-terminal-execution.md`: APPEND section `## B-9 Lanjutan — Multi-Arm Hardening (implemented)` berisi: 4 perubahan (select tidak disarm; arm tanpa attach; fanout re-attach per akun + restore; gate single-path attached-ke-armed + >1 armed fail-closed di pipeline), cara pakai (contoh: `bil2` DEMO arm saja → fan-out target tunggal; 3 akun → arm semua + aktifkan `canonical_fanout_enabled`), dan LIMITASI (monitoring/reconciliation per-akun terminal-aware = fase berikutnya).

## TEST YANG WAJIB DIUPDATE (semantik baru; JANGAN hapus tanpa pengganti)
- `tests/test_mt5_terminals.py`:
  - `test_switch_reattaches_and_disarms` (~230) → rename/ubah: select tetap re-attach (assert calls shutdown+path) TAPI arm state TIDAK berubah (set arm via `_state_for(...)["armed"]=True` atau `arm_terminal`; assert masih armed setelah select).
  - `test_failed_reattach_disarms_and_reports` (~259) → failed re-attach: `ok=False`, arm state TIDAK berubah.
  - `test_select_disarms_all_terminals` (~545) → ganti menjadi test B-9 core: arm A + arm B (tanpa attach requirement), `select_terminal("c")` → `get_armed_terminals()` tetap berisi A dan B.
  - `test_arm_not_attached_rejected` (~495) → sekarang arm TANPA attached HARUS SUKSES (running + execution:true); assert `ok=True` + masuk `get_armed_terminals()`.
  - `test_arm_requires_attached_binding` (~305, legacy `arm_execution`) → update mengikuti semantik baru (arm tanpa attach sukses; hapus assert "attached").
- `tests/test_task12_adversarial_e2e.py`: cek asumsi select-disarm di skenario L/M + helper `_disarm_terminals`; sesuaikan bila terdampak (JANGAN lemahkan invariant: di akhir suite tidak boleh ada terminal armed).
- `tests/test_terminal_selection.py`, `tests/test_task06_canonical_fanout.py`, `tests/test_fanout_multi_terminal.py`: jalankan; perbaiki hanya yang terdampak semantik baru.

## TEST BARU (wajib, file baru `tests/test_b9_multi_arm_hardening.py` — boleh + tambahan di file lama)
1. **Multi-arm tanpa attach**: arm `bil2` + arm `demo2` (config execution:true, running, binding TIDAK attached ke demo2) → keduanya `ok=True`, `get_armed_terminals()` berisi keduanya.
2. **Select tidak disarm**: arm A+B → `select_terminal(C)` sukses → A+B masih armed; binding pindah ke C (assert calls).
3. **Fan-out re-attach per akun**: `CanonicalFanout` dengan fake connector + execution_engine stub yang mencatat binding saat `execute_order` dipanggil; 2 target dengan `path` → urutan calls: attach A → order(A) → attach B → order(B) → restore original. Assert order diterima akun yang benar + binding restored.
4. **Fan-out partial attach failure**: attach ke B gagal → dispatch B FAILED, A tetap FILLED, restore tetap terjadi.
5. **Gate `execution_permitted` (verifikasi, sudah ada di kode)**: 2 terminal armed, binding attached ke salah satunya → True; binding attached ke terminal NON-armed → False; terminal armed berhenti running → False.
6. **Pipeline >1 armed fail-closed**: pipeline single-path (fan-out OFF) + 2 armed → hasil failure dengan pesan "MULTIPLE TERMINALS ARMED", engine `execute_order` TIDAK dipanggil; 1 armed → engine dipanggil seperti biasa; fanout ON → jalur fan-out tidak terblokir.
7. Semua test baru WAJIB membersihkan state (`_terminal_states`, `_selected_id`, `_execution_armed`, mirrors) di fixture autouse.

## ACCEPTANCE CRITERIA / STOP GATE (semua harus PASS sebelum lapor)
1. `pytest tests/test_b9_multi_arm_hardening.py -q` → semua pass.
2. `pytest tests/test_mt5_terminals.py tests/test_fanout_multi_terminal.py tests/test_terminal_selection.py tests/test_task06_canonical_fanout.py tests/test_task12_adversarial_e2e.py tests/test_reconciliation_providers.py -q` → semua pass.
3. FULL SUITE `pytest tests/ -q` → 3098 + test baru, 0 failed (sebutkan jumlah akhir).
4. Lint clean (ruff/black/isort/flake8 sesuai pyproject).
5. `git diff --stat` TIDAK menyentuh `mt5_terminals.json` execution flags; tidak ada file arm-state runtime yang berubah; tidak ada order nyata terkirim (semua fake).
6. Grep bukti: tidak ada lagi loop disarm-all di `select_terminal`; tidak ada lagi syarat `attached` di `arm_terminal`; `fanout.py` memuat re-attach + restore.

## COMPLETION REPORT (format section 15 master plan; bahasa Indonesia)
```
TASK: B-9 LANJUTAN / STATUS: PASS atau BLOCKED
FILES CHANGED: <daftar + ringkas per file>
ROOT CAUSE: <per gap #1..#4>
FIX: <per file, jelaskan perilaku baru>
TESTS: <command + hasil; termasuk full suite count>
RUNTIME VERIFICATION: <bukti test baru per acceptance 1-7>
REMAINING ISSUES: <mis. monitoring/reconciliation per-akun = fase berikutnya; fan-out default masih OFF>
NEXT TASK: NOT STARTED
```
Kalau ada satu acceptance gagal → STATUS: BLOCKED dan STOP (jangan lanjut ke task lain).
