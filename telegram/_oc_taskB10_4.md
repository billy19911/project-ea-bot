# TASK B-10 #4 — Test baru: `test_b10_auto_detect_terminals.py`

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. BACA dulu: `docs/tasks/B-10-auto-detect-active-terminals.md` section "TASK 4".
Prasyarat: TASK 1–3 SUDAH selesai (kode terminals.py + engine.py sudah berubah; test lama sudah disapu).

Safety: DISARMED by default; DILARANG `git commit`/`git push`; DILARANG menyentuh `services/python/mt5_terminals.json`; DILARANG mengubah `src/**` di task ini (HANYA buat file test baru); jangan start/stop server.

## GOAL
File test BARU `services/python/tests/test_b10_auto_detect_terminals.py` yang membuktikan seluruh acceptance B-10 end-to-end di level modul (tanpa MT5 nyata, tanpa order nyata). Ikuti pola yang sudah ada di `test_mt5_terminals.py` / `test_fanout_multi_terminal.py` (fixture `_clean_state` reset state global; `_use_config` menulis config ke tmp + env `MT5_TERMINALS_CONFIG`; `scan_running_terminals` dan `_detect_attached_path` di-monkeypatch).

## 8 SKENARIO WAJIB (satu test per skenario, nama jelas ber-prefix `test_b10_`)
1. `test_b10_arm_execution_false_running_ok` — config `vito2` `execution:false` + running → `arm_terminal("vito2", True)` → `ok is True`, `armed is True`, `get_armed_terminals() == ["vito2"]`; cleanup disarm.
2. `test_b10_arm_auto_detected_terminal_ok` — terminal running TIDAK ada di config → tampil di view dengan `source == "auto"` + `armable is True` + `fanout_target is True` → `arm_terminal("auto-<pid>", True)` → `ok is True`; masuk `get_armed_terminals()`.
3. `test_b10_arm_stopped_rejected_fail_closed` — terminal di config tapi TIDAK running → `arm_terminal(id, True)` → `ok is False`, `"not running" in message.lower()`; `get_armed_terminals() == []`.
4. `test_b10_fanout_targets_ignore_execution_flag` — 2 terminal di config: `execution:false` + running + `fanout_target:true`, dan `execution:true` + running → arm keduanya → `get_fanout_targets()` berisi KEDUANYA (tanpa gate `execution`); lalu set scan → [] (keduanya stop) → `get_fanout_targets() == []` (drop saat mati).
5. `test_b10_execution_permitted_still_requires_attached` — arm terminal running tapi binding attached ke terminal LAIN (`_detect_attached_path` → folder lain / None) → `execution_permitted() is False` (fail-closed); lalu `_detect_attached_path` → folder terminal yang armed → `execution_permitted() is True`.
6. `test_b10_armed_terminal_stops_dropped_everywhere` — arm terminal running → `get_armed_terminals() == [id]` + `get_fanout_targets()` memuatnya → `scan_running_terminals` → [] (terminal mati) → `get_armed_terminals() == []` DAN `get_fanout_targets() == []`; setelah "hidup lagi" → muncul kembali (state arm persist, bukan di-reset).
7. `test_b10_sizing_fallback_signal_volume` — unit `ExecutionEngine._size_for_terminal`: pasang fake `MetaTrader5` di `sys.modules` (SimpleNamespace/ModuleType dengan `account_info`/`symbol_info` minimal — lihat pola `_FakeMT5` di `test_fanout_multi_terminal.py`) → `_size_for_terminal({}, 100.0, 1.0, "XAUUSD", fallback_volume=0.10)` → `0.10`; `{fixed_lot: 0.05}` → `0.05` (prioritas fixed); `fallback_volume=0.0` → `0.0` (fail-closed).
8. `test_b10_default_state_all_disarmed` — tanpa arm eksplisit: view `execution_armed is False`, `armed_terminals == []`, semua entry `armed is False`; `get_armed_terminals() == []`; `get_fanout_targets() == []`.

## FILE BARU — struktur
```python
# -*- coding: utf-8 -*-
"""B-10 — auto-detect active terminals: running is the only arm gate.

Proves: arm works for execution:false + auto-detected terminals, stopped
terminals fail closed, fan-out has no execution-flag gate, execution_permitted
still requires an attached binding, sizing falls back to the signal volume,
and the default state is DISARMED.
"""
```
+ import `importlib`, `json` bila perlu, `pytest`; `terminals = importlib.import_module("mt5.terminals")`; `engine_mod = importlib.import_module("execution.engine")`.
+ Fixture autouse `_clean_state` (sama persis dengan test_mt5_terminals.py — reset `_selected_id`, `_execution_armed`, `_terminal_states`, `_mirror_selected`, `_mirror_armed`, `_account_cache`, `_account_cache_ts` sebelum & sesudah).
+ Helper `_use_config`, `_fake_running(folder, pid)`, `_fake_attached(folder)`.
+ CONFIG_B10 contoh: `bil2` (execution:true), `vito2` (execution:false), `third` (execution:false).
+ Untuk skenario 7: fake MT5 minimal (butuh `account_info().equity`? TIDAK — fallback tidak membaca equity; cukup `symbol_info`/`symbol_info_tick` bila clamp menyentuh; clamp memakai `symbol_info(symbol)` → kembalikan `None` → aman; tapi `_size_for_terminal` meng-import MetaTrader5 HANYA di cabang risk_pct — fallback TIDAK import → cukup pastikan tidak error).

## VERIFIKASI (STOP GATE)
1. ```
cd services/python && .venv/Scripts/python.exe -m pytest tests/test_b10_auto_detect_terminals.py -q --basetemp="C:\Users\billy\AppData\Local\Temp\pa_b10_t4"
```
→ 8 passed (atau lebih), 0 failed.
2. Regresi file-file terkait tetap hijau:
```
.venv/Scripts/python.exe -m pytest tests/test_mt5_terminals.py tests/test_fanout_multi_terminal.py tests/test_b9_multi_arm_hardening.py -q --basetemp="C:\Users\billy\AppData\Local\Temp\pa_b10_t4b"
```
3. Lint file baru (black/isort/flake8, line-length 100, extend-ignore E203,W503).

## COMPLETION REPORT (Indonesia, format sama sebelumnya)
```
TASK: B-10 #4 / STATUS: PASS atau BLOCKED
FILES CHANGED (file baru) / ROOT CAUSE / FIX / TESTS (per skenario) / RUNTIME VERIFICATION / REMAINING ISSUES / NEXT TASK: NOT STARTED
```
Jika ada satu skenario gagal → BLOCKED dan STOP.
