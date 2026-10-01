# B-10 — Auto-Detect Terminal Aktif (Tanpa Gate Live/Demo, Arm Manual per Akun)

## Goal
Semua terminal MT5 yang **sedang berjalan (running)** otomatis terdeteksi dan tampil di dashboard, dan **satu-satunya kontrol adalah ARM manual per akun** oleh operator. Tidak ada lagi pembedaan live/demo dan tidak ada lagi gate `"execution": true|false` di `mt5_terminals.json` sebagai syarat arm. Fail-closed tetap: semua mulai dari **DISARMED**; order nyata hanya mungkin bila operator meng-arm sendiri.

**Arahan user (verbatim):** *"autodeteksi terminal yang aktif saja, gk usah di bedakan live / demo kan nanti aku jg yg seting manual mau di arm ato gk nya"*

## Keputusan Desain (final untuk plan ini)
1. **Eligible arm = `running`** (proses `terminal64.exe` hidup, terdeteksi `scan_running_terminals()` via psutil). Bukan `execution:true`.
2. **Field `"execution"` di `mt5_terminals.json` menjadi deprecated/ignored** — kode tidak membacanya lagi untuk gate apa pun. File JSON **tidak disentuh oleh agent** (milik user; biarkan apa adanya).
3. **API field `execution_allowed` dihapus**, diganti `armable` (= `running`). Consumer di UI & test di-update serentak.
4. **Terminal auto-detect (di luar config) juga armable** — sebelumnya hardcoded `execution_allowed: false` ("never armable"). Sekarang `armable: true` saat running, dan `fanout_target: true` (ikut fan-out saat armed).
5. **Sizing untuk terminal tanpa config** (auto-detect / tanpa `fixed_lot`/`risk_per_trade_pct`): fallback ke **volume dasar sinyal** (`request.volume`), bukan 0 (sebelumnya 0 → order gagal). Prioritas tetap: `fixed_lot` → `risk_per_trade_pct` → volume sinyal.
6. **Safety invariants dipertahankan 100%**: default arm OFF; `execution_permitted()` tetap fail-closed (butuh ≥1 armed + binding attached); terminal yang mati otomatis drop dari daftar armed; `require_approval`/token tetap; `EA_ALLOW_LIVE` tidak pernah di-set; tidak ada order nyata selama test.

## Current vs Target

| Aspek | Sekarang (B-9) | Target (B-10) |
|---|---|---|
| Syarat arm | running + `"execution": true` | **running saja** |
| Terminal auto-detect | data-only, tidak bisa di-arm | **bisa di-arm** (armable) |
| `get_armed_terminals()` | armed + execution_allowed + running | **armed + running** |
| `get_fanout_targets()` | execution_allowed + running + armed + fanout_target | **running + armed + fanout_target** |
| UI badge | `eligible` / `data-only` | dihapus (hanya `ARMED` + status running) |
| UI tombol Arm | disabled bila `!execution_allowed` | disabled hanya bila **tidak running** |
| Sizing tanpa config | volume 0 → order gagal | fallback volume sinyal |
| `execution_permitted()` | armed + attached (fail-closed) | **tidak berubah** (fail-closed) |
| Default arm | OFF | **OFF (tidak berubah)** |

## Files to Modify
- `services/python/src/mt5/terminals.py` — inti: `list_terminals` (279–345), `arm_terminal` (883–962), `get_armed_terminals` (730–763), `get_fanout_targets` (825–850), auto-entry (322–346), `armed_terminals` view (354–360). `execution_permitted` (963–1000) **tidak diubah**.
- `services/python/src/mt5/endpoints.py` — docstring `execution_allowed` (line 95) → `armable`.
- `services/python/src/execution/engine.py` — `_size_for_terminal` (1224–1261) + call site (1190): fallback `request.volume`.
- `apps/web/app/control-plane/page.tsx` — types (1177), badge+toggle arm (1470–1500), danger zone (1551).
- `services/python/tests/test_mt5_terminals.py` — assert gate lama (139–157, 358, 476–477).
- `services/python/tests/test_task06_canonical_fanout.py` — assert `execution_allowed` (420).
- `services/python/tests/test_task12_adversarial_e2e.py` — assert `execution_allowed` (930).
- `services/python/tests/test_b9_multi_arm_hardening.py` — fixture & assert bila menyentuh field lama.
- NEW `services/python/tests/test_b10_auto_detect_terminals.py` — test baru B-10.
- `CHANGELOG.md` + dokumen ini (status implementasi) — di task terakhir.

## TASK BREAKDOWN (serial, satu task satu agent, STOP GATE per task)

