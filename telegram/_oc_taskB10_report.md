# TASK B-10 — AUTO-DETECT TERMINAL AKTIF — COMPLETION REPORT

TASK: B-10 (auto-detect terminal aktif: arm eligibility = running saja; tanpa gate
`"execution"`; arm manual per akun; sizing fallback volume sinyal; badge UI disederhanakan)
STATUS: PASS (TASK 6 selesai; E2E smoke = pending verifier pasca-restart)

## RINGKASAN EKSEKUSI (6 task serial, 1 opencode per task)

- **TASK 1 — `terminals.py`: eligibility arm = RUNNING.** Gate `execution_allowed`
  dihapus dari jalur arm & fanout. `list_terminals` mengemit `armable` (= proses
  running) menggantikan `execution_allowed`; auto-entry (terminal di luar config)
  kini `armable: true` + `fanout_target: true`. `arm_terminal` hanya butuh
  exists + running; `get_armed_terminals` = armed + running; `get_fanout_targets`
  = running + armed + fanout_target. `execution_permitted()` **tidak diubah**.
- **TASK 2 — `engine.py`: sizing fallback volume sinyal.** `_size_for_terminal`
  menerima `fallback_volume`; prioritas `fixed_lot` → `risk_per_trade_pct` →
  volume sinyal (`request.volume`), tetap di-clamp `[min_volume, max_lot_per_trade]`
  + normalisasi `volume_step`. Sebelumnya target tanpa config → 0.0 → order gagal.
- **TASK 3 — sapuan test lama.** Sisa referensi `execution_allowed` di test
  (task06, task12, b4, dual_import, b9) diubah ke semantik `armable`/perilaku baru.
  Test `test_arm_execution_false_terminal_rejected` (mt5_terminals) diubah maknanya:
  *execution:false TIDAK menghalangi arm; yang menghalangi hanya terminal stopped*.
- **TASK 4 — test baru `test_b10_auto_detect_terminals.py`.** 8 skenario acceptance.
- **TASK 5 — UI `control-plane/page.tsx`.** `execution_allowed?` → `armable?`; badge
  `eligible`/`data-only` dihapus; tombol Arm nonaktif hanya bila tidak running;
  danger zone memakai `selected?.running`.
- **TASK 6 (ini) — full suite + dokumentasi.** Full suite hijau, CHANGELOG +
  status doc diupdate, laporan ini ditulis.

## FILES CHANGED

Kode:
- `services/python/src/mt5/terminals.py` — eligibility arm = running; `armable`
  menggantikan `execution_allowed`; auto-entry armable + fanout_target.
- `services/python/src/mt5/endpoints.py` — docstring `execution_allowed` → `armable`.
- `services/python/src/execution/engine.py` — `_size_for_terminal` fallback volume
  sinyal + call site mengirim `request.volume`.
- `apps/web/app/control-plane/page.tsx` — types `armable`; badge disederhanakan;
  tombol Arm/danger zone berbasis `running`.

Test:
- `services/python/tests/test_b10_auto_detect_terminals.py` (**NEW**, 8 test).
- `services/python/tests/test_mt5_terminals.py`, `test_terminal_selection.py`,
  `test_b4_demo_validation.py`, `test_dual_import_unification.py`,
  `test_task06_canonical_fanout.py`, `test_task12_adversarial_e2e.py`,
  `test_fanout_multi_terminal.py`, `test_b9_multi_arm_hardening.py` — assert lama
  diperbarui.

Dokumen:
- `CHANGELOG.md` — entri B-10 ditambah paling atas (setelah header).
- `docs/tasks/B-10-auto-detect-active-terminals.md` — footer status → IMPLEMENTED.
- `telegram/_oc_taskB10_report.md` (file ini).

TIDAK disentuh: `services/python/mt5_terminals.json` (perubahan `fanout_target`
yang ada adalah perubahan MANUAL user di working tree sebelum pekerjaan B-10 —
agent tidak menyentuhnya); `runtime_settings.json`; tidak ada file arm-state
runtime yang diubah; tidak ada order nyata terkirim.

## ROOT CAUSE

1. Arm sebuah terminal sebelumnya butuh DUA syarat: running **dan**
   `"execution": true` di `mt5_terminals.json`. Terminal yang berjalan nyata
   tapi `execution:false` tidak bisa di-arm dari dashboard (ditolak).
2. Terminal **auto-detect** (di luar config) di-hardcode `execution_allowed: false`
   ("never armable") + tidak ikut fan-out — jadi terminal aktif yang baru terdeteksi
   tidak bisa dipakai sampai didaftarkan manual ke config.
3. Terminal tanpa config sizing (`fixed_lot`/`risk_per_trade_pct` tidak ada)
   mendapat volume 0.0 → order fan-out gagal ("Volume lot tidak valid (0)").
4. UI menampilkan badge `eligible`/`data-only` dan tombol Arm yang disabled
   berdasarkan `execution_allowed` — tidak sesuai model "arm manual per akun".

## FIX

- **Eligibility = running:** `armable = bool(proc is not None)`; gate `execution`
  dihapus dari `arm_terminal` / `get_armed_terminals` / `get_fanout_targets`.
  Terminal auto-detect: `armable: true`, `fanout_target: true`.
