# TASK B-10 #1 — terminals.py: eligibility arm = RUNNING (hapus gate `execution_allowed`)

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. HEAD = 2ababf2.
BACA dulu: `docs/tasks/B-10-auto-detect-active-terminals.md` (plan resmi B-10) — khususnya section "Keputusan Desain" + "TASK 1".

Safety: semua MT5 execution tetap DISARMED by default. DILARANG mengubah default arm, DILARANG enable LIVE, DILARANG mengirim order nyata, DILARANG mengubah `services/python/mt5_terminals.json` (file ini SEDANG ada perubahan manual user di working tree — jangan disentuh sama sekali). DILARANG `git commit` / `git push` — verifier yang commit setelah review.

## ⚠ ENVIRONMENT
- Semua command selesai < 60 detik (pytest beberapa file boleh lebih; timeout wajar).
- Web :4321, python :5302/:8787, node :3789 SUDAH JALAN — JANGAN start/stop/restart, jangan jalankan server blocking.
- Python: `services/python/.venv/Scripts/python.exe`. Test: `cd services/python && .venv/Scripts/python.exe -m pytest ...` — jika basetemp default terkunci, pakai `--basetemp=/c/Users/billy/AppData/Local/Temp/pa_b10_t1` (atau temp lain).
- Lint: black/isort/flake8 terinstall di venv (line-length 100; isort profile=black; flake8 extend-ignore E203,W503). Jalankan pada file yang diubah.

## GOAL
B-10: **satu-satunya syarat arm = terminal RUNNING.** Field `"execution": true|false` di mt5_terminals.json tidak lagi dibaca untuk gate apa pun (deprecated/ignored — file tidak disentuh). API field `execution_allowed` dihapus dari view `list_terminals()` dan diganti `armable` (= running). Fail-closed tetap: default OFF; terminal stopped tidak bisa di-arm; `execution_permitted()` TIDAK diubah.

## PERUBAHAN KODE (WAJIB SEMUA)

### A. `services/python/src/mt5/terminals.py`