> Aturan main (verbatim, dipertahankan): *"Tasks MUST be completed in order. A task is not complete merely because code was changed or unit tests pass. Each task has a STOP GATE. The agent MUST NOT start the next task until every acceptance criterion and verification command for the current task passes."*

### TASK 1 — `terminals.py`: eligibility = running
**Scope:** hapus gate `execution_allowed` dari jalur arm & fanout.
- `list_terminals`: ganti `"execution_allowed": t["execution"]` → `"armable": bool(proc is not None)`; auto-entry `"execution_allowed": False` → `"armable": True` (running by definition) + `"fanout_target": True`; blok `armed_terminals` (354–360) → `e.get("armed") and e.get("armable")`.
- `arm_terminal`: hapus blok `if not entry["execution_allowed"]` (902–911). Syarat arm = exists + running.
- `get_armed_terminals`: hapus gate `execution_allowed` (757) → armed + running.
- `get_fanout_targets`: hapus gate `execution_allowed` (841) → running + armed + fanout_target.
- Update docstring fungsi yang menyebut `execution: true`.
- `endpoints.py` docstring line 95 → `armable`.
**Acceptance:** arm terminal `execution:false` yang running → `ok:true`; terminal stopped → `ok:false`; auto-entry armable; fanout target mencakup terminal tanpa `execution:true`; `execution_permitted()` masih fail-closed.
**STOP GATE:**
```
services/python/.venv/Scripts/python.exe -m pytest services/python/tests/test_mt5_terminals.py services/python/tests/test_terminal_selection.py services/python/tests/test_b9_multi_arm_hardening.py -q
```
Harus hijau SEMUA (test lama yang assert gate di-update di task yang sama — bukan di-skip).

### TASK 2 — `engine.py`: sizing fallback volume sinyal
**Scope:** `_size_for_terminal(target, entry, risk_price, symbol, fallback_volume)` — bila `fixed_lot` & `risk_per_trade_pct` tidak ada → pakai `fallback_volume` (= `request.volume`), tetap clamp ke `[min_volume, max_lot_per_trade]` + normalisasi `volume_step`. Call site (1190) kirim `request.volume`.
**Acceptance:** target tanpa sizing → volume = volume sinyal (bukan 0); target dengan `fixed_lot` → tetap fixed; risk_pct tetap dihitung; tidak ada test lama yang pecah.
**STOP GATE:**
```
services/python/.venv/Scripts/python.exe -m pytest services/python/tests/test_execution_engine.py services/python/tests/test_fanout_multi_terminal.py -q
```

### TASK 3 — Update test lama yang meng-assert gate
**Scope:** sapu bersih sisa referensi `execution_allowed` di test (task06:420, task12:930, b4, dual_import, b9 bila ada) → assert `armable`/perilaku baru. Test `test_arm_execution_false_terminal_rejected` (mt5_terminals:476) diganti maknanya: *"execution:false TIDAK menghalangi arm; yang menghalangi hanya terminal stopped"*.
**Acceptance:** `grep -rn "execution_allowed" services/python/src services/python/tests apps/web` → **nol** (selain komentar/migrasi yang disengaja).
**STOP GATE:**
```
services/python/.venv/Scripts/python.exe -m pytest services/python/tests/test_task06_canonical_fanout.py services/python/tests/test_task12_adversarial_e2e.py services/python/tests/test_b4_demo_validation.py services/python/tests/test_dual_import_unification.py -q
```

### TASK 4 — Test baru B-10 (`test_b10_auto_detect_terminals.py`)
**Scope:** test yang membuktikan seluruh acceptance B-10:
1. arm terminal `execution:false` + running → OK, `get_armed_terminals` memuatnya.
2. arm terminal auto-detect (tidak di config) + running → OK.
3. arm terminal stopped → rejected (fail-closed).
4. `get_fanout_targets` tanpa gate execution: running+armed+fanout_target → ikut; stopped → drop.
5. `execution_permitted()` tetap butuh attached (fail-closed) — armed tanpa attached → False.
6. Terminal armed lalu mati → otomatis keluar dari `get_armed_terminals` & `get_fanout_targets`.
7. Sizing fallback: target tanpa `fixed_lot`/`risk_per_trade_pct` → volume = volume sinyal.
8. Default state: semua OFF tanpa arm eksplisit.
**STOP GATE:**
```
services/python/.venv/Scripts/python.exe -m pytest services/python/tests/test_b10_auto_detect_terminals.py -q
```
Semua test BARU hijau + full file-file B-9 tetap hijau.

