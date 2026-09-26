# LEDGER-SLTP T2 — REPORT (Stale Ledger Backfill)

**Tanggal:** 2026-09-26
**Status:** ✅ SELESAI (ops dijalankan orchestrator setelah OpenCode stuck di fase restart)
**Task:** CERT-B1 ≡ LEDGER-SLTP T2
**Brief:** `docs/tasks/LEDGER-SLTP-T2-stale-backfill.md`

---

## 1. Ringkasan

Ledger `services/python/logs/order_state.jsonl` berisi 15 record `position_confirmed` BASI
(posisi sudah lama tidak ada di broker; 0 record `closed`). Setiap record dihitung sebagai
posisi internal terbuka selamanya → `ReconciliationGuard` fail-close SEMUA order baru.

**Hasil:** 15 record di-backfill → `closed` (reason `stale_backfill`). Reconciliation bersih
(0 mismatch, `critical=false`), guard unblocked (`last_ok=True`). Idempotent — re-run 0 kandidat.

---

## 2. Temuan kritis (HAZARD paper-vs-live)

Script `scripts/ledger_close_stale.py` saat dijalankan **standalone** memuat `src.mt5.connector`
dalam **simulation mode** → `get_positions_ex()` mengembalikan `(ok=True, [dummy 1001, dummy 1002])`.
Artinya "verified read" menjadi palsu: setiap ticket nyata terlihat "absent from broker".

**Bukti (dry-run standalone, `b4_b1_dryrun_standalone.txt`):**
```
Broker positions: 2 ticket(s)      <-- dummy simulasi 1001/1002
Candidates: 15
```

**Fix:** wrapper baru `scripts/ledger_backfill_live.py` yang:
1. resolve terminal path (default `E:\MT5 XYNN EA\MetaTrader 5 BIL 2\terminal64.exe`, override `MT5_TERMINAL_PATH`);
2. attach read-only `connector.use_live_data_mode(path=...)` → abort (exit 2) jika gagal;
3. verifikasi `get_positions_ex()` `ok=True` → abort (exit 2) jika tidak;
4. delegasi ke `StaleBackfill` yang sama (dry-run default, `--apply` untuk menulis).

**Bukti (dry-run live, `b4_b1_dryrun_live.txt`):**
```
Live attach OK — broker positions: 0 ticket(s)
Candidates: 15
```

---

## 3. Eksekusi

| Langkah | Perintah | Hasil |
|---|---|---|
| Backup ledger | `cp ... b4_order_state_backup_preB1.jsonl` | 771 lines |
| Dry-run standalone (hazard) | `python scripts/ledger_close_stale.py` | 2 dummy tickets — HAZARD terbukti |
| Dry-run live | `python scripts/ledger_backfill_live.py` | 0 tickets broker, 15 kandidat |
| Apply | `python scripts/ledger_backfill_live.py --apply` | **15 record closed (reason=stale_backfill)** |
| Re-run (idempotensi) | `python scripts/ledger_backfill_live.py --apply` | 0 kandidat, 15 already closed, 0 written |
| Restart service | `scripts/restart-py.ps1` | `[OK] python :8787 sehat` |
| Force reconciliation | `POST /reconciliation/run` | 0 mismatch, `critical=false` |

**State ledger final:** `{acknowledged: 40, unknown: 41, submitting: 143, closed: 15}` — 0 `position_confirmed` tersisa.

---

## 4. Verifikasi independen

1. **Store vs provider (in-process, cwd `services/python`):**
   `OrderStateStore().all_orders()` → 243 orders; `internal_positions_from_store(orders)` → `[]`
   → benar-benar bersih (bukan false-clean: broker live juga 0 posisi).
2. **Live endpoints:**
   - `GET /reconciliation/status` → `last_report.total_mismatches=0`, `critical=false`, `history_count=2`, `source=live`.
   - `GET /mt5/positions` → `{"positions":[],"count":0}`.
   - `GET /health` → `status: ok`.
3. **Guard:** `ReconciliationGuard.check_can_execute()` → `last_ok=True` (recon terakhir bersih) → order baru tidak diblokir.
4. **Tests:** `tests/test_ledger_backfill.py` → **13 passed**.
5. **Lint:** flake8 `--max-line-length=100 --extend-ignore=E203,W503` → 0; black `--line-length 100` → clean.

---

## 5. File yang berubah

| File | Perubahan |
|---|---|
| `scripts/ledger_close_stale.py` | (sudah ada dari fase OpenCode) + black reformat minor (line-join) |
| `scripts/ledger_backfill_live.py` | **BARU** — wrapper attach live + fail-closed |
| `services/python/tests/test_ledger_backfill.py` | (sudah ada) + black reformat minor |
| `services/python/logs/order_state.jsonl` | +15 record `closed` (append-only) |
| `b4_order_state_backup_preB1.jsonl` | Backup pre-apply (771 lines) |
| `b4_b1_dryrun_standalone.txt` / `b4_b1_dryrun_live.txt` / `b4_b1_apply.txt` / `b4_b1_restart.txt` | Bukti eksekusi |

---

## 6. Catatan jujur

- OpenCode mengerjakan script + tests sampai selesai, lalu **stuck** di fase restart service
  (log statis >10 mnt, tanpa child process, tanpa koneksi network ESTABLISHED) → di-kill;
  orchestrator mengambil alih ops sesuai protokol anti-stuck.
- **Pelajaran anti-stuck:** jangan suruh OpenCode menjalankan `scripts/restart-py.ps1`
  (wrapper timeout by design → proses tampak hang). Restart service dilakukan dari orchestrator.
- Tidak ada commit (sesuai guardrail).
- Kill switch masih `triggered`+`locked` (reason `execution_error` lama) — **di luar scope T2**,
  ditangani di CERT-B2.
