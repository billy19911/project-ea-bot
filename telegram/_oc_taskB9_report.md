# TASK B-9 LANJUTAN — MULTI-ARM HARDENING — COMPLETION REPORT

TASK: B-9 Lanjutan (multi-arm per akun: select tidak men-disarm; arm tanpa attach; fan-out re-attach per akun; single-path fail-closed >1 armed)
STATUS: PASS

## FILES CHANGED

- `services/python/src/mt5/terminals.py` — GAP #1/#2: loop disarm-all dihapus dari
  `_select_terminal_locked`; guard `attached` dihapus dari `arm_terminal`; docstring
  safety model #3 diupdate (select hanya memindah binding data). +10/-13.
- `services/python/src/execution/fanout.py` — GAP #4: `fan_out` mengingat path
  binding awal, re-attach PER AKUN (`_reattach_for_target`) sebelum order akun
  dikirim, restore binding di `finally` (`_restore_binding`), plus
  `_load_connector` / `_current_attached_path` / `_clear_symbol_cache` helper.
  +145/-30.
- `services/python/src/orchestration/pipeline.py` — GAP #3: `_BlockedExecutionAdapter`
  + guard "single-terminal path + >1 armed → fail-closed" di `_dispatch_execution`
  + helper `_armed_terminal_count()` (dual-import, fail-closed ke 0). +64.
- `services/python/src/system/settings_store.py` — knob baru `canonical_fanout_enabled`
  (bool, default 0 = NONAKTIF). +14.
- `services/python/src/system/endpoints.py` — `_apply_to_runtime` melaporkan toggle
  `canonical_fanout_enabled` (berlaku pada start proses berikutnya). +5.
- `services/python/src/mt5/endpoints.py` — docstring `select`/`arm` endpoint
  diselaraskan dengan semantik baru (B-9 Lanjutan). +5/-4.
- `apps/web/app/control-plane/page.tsx` — copy UI: select "status arm tidak
  berubah"; teks Arm/Disarm per-baris menjelaskan multi-arm. +5/-3.
- `services/python/tests/test_mt5_terminals.py` — test lama diupdate ke semantik
  baru (select TIDAK disarm; arm TIDAK butuh attach). +37/-37.
- `services/python/tests/test_task06_canonical_fanout.py` — fixture autouse
  stub connector (re-attach no-op di headless test). +11.
- `services/python/tests/test_task12_adversarial_e2e.py` — fixture autouse stub
  connector yang sama. +22.
- `services/python/tests/test_b9_multi_arm_hardening.py` (NEW) — 12 test B-9
  end-to-end (lihat RUNTIME VERIFICATION).
- `docs/tasks/B-9-multi-terminal-execution.md` — section "B-9 Lanjutan —
  Multi-Arm Hardening (implemented)" + LIMITATIONS fase berikutnya. +66.
- `telegram/_oc_taskB9.md` (spec), `telegram/_oc_taskB9_report.md` (this file).

TIDAK disentuh: `services/python/mt5_terminals.json` (execution flags),
`services/python/runtime_settings.json`, file arm-state runtime apa pun.
Tidak ada order nyata terkirim — semua fake/inject, tidak ada `MetaTrader5` di
jalur test baru.

## ROOT CAUSE

Multi-arm manual (arm per akun dari dashboard) tidak bisa berjalan end-to-end
karena 4 gap:

1. **`select_terminal` men-disarm SEMUA terminal** (`for st in _terminal_states.values(): st["armed"] = False`)
   sebelum re-attach. Operator meng-arm A+B, memilih C → A/B diam-diam lepas arm.
2. **`arm_terminal` mewajibkan binding attached** ke terminal itu. Binding MT5
   process-wide hanya menunjuk SATU terminal, jadi akun kedua tidak bisa di-arm
   tanpa memindah binding data ke sana.
3. **Jalur single-terminal tanpa guard "salah ekspektasi"**: M terminal armed +
   fan-out OFF → satu order lewat binding, akun armed lain diam-diam TIDAK dapat
   order (partial send tanpa peringatan).
4. **`CanonicalFanout.fan_out` memanggil `execute_order` dari loop** tanpa
   re-attach per akun — binding tetap di terminal terakhir → order/symbol
   resolver bisa mendarat di broker yang SALAH untuk akun berikutnya.

Temuan recon (sudah tertutup, TIDAK ditulis ulang): `execution_permitted()`
sudah menegakkan "≥1 armed & eligible AND binding attached ke salah satunya"
(fail-closed) dan dipakai engine `_native_execution_armed()`.

## FIX

- **GAP #1:** loop disarm-all DIHAPUS dari `_select_terminal_locked`. Select kini
  hanya: validasi entry → re-attach binding → pindah flag selected → simpan →
  clear symbol cache. Pesan sukses: `... Arm state unchanged.`; re-attach gagal
  tetap melaporkan binding detached tanpa menyentuh arm state.
- **GAP #2:** guard `if not entry["attached"]: reject` DIHAPUS dari `arm_terminal`.
  Arm kini butuh: terdaftar + running + `"execution": true`. Disarm selalu boleh.