1. **`list_terminals()`** (sekitar line 279–366):
   - Line ~305: `"execution_allowed": t["execution"],` → `"armable": bool(proc is not None),`
   - Auto-entry (line ~322–349): `"execution_allowed": False,` → `"armable": True,` (auto = running by definition). Ganti juga komentar "Auto-detected terminals are never fan-out targets..." dan ubah `"fanout_target": False,` → `"fanout_target": True,` (B-10 keputusan #4: auto-detect ikut fan-out saat armed).
   - Blok `armed_terminals` (line ~353–357): `if e.get("armed") and e.get("execution_allowed") and e.get("running")` → `if e.get("armed") and e.get("armable")`.
   - Pastikan TIDAK ada lagi referensi `execution_allowed` di seluruh file.

2. **`get_armed_terminals()`** (line ~741–762):
   - Hapus gate `if not entry.get("execution_allowed"): continue` (line ~757–758).
   - Sisa gate: armed + running (fail-closed tetap: stopped → drop).
   - Update docstring: "Return terminal ids armed AND running (B-10: running is the only eligibility condition; the `execution` config flag is ignored)."

3. **`get_fanout_targets()`** (line ~825–850):
   - Hapus gate `if not entry.get("execution_allowed"): continue` (line ~841–842).
   - Sisa gate: running + armed + fanout_target.
   - Update docstring: buang bullet "`execution: true` in the config"; ganti daftar syarat: "currently running, ARMED by the operator, `fanout_target` true (B-10: no execution flag gate)".

4. **`arm_terminal()`** (line ~853–924):
   - Hapus blok `if not entry["execution_allowed"]: return {...}` (line ~902–912) — terminal `execution:false` yang running HARUS bisa di-arm sekarang.
   - Syarat arm tersisa: exists di registry + running.
   - Update docstring (line ~856–868): buang klaim `"execution": true`; tulis: "Arming requires the terminal to exist in the registry and be currently running. Any running terminal (demo or live) can be armed — the per-terminal arm switch is the ONLY execution control (B-10). An attached binding is NOT required."
   - Disarm tetap selalu allowed (tidak berubah).

5. JANGAN ubah `execution_permitted()` (line ~961–983), `load_config()`, `update_terminal_config()`, `select_terminal()`, `scan_running_terminals()`.

### B. `services/python/src/mt5/endpoints.py`
- Docstring `list_terminals` (line ~93–98): `execution_allowed` → `armable` ("`armable` reflects whether the terminal is currently running; any running terminal can be armed").
- Docstring `arm_terminal_by_id` (line ~133–146): buang klaim "marked `\"execution\": true` ... can never be armed"; ganti: arming requires registry + running only.
- Docstring `arm_terminal` legacy (line ~117–125): buang syarat `"execution": true`.

## TEST YANG WAJIB DIUPDATE (satu paket dengan kode — jangan di-skip)

### `services/python/tests/test_mt5_terminals.py`
- Docstring modul line ~9: "arming requires: running + execution-enabled (attach NOT required, B-9)" → "arming requires: running only (attach NOT required; execution flag ignored, B-10)".
- Line ~139: `assert by_id["a"]["execution_allowed"] is False` → `assert by_id["a"]["armable"] is True` (a running).
- Line ~142: `assert by_id["c"]["execution_allowed"] is True` → `assert by_id["c"]["armable"] is False` (c NOT running). Update komentar.
- Line ~157: `assert auto[0]["execution_allowed"] is False  # never armable` → `assert auto[0]["armable"] is True` (running by definition) + tambahkan `assert auto[0]["fanout_target"] is True`.
- `test_arm_requires_execution_flag` (line ~294–304) → rename `test_arm_execution_flag_ignored`: terminal A `execution:false` running + selected → `arm_execution(True)` sekarang `ok is True` + `is_execution_armed() is True`; cleanup disarm di akhir test.
- `test_arm_ignores_binding_attachment` (~316–329) & `test_arm_succeeds_when_all_conditions_met` (~331–341): tetap, pastikan pass.
- `test_arm_execution_false_terminal_rejected` (line ~476–490) → rename `test_arm_execution_false_terminal_allowed`: vito2 `execution:false` running → `arm_terminal("vito2", True)` sekarang `ok is True`, `armed is True`, masuk `get_armed_terminals()`; lalu cleanup `arm_terminal("vito2", False)`.
- `test_arm_endpoint_rejects_ineligible` (line ~597–609) → rename `test_arm_endpoint_allows_execution_false_terminal`: vito2 `execution:false` running → endpoint `arm_terminal_by_id("vito2", ...)` sekarang SUKSES (`result["ok"] is True`, `armed_terminals == ["vito2"]`); cleanup disarm.
- `test_arm_endpoint_rejects_when_not_eligible` (line ~647–655): tetap (tidak running → 400). Pastikan pass.
- `test_get_armed_terminals_filters_ineligible` (~526–539): tetap (stopped → drop). Pastikan pass.
- Cek juga test lain di file ini yang mungkin assert field lama (grep `execution_allowed` di file → harus nol setelah update).

### `services/python/tests/test_fanout_multi_terminal.py`
- Docstring line ~7: "running + execution:true + armed + fanout_target" → "running + armed + fanout_target (B-10: execution flag ignored)".
- `test_fanout_targets_require_running_armed_eligible` (line ~61–79): buktikan gate lama hilang — jadikan terminal `c` (`execution: False`) juga RUNNING + armed → hasil `["a", "c"]` (b tetap excluded karena not running). Rename test → `test_fanout_targets_require_running_armed`.
- Test lain di file ini tidak boleh diubah selain yang perlu.

### `services/python/tests/test_task06_canonical_fanout.py`
- Line ~420: `assert entry["execution_allowed"] is True` → `assert entry["armable"] is True`.

### `services/python/tests/test_task12_adversarial_e2e.py`
- Line ~930: `assert entry["execution_allowed"] is True` → `assert entry["armable"] is True`.

JANGAN ubah `test_b9_multi_arm_hardening.py`, `test_terminal_selection.py` kecuali memang merah (diharapkan hijau tanpa perubahan). JANGAN ubah `test_b4_demo_validation.py`/`test_dual_import_unification.py` di task ini (fake-nya tidak membaca field asli; disapu di task berikutnya).

## VERIFIKASI (STOP GATE — semua harus PASS sebelum lapor)
1. Gate utama:
```
cd services/python && .venv/Scripts/python.exe -m pytest tests/test_mt5_terminals.py tests/test_terminal_selection.py tests/test_b9_multi_arm_hardening.py tests/test_fanout_multi_terminal.py tests/test_task06_canonical_fanout.py tests/test_task12_adversarial_e2e.py -q --basetemp=<tmp-fresh>
```
→ semua hijau, 0 failed.
2. Lint bersih pada file yang diubah:
```
cd services/python && .venv/Scripts/python.exe -m black --check src/mt5/terminals.py src/mt5/endpoints.py tests/test_mt5_terminals.py tests/test_fanout_multi_terminal.py tests/test_task06_canonical_fanout.py tests/test_task12_adversarial_e2e.py
.venv/Scripts/python.exe -m isort --check-only <file yang sama>
.venv/Scripts/python.exe -m flake8 src/mt5/terminals.py src/mt5/endpoints.py tests/test_mt5_terminals.py tests/test_fanout_multi_terminal.py tests/test_task06_canonical_fanout.py tests/test_task12_adversarial_e2e.py
```
3. Grep bukti:
```
grep -rn "execution_allowed" services/python/src services/python/tests apps/web
```
→ NOL (kecuali file test_b4/dual_import yang belum disapu di task ini — sebutkan sisanya di report).
4. `git diff --stat` TIDAK menyentuh `services/python/mt5_terminals.json`.
5. Bukti perilaku (di test): arm terminal `execution:false` running → `ok:true`; stopped → reject; auto-entry `armable:true`; `get_fanout_targets` mencakup terminal tanpa `execution:true`; `execution_permitted()` masih fail-closed.

## COMPLETION REPORT (bahasa Indonesia, format ini)
```
TASK: B-10 #1 / STATUS: PASS atau BLOCKED
FILES CHANGED: <daftar + ringkas per file>
ROOT CAUSE: <kenapa perubahan ini>
FIX: <per file, perilaku baru>
TESTS: <command + hasil per file + total pass/fail>
RUNTIME VERIFICATION: <bukti grep + perilaku baru per acceptance>
REMAINING ISSUES: <mis. sisa referensi execution_allowed di test_b4/dual_import → task berikutnya>
NEXT TASK: NOT STARTED
```
Kalau ada satu acceptance gagal → STATUS: BLOCKED dan STOP (jangan lanjut ke task lain).
