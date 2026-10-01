# TASK B-10 #2 — engine.py: sizing fallback ke volume sinyal

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. BACA dulu: `docs/tasks/B-10-auto-detect-active-terminals.md` section "TASK 2".
Prasyarat: TASK 1 (terminals.py eligibility=running) SUDAH selesai & lulus gate.

Safety: DISARMED by default; DILARANG `git commit`/`git push`; DILARANG menyentuh `services/python/mt5_terminals.json`; DILARANG mengubah `execution_permitted()`; jangan start/stop server (semua sudah jalan).

## GOAL
Terminal yang bisa di-arm sekarang termasuk terminal auto-detect/running tanpa konfigurasi sizing (`fixed_lot`/`risk_per_trade_pct` tidak ada di mt5_terminals.json). Saat ini `_size_for_terminal` mengembalikan 0.0 untuk mereka → order fan-out GAGAL ("Volume lot tidak valid (0)"). B-10: fallback ke **volume sinyal** (volume dari base request). Prioritas final: `fixed_lot` → `risk_per_trade_pct` → **volume sinyal (fallback)** — semua tetap di-clamp `[min_volume, max_lot_per_trade or max_volume]` + normalisasi `volume_step`.

## PERUBAHAN KODE (WAJIB)

### `services/python/src/execution/engine.py`
1. **`_size_for_terminal`** (line ~1224–1287): tambah parameter `fallback_volume: float = 0.0` (keyword, default 0.0 agar kompatibel). Ubah rantai prioritas:
   - `fixed_lot` valid (>0) → `vol = fixed`
   - elif `risk_per_trade_pct` valid + `risk_price > 0` → hitung dari equity (TIDAK BERUBAH)
   - **BARU:** else → `vol = float(fallback_volume or 0.0)`
   - Hapus `vol = 0.0` pada cabang else terakhir (line ~1266–1267) — ganti dengan fallback.
   - Blok `if vol <= 0: return 0.0` tetap (fallback 0 pun tetap fail-closed).
   - Clamp + volume_step normalization TIDAK BERUBAH.
   - Update docstring: tambah penjelasan fallback "→ signal volume (`fallback_volume`) when the terminal has no sizing configured (B-10: auto-detected/running terminals without config must still trade the signal lot)".
2. **Call site** (line ~1190): `volume = self._size_for_terminal(target, entry, risk_price, symbol, fallback_volume=request.volume)`.
3. JANGAN ubah `execute_order_fanout` lainnya, JANGAN ubah `_dispatch_one` (re-pricing/SL-TP), JANGAN ubah `execution_permitted`.

### TEST (satu paket)
### `services/python/tests/test_fanout_multi_terminal.py`
- Tambah test baru `test_fanout_sizing_falls_back_to_signal_volume`:
  - 2 target TANPA `fixed_lot`/`risk_per_trade_pct` (hanya id/label/path) → `execute_order_fanout(_request(), ...)` sukses 2/2; `vols == [0.10, 0.10]` (volume sinyal `_request()` = 0.10).
  - 1 target `fixed_lot: 0.05` + 1 target tanpa sizing → `vols == [0.05, 0.10]` (prioritas fixed tetap menang).
- Tambah test `test_size_for_terminal_fallback_and_clamp` (unit, tanpa MT5): panggil `engine._size_for_terminal({}, 100.0, 1.0, "XAUUSD", fallback_volume=0.10)` dengan fake MT5 terinstall → `0.10`; fallback di atas `max_lot_per_trade` → ter-clamp; `fallback_volume=0.0` → `0.0` (fail-closed).
- Test lama TIDAK BOLEH diubah selain yang perlu; semua harus tetap hijau.

## VERIFIKASI (STOP GATE)
```
cd services/python && .venv/Scripts/python.exe -m pytest tests/test_execution_engine.py tests/test_fanout_multi_terminal.py -q --basetemp=<tmp-fresh>
```
→ 0 failed.
Lint: black/isort/flake8 pada `src/execution/engine.py` + `tests/test_fanout_multi_terminal.py`.
Bukti perilaku: grep `fallback_volume` di engine.py (ada di signature + call site); jalankan test baru via `-k fallback` dan lampirkan output.

## COMPLETION REPORT (Indonesia, format sama TASK 1)
```
TASK: B-10 #2 / STATUS: PASS atau BLOCKED
FILES CHANGED / ROOT CAUSE / FIX / TESTS / RUNTIME VERIFICATION / REMAINING ISSUES / NEXT TASK: NOT STARTED
```
Jika ada acceptance gagal → BLOCKED dan STOP.