- **GAP #3:** `_dispatch_execution` menghitung terminal armed (helper dual-import,
  error → 0). Fan-out OFF + count > 1 → JANGAN kirim order; kembalikan
  `_BlockedExecutionAdapter` dengan pesan `MULTIPLE TERMINALS ARMED — single-terminal
  execution disabled. Enable canonical fan-out (canonical_fanout_enabled) or disarm
  all but one.` Count ≤ 1 → perilaku lama. Branch fan-out tidak terpengaruh.
- **GAP #4:** `fan_out` menyimpan path binding awal; untuk SETIAP target ber-`path`:
  `connector.shutdown()` + `use_live_data_mode(path)` + `clear_symbol_cache()`
  SEBELUM order akun itu diproses. Attach gagal → hanya akun itu FAILED
  ("gagal attach ke terminal '<id>'"); akun lain tetap jalan. `finally` restore
  binding awal (best-effort, tidak pernah raise). Target tanpa `path` (test double)
  melewati re-attach (backward-compat).
- **Knob:** `canonical_fanout_enabled` (default NONAKTIF) + wiring pelaporan di
  `_apply_to_runtime`; dicatat bahwa perubahan berlaku pada start proses berikutnya
  (coordinator dibangun sekali).

## TESTS

- `pytest tests/test_b9_multi_arm_hardening.py -q` → **12 passed** (file baru).
- `pytest tests/test_mt5_terminals.py tests/test_fanout_multi_terminal.py
  tests/test_terminal_selection.py tests/test_task06_canonical_fanout.py
  tests/test_task12_adversarial_e2e.py tests/test_reconciliation_providers.py -q`
  → **122 passed** (semua file terdampak).
- FULL SUITE `pytest tests/ -q` → **3110 passed, 0 failed** (3098 baseline + 12
  baru), 1 warning.
- Lint clean: `black --check` (10 files unchanged), `isort --check-only`, `flake8
  --max-line-length 100` → semua bersih.
- `--basetemp=<fresh>` dipakai karena `./temp_pytest` terkunci oleh service yang
  sedang berjalan (quirk environment pre-existing).

## RUNTIME VERIFICATION (acceptance 1–7 spec)

1. **Multi-arm tanpa attach** — arm `a` + arm `b` (binding attached ke `a` saja)
   → keduanya `ok=True`, `get_armed_terminals() == {a,b}`. PASS
2. **Select tidak disarm** — arm `a`+`b` → select `c` → keduanya tetap armed,
   binding pindah ke `c` (shutdown + attach terekam). PASS
3. **Fan-out re-attach per akun** — recording connector + engine: order(111)
   melihat binding di `a`, order(222) melihat binding di `b`, binding direstore
   ke ORIGINAL. Target tanpa path melewati re-attach. PASS
4. **Fan-out partial attach failure** — attach ke `b` gagal → `b` FAILED
   ("gagal attach"), `a` FILLED, binding tetap direstore. PASS
5. **Gate `execution_permitted()`** (verifikasi kode existing) — 2 armed +
   attached ke salah satunya → True; attached ke terminal NON-armed → False;
   terminal armed berhenti running → False. PASS
6. **Pipeline >1 armed fail-closed** — single path + 2 armed → failure dengan
   pesan "MULTIPLE TERMINALS ARMED", `engine.execute_order` TIDAK dipanggil;
   1 armed → engine dipanggil; 0 armed → engine dipanggil; fanout ON → jalur
   fan-out tidak terblokir. PASS
7. **Isolasi test** — fixture autouse me-reset `_terminal_states`/`_selected_id`/
   `_execution_armed`/mirrors dan meng-assert `is_execution_armed() is False`
   setelah tiap test. PASS
- Grep bukti: tidak ada loop disarm-all di `select_terminal`; tidak ada guard
  `attached` di `arm_terminal`; `fanout.py` memuat `_reattach_for_target` +
  `_restore_binding`.
- `git diff --stat` TIDAK menyentuh `mt5_terminals.json` / `runtime_settings.json`;
  tidak ada file arm-state runtime berubah; semua order fake (tidak ada order
  nyata terkirim).
- Runtime probe read-only pasca-perubahan: `is_execution_armed()=False`,
  `get_armed_terminals()=[]`, `execution_permitted()=False` — semua terminal
  tetap DISARMED by default.

## SAFETY

- Default arm TIDAK berubah: semua terminal DISARMED by default; tidak ada
  perubahan `"execution": true|false` di `mt5_terminals.json`.
- LIVE (`vito2`) tetap `execution: false` dan tidak di-arm.
- Tidak ada order nyata terkirim; tidak ada `MetaTrader5` di test baru.
- Tidak ada `git commit` / `git push` oleh agent implementer.

## REMAINING ISSUES (fase berikutnya, didokumentasikan di docs/tasks/B-9)

- `modify_position_sltp` melewati binding yang SEDANG attached; ticket milik
  terminal lain akan ditolak broker. Routing SL/TP per-terminal = fase berikutnya.
- Monitoring/reconciliation per-akun yang terminal-aware (loop semua armed) =
  fase berikutnya.
- `canonical_fanout_enabled` di-wire saat pipeline dibangun; perubahan berlaku
  pada start proses berikutnya.
- Fan-out masih default OFF.

## NEXT TASK

Verifier (agen ini) melakukan verifikasi mandiri + commit. Tidak ada task
berikutnya dalam spec B-9 Lanjutan.