### TASK 5 — UI `control-plane/page.tsx`
**Scope:**
- types: `execution_allowed?: boolean` → `armable?: boolean`.
- badge: hapus `eligible`/`data-only`; sisakan badge `ARMED` + (opsional) badge running/stopped.
- tombol Arm: `disabled={busy || !hasToken || !t.running || !t.execution_allowed}` → `disabled={busy || !hasToken || !t.running}`; tooltip menyesuaikan.
- danger zone (1551): `selected?.execution_allowed &&` → `selected?.running &&`.
**Acceptance:** ESLint bersih; `curl :4321/control-plane` render; grep `execution_allowed` di `apps/web` → nol.
**STOP GATE:**
```
cd apps/web && npx eslint app/control-plane/page.tsx && cd ../..
curl -s http://localhost:4321/control-plane | grep -c "ARMED\|Arm"
```

### TASK 6 — Full suite + E2E smoke + dokumentasi
**Scope:**
1. Full suite Python: target ≥ 3110 + test baru, 0 failed.
2. E2E smoke via HTTP `:8787`: arm terminal yang **sebelumnya `execution:false`** (mis. `vito2`) → `ok:true` → verifikasi muncul di `armed_terminals` → **disarm** → verifikasi bersih. **Tidak ada order yang dikirim; tidak ada sinyal berjalan; fanout OFF.**
3. Update `CHANGELOG.md` + status implementasi di dokumen ini.
4. Laporan `telegram/_oc_taskB10_report.md`.
**STOP GATE:**
```
services/python/.venv/Scripts/python.exe -m pytest services/python/tests -q --basetemp=<tmp-fresh>
curl -s http://127.0.0.1:8787/mt5/terminals | python -m json.tool
```
+ bukti arm/disarm tercatat; state akhir SEMUA DISARMED.

## Acceptance Criteria (global, dicek di TASK 6)
1. Terminal running apa pun (demo/live/config/auto) → bisa di-arm manual; tanpa `execution:true`.
2. Terminal stopped → tidak bisa di-arm (fail-closed).
3. Tidak ada lagi referensi `execution_allowed`/gate `"execution"` di jalur arm/fanout kode & UI.
4. Default arm tetap OFF; `mt5_terminals.json` tidak berubah; `EA_ALLOW_LIVE` tidak di-set.
5. `execution_permitted()` tetap butuh armed+attached (fail-closed) — tidak dilonggarkan.
6. Sizing: `fixed_lot` → `risk_pct` → volume sinyal.
7. Full suite hijau; lint bersih; E2E smoke tercatat; state akhir disarmed.

## Larangan (spec, dipertahankan)
- DILARANG mengubah default arm menjadi ON; DILARANG enable LIVE; DILARANG mengirim order nyata.
- DILARANG mengubah `mt5_terminals.json` (termasuk flag `execution` — biarkan; kode yang berhenti membacanya).
- DILARANG `git commit`/`git push` oleh agent — verifier yang commit setelah review.
- DILARANG me-restart server `:4321`/`:5302`/`:3789` tanpa instruksi; `:8787` hanya bila diperlukan dan diizinkan.
- DILARANG menghapus test tanpa pengganti; DILARANG skip test.

## Out of Scope (fase berikutnya)
- Per-terminal SL/TP routing untuk ticket lintas terminal (`modify_position_sltp`).
- Monitoring/reconciliation terminal-aware.
- Auto-registrasi terminal baru ke `mt5_terminals.json` (auto-detect tetap read-only; tanpa sizing config pakai fallback volume sinyal).
- Penghapusan fisik field `"execution"` dari file config (milik user).

## Risk & Mitigasi
| Risiko | Mitigasi |
|---|---|
| Live account (vito2) tak sengaja ikut tereksekusi | Fail-closed: default OFF; fanout OFF by default; arm tetap manual; smoke test langsung disarm; tidak ada sinyal berjalan saat uji |
| Terminal tanpa sizing config → lot salah | Fallback volume sinyal + clamp broker (min/max/step); fixed_lot & risk_pct tetap prioritas |
| Regresi gate | STOP GATE per task + test baru B-10 + full suite |
| `execution_permitted` terlalu longgar | Tidak diubah; test fail-closed tetap dipertahankan |

---
**Created:** 2026-10-01
**Assignee:** OpenCode (serial, 1 task per agent, gate-verified) — verifier: assistant + user
**Priority:** P1 (user-requested)
**Status:** IMPLEMENTED & VERIFIED — TASK 1–6 selesai & lulus STOP GATE; full suite 3120 passed. E2E smoke LULUS di server utama `:8787` (pasca-restart, PID 39696, kode B-10 aktif): arm `vito2` (LIVE, tadinya `execution:false`) → `ok:true` → `armed_terminals:["vito2"]` → disarm → bersih; arm terminal stopped (`vito1`) → `ok:false "is not running"` (fail-closed); Node proxy `:3789` meneruskan `armable` (tanpa `execution_allowed`); state akhir semua DISARMED. Tidak ada order nyata.