- **Fail-closed dipertahankan:** default semua DISARMED; terminal stopped → tidak
  bisa di-arm; terminal armed yang mati otomatis drop dari armed + fanout;
  `execution_permitted()` TIDAK diubah (butuh ≥1 armed + binding attached).
- **Sizing fallback:** `fixed_lot` → `risk_per_trade_pct` → volume sinyal;
  clamp broker (min/max/step) tetap.
- **UI:** badge `eligible`/`data-only` dihapus; Arm disabled hanya bila
  `busy || !hasToken || !t.running`; danger zone `selected?.running`.

## TESTS (STOP GATE per task + full suite)

- TASK 1 gate: `pytest test_mt5_terminals.py test_terminal_selection.py
  test_b9_multi_arm_hardening.py test_fanout_multi_terminal.py
  test_task06_canonical_fanout.py test_task12_adversarial_e2e.py -q` →
  **129 passed**, 0 failed.
- TASK 2 gate: `pytest test_execution_engine.py test_fanout_multi_terminal.py -q`
  → **57 passed**, 0 failed.
- TASK 3 gate: `pytest test_task06_canonical_fanout.py test_task12_adversarial_e2e.py
  test_b4_demo_validation.py test_dual_import_unification.py -q` → **117 passed**,
  0 failed.
- TASK 4 gate: `pytest test_b10_auto_detect_terminals.py -q` → **8 passed**, 0 failed.
- TASK 5 gate: `npx eslint app/control-plane/page.tsx` → **bersih (exit 0)**;
  `grep execution_allowed apps/web` (source) → nol.
- **FULL SUITE:** `pytest tests -q --basetemp=C:\Users\billy\AppData\Local\Temp\pa_b10_t6`
  → **3120 passed, 1 warning in 75.97s** (0 failed). Target ≥ 3118 (baseline 3110 +
  8 test baru B-10) TERPENUHI.
- Sapuan `execution_allowed`: hanya tersisa 3 komentar migrasi yang disengaja
  di `test_b4_demo_validation.py` (x2) + `test_dual_import_unification.py` (x1) —
  sesuai acceptance TASK 3 ("selain komentar/migrasi yang disengaja").

## RUNTIME VERIFICATION

- Full suite dijalankan atas working tree B-10 dengan basetemp FRESH (bukan
  `temp_pytest` lama yang terkunci oleh service yang sedang berjalan).
- STOP GATE TASK 6:
  1. Output full suite: **3120 passed, 0 failed** — angka persis tercatat.
  2. `grep -n "B-10" CHANGELOG.md` → entri baru di baris ≤ 20.
  3. `grep -n "Status:" docs/tasks/B-10-auto-detect-active-terminals.md` → status baru.
  4. `ls -la telegram/_oc_taskB10_report.md` → ada.
- E2E smoke via HTTP `:8787` (arm terminal `execution:false` + verifikasi
  `armed_terminals` + disarm) **TIDAK dijalankan oleh agent ini** (butuh restart
  server) — **DIJALANKAN OLEH VERIFIER pasca-laporan ini** pada instance
  sementara kode-B-10 `:8791` (terisolasi, scheduler/feed/risk OFF) dengan hasil
  LULUS: `armable` teremit; arm `vito2` → `ok:true` → `armed_terminals:["vito2"]`
  → disarm → `[]`; arm stopped (`vito1`) → `ok:false "is not running"`;
  state akhir semua DISARMED. Server utama `:8787` masih kode pra-B-10 sampai
  di-restart (butuh UAC).
- State akhir test: semua terminal **DISARMED** (fixture autouse me-reset
  `_terminal_states`/`_selected_id`/`_execution_armed` sebelum & sesudah tiap test;
  test B-10 men-disarm sendiri sebagai cleanup).

## KEPATUHAN SAFETY

- Default arm tetap **OFF** — tidak ada perubahan default arm jadi ON.
- `services/python/mt5_terminals.json` **tidak disentuh** oleh agent (perubahan
  `fanout_target` yang terlihat adalah perubahan manual user yang sudah ada di
  working tree sebelum B-10).
- Tidak ada order nyata dikirim; semua fake/inject; tidak ada `EA_ALLOW_LIVE`
  di-set.
- `execution_permitted()` tetap fail-closed (butuh armed + attached) — tidak
  dilonggarkan.
- Tidak ada `git commit`/`git push` oleh agent; tidak ada start/stop/restart
  server apa pun (`:4321`, `:5302`, `:3789`, `:8787` tidak disentuh).
- E2E smoke via `:8787` tidak dijalankan/diklaim di dokumen mana pun — dicatat
  sebagai "pending verifier (pasca-restart)".

## REMAINING ISSUES

- E2E smoke HTTP `:8787` belum dijalankan (butuh restart server) — tugas verifier.
- `.next` build artifact di `apps/web` masih memuat string bundle lama
  (`execution_allowed`/`eligible`) sampai rebuild; source `apps/web` sendiri bersih.
- Out of scope (fase berikutnya, dari dokumen B-10): routing SL/TP per-terminal,
  monitoring/reconciliation terminal-aware, auto-registrasi terminal baru ke
  `mt5_terminals.json` (auto-detect tetap read-only).

## NEXT TASK

E2E smoke oleh verifier (pasca-restart `:8787`): arm terminal yang sebelumnya
`execution:false` → `ok:true` → verifikasi muncul di `armed_terminals` → disarm →
verifikasi bersih; tanpa order nyata; state akhir SEMUA DISARMED.
