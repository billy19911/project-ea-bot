# B-4 — Controlled DEMO Validation (Live Broker Path)

Status: DRAFT — menunggu persetujuan user sebelum delegasi ke OpenCode.
Tanggal: 2026-09-26
Konteks: Blocker terbuka TERAKHIR di `docs/audit/RELEASE_BLOCKERS.md` (B-4, P0 for live readiness).
Definisi acceptance (verbatim):

> "Perform a controlled DEMO-account validation (arm a demo terminal, place a small order,
> verify fill/confirmation/reconciliation/restart recovery) and record the evidence
> before any live deployment"

Residual terkait (B-3): `/mt5/orders/execute` masih surface paper (memanggil connector, bukan
executor) — gating endpoint ini opsional (T5), BUKAN syarat B-4.

## Temuan recon (2026-09-26)

1. **Jalur eksekusi native** = `ExecutionEngine._send_to_mt5()` (`src/execution/engine.py:722-960`).
   Gate berlapis (semua fail-closed):
   - `import MetaTrader5` (venv OK, v5.0.6180) — tanpa lib → fallback simulated/refuse jujur.
   - `_native_execution_armed()` = terminal attached + `execution:true` + armed; tidak armed → 403.
   - `require_approval=True` → butuh `approval_token` dari Risk Gate; tanpa token → 403 sebelum dispatch.
   - Catatan: `simulation_mode=True` TIDAK memblokir native path selama `require_approval=True`
     (baris 831: kondisi simulated hanya jika `not require_approval`).
2. **Wiring runtime shipped** (`orchestration/runtime.py:420`):
   `ExecutionEngine(mt5_connector=None, simulation_mode=True, require_approval=True)`.
3. **State machine durable**: `execution.state_machine.set_store(OrderStateStore())` di
   `main.py:161-171` → `services/python/logs/order_state.jsonl` (append-only, di-reload saat startup).
   Lifecycle: intent_created → risk_approved → submitting → submitted → acknowledged → filled →
   position_confirmed.
4. **Reconciliation**: `execution/reconciliation_providers.py` — sisi internal dari `_order_store`
   (state filled/position_confirmed + ticket), sisi broker dari connector read-only.
   `/reconciliation/status` sekarang: history_count 8, source live.
5. **Arm gate in-memory** (`mt5/terminals.py`) → HILANG saat restart (by design);
   selection persisted di `mt5_selected.json` (`{"selected_id":"bil2"}`).
6. **bil2** = satu-satunya terminal `execution:true`; saat recon `running:false` (terminal MT5 belum
   dibuka) → probe 400 "Tidak ada terminal yang berjalan".
7. **Bukti order DEMO sebelumnya** (25 Sep): ticket 1352094141/1352313902/1352414292/1352414491 ada di
   `order_state.jsonl` + lessons PnL, TAPI tidak ada evidence formal di repo (`docs/evidence/` belum ada).
   B-4 = validasi TERKONTROL + evidence terdokumentasi (bukan sekadar pernah terjadi).
8. **Pasar**: XAUUSD tutup weekend → live run hanya saat market buka (retcode 10018 = market closed).
9. `/mt5/orders/execute` = connector paper (residual B-3) — BUKAN jalur yang divalidasi B-4.

## Desain (T1–T5)

### T1 — Harness validasi end-to-end + unit test (TDD)
Files: `scripts/b4_demo_validation.py` (baru), `services/python/tests/test_b4_harness.py` (baru).
- Harness (default READ-ONLY; order hanya dengan flag eksplisit `--place-order`):
  1. Guard DEMO: `mt5.initialize(path=bil2)` → `account_info()` → WAJIB `trade_mode==0` (DEMO)
     + server mengandung "Demo"; kalau bukan → ABORT (tanpa order).
  2. Select + attach + arm bil2 via modul `mt5.terminals` in-process (sama seperti proses service).
  3. Order kecil: XAUUSD, volume = minimum symbol (≤0.01), SL/TP diset; lewat `ExecutionEngine`
     dengan wiring identik runtime + `approval_token="gate:b4-<run-id>"`.
  4. Verifikasi: `confirm_execution(ticket)` + `positions_get(ticket)` + deal history.
  5. Evidence JSON → `docs/evidence/` (account, ticket, retcode, price, latency, state machine).
- Unit test (tanpa order nyata): guard DEMO menolak non-demo; fail-closed saat tidak armed;
  urutan langkah; parsing evidence.
- Acceptance: unit test hijau; live run → ticket + retcode 0 + posisi terkonfirmasi.

### T2 — Reconciliation live
Files: `services/python/tests/test_b4_reconciliation_live.py` (baru); live: jalankan runner/endpoint.
- Setelah order T1: internal ledger (order_state.jsonl) vs broker positions → matched untuk ticket B-4.
- Live: `GET /reconciliation/status` → `matched` memuat ticket; `total_mismatches` 0, `critical` false.
- Acceptance: matched entry ticket B-4; tanpa false positive.

### T3 — Restart recovery
Files: unit test simulasi + live restart.
- Simulasi (unit): tulis state → reload `OrderStateStore` → state terbaca (POSITION_CONFIRMED persist).
- Live: restart Python via `scripts/restart-py.ps1` → verifikasi:
  (a) order_state.jsonl tetap memuat ticket B-4 dengan state akhir;
  (b) reconciliation setelah restart tetap match;
  (c) arm hilang → re-arm (by design, didokumentasikan);
  (d) `/health` 200.
- Acceptance: semua terverifikasi + dicatat di evidence.

### T4 — Evidence + update status blocker
Files: `docs/evidence/B-4-demo-validation.md` (baru), `docs/audit/RELEASE_BLOCKERS.md` (update B-4).
- Evidence: timestamp, account (login/server/trade_mode/balance), terminal, order (ticket, symbol,
  vol, price, retcode, latency), fill confirmation, reconciliation, restart recovery, raw outputs.
- Update B-4 → FIXED dengan pointer evidence; residual B-3 tetap dicatat.

### T5 (opsional, keputusan user) — hardening `/mt5/orders/execute`
- Gate endpoint di jalur approval yang sama (atau tandai eksplisit paper-only) → menutup residual B-3.
- Bukan syarat B-4; bisa ditunda.

## Dependency operasional (live run)
- MT5 BIL 2 harus running + login DEMO (harness bisa `mt5.initialize(path)` auto-start; jika gagal →
  user buka manual).
- Market buka (XAUUSD tutup weekend; retcode 10018 = market closed → tunggu sesi buka).
- T1–T2 (kode + unit test) bisa dikerjakan kapan pun; live run T1–T3 saat market buka.

## Safety
- Guard DEMO wajib (abort bila bukan trade_mode 0) — tidak ada jalur order ke akun live.
- Volume minimum; 1 order per run; tanpa loop.
- Arm eksplisit + require_approval (fail-closed ganda).
- Tidak commit (aturan tetap); preserve user changes.

## Verifikasi akhir (supervisor, bukan percaya summary OpenCode)
- Unit test baru + full pytest hijau (baseline 2193, tidak boleh merah).
- flake8 (max 100) + black --check hijau untuk file baru.
- Live evidence dicek manual: ticket di MT5 (positions/deals), order_state.jsonl, reconciliation status.
- `RELEASE_BLOCKERS.md` B-4 diperbarui dengan pointer evidence.
