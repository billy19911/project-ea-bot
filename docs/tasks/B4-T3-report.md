# B-4 T3 — Restart Recovery Validation (Report)

Status: DONE (kode + unit test + live run dua proses terpisah terhadap bil2). No commit.
Parent plan: `docs/plans/B4-LIVE-DEMO-VALIDATION.md` (T3)
Blocker ref: `docs/audit/RELEASE_BLOCKERS.md` → B-4 (lines 64–79)
Depends on: T1 (ticket `1353670649` dibiarkan OPEN) + T2 (reconciliation matched)

## Goal (yang dibuktikan)

Setelah proses service/harness **restart**:

1. Durable ledger (`services/python/logs/order_state.jsonl`) tetap memuat order T1.
2. `OrderStateStore` **rehidrasi** record dari FILE ke memory saat `__init__`.
3. Reconciliation fresh tetap **match** ticket T1 terhadap broker.
4. Arm state (in-memory by design) **hilang** saat restart → **wajib re-arm** — lalu
   re-arm bil2 dan dokumentasikan siklus penuhnya.

## Desain: dua proses terpisah (inilah "restart" yang genuine)

`recovery-check` dijalankan sebagai **dua invokasi proses terpisah**:

```
python scripts/b4_demo_validation.py recovery-check --stage pre
python scripts/b4_demo_validation.py recovery-check --stage post
```

Karena keduanya proses OS terpisah, memory (`_order_store` dan arm flag) benar-benar
kosong di awal proses `post` — jadi rehidrasi **harus** datang dari FILE, bukan dari
sisa cache proses sebelumnya. Inilah buktinya, bukan sekadar klaim.

- **Stage `pre`** — baca ticket T1 dari evidence JSON → konfirmasi record-nya ada di
  FILE ledger → arm bil2 (mekanisme yang sama dengan T1) → snapshot arm state.
- **Stage `post`** (proses baru) — buang store memory (`set_store(None)+reset_store()`),
  bangun `OrderStateStore()` **baru** (rehidrasi dari disk) → assert state T1 terbaca →
  assert arm state **KOSONG** → jalankan reconciliation → assert ticket T1 match →
  re-arm bil2 → konfirmasi armed.

## Bukti kunci: state bertahan lewat FILE (bukan memory)

Ledger `services/python/logs/order_state.jsonl` (append-only) memuat:

```
{"intent_id": "b4-t1-1353670649", "state": "position_confirmed", "timestamp": "2026-09-26T13:40:18.687767+00:00", "ticket": 1353670649}
{"intent_id": "b4-t1-1353670649", "state": "position_confirmed", "timestamp": "2026-09-26T13:41:12.360502+00:00", "ticket": 1353670649}
{"intent_id": "b4-t1-1353670649", "state": "position_confirmed", "timestamp": "2026-09-26T13:41:40.749124+00:00", "ticket": 1353670649}
```

Proses `post` adalah proses baru: `arm_state_post_restart.execution_armed == false`
membuktikan memory memang kosong, NAMUN `rehydrated_state == "position_confirmed"`
terbaca oleh `OrderStateStore()` yang baru — jadi state itu datang dari FILE.

## Stage `pre` — output verbatim

```
[OK  ] t1_ticket: t1 ticket=1353670649
[OK  ] ledger_file_record: ticket=1353670649 state=position_confirmed intent_id=b4-t1-1353670649 in logs\order_state.jsonl
[OK  ] arm: terminal 'bil2' armed and execution permitted
[OK  ] arm_state_pre: armed=True armed_terminals=['bil2'] permitted=True
[OK  ] stage_pre: pre-restart state captured
Pre-restart: T1 ticket present in ledger FILE + arm state captured. Next: run 'recovery-check --stage post' as a SEPARATE process.
```

Exit code **0**. Snapshot arm state pre-restart:

| Field | Value |
| --- | --- |
| `execution_armed` | `true` |
| `armed_terminals` | `["bil2"]` |
| `terminal_selected` | `true` |
| `execution_permitted` | `true` |
| `saved_selection` | `"bil2"` (persisted — selamat dari restart) |

## Stage `post` — output verbatim (proses terpisah)

```
[OK  ] t1_ticket: t1 ticket=1353670649
[OK  ] rehydrate: ticket=1353670649 rehydrated state=position_confirmed from logs\order_state.jsonl
[OK  ] arm_cleared: armed=False armed_terminals=[] (expected empty after restart)
[OK  ] attach_connector: connector live_mode=True path=E:\MT5 XYNN EA\MetaTrader 5 BIL 2\terminal64.exe
[OK  ] reconcile_post: ticket=1353670649 matched=True critical=True mismatches=17
[OK  ] arm: terminal 'bil2' armed and execution permitted
[OK  ] rearm: re-armed 'bil2': armed=True permitted=True
Post-restart: ticket rehydrated from FILE + reconciled + arm was EMPTY → re-armed. Recovery cycle COMPLETE.
```

Exit code **0**.

## Siklus arm: cleared → re-armed (by design, bukan bug)

| Titik | `execution_armed` | `armed_terminals` | `execution_permitted` |
| --- | --- | --- | --- |
| `pre` (akhir proses pre) | `true` | `["bil2"]` | `true` |
| `post` awal (setelah "restart") | **`false`** | **`[]`** | **`false`** |
| `post` setelah re-arm | `true` | `["bil2"]` | `true` |

Arm state **in-memory by design** (`src/mt5/terminals.py`, `_terminal_states`) → hilang
saat proses mati. Selection **dipersist** (`mt5_selected.json` → `{"selected_id":"bil2"}`),
terlihat di `saved_selection`. Re-arm setelah restart adalah **WAJIB & diharapkan** — ini
perilaku fail-closed yang benar, bukan regresi. Harness meng-arm ulang lewat mekanisme
yang sama dengan T1 (`mt5.terminals` in-process), bukan bypass.

## Reconciliation setelah restart

- `t1_ticket_matched: true`, `matched: [1353670649]` — ticket T1 tetap cocok.
- `missing_internal: []` — tidak ada posisi broker yang tak dikenal ledger.
- `has_critical: true`, `total_mismatches: 17` — **identik** dengan T2 (3 field-diff
  *expected_ledger_shape_gap* pada pasangan matched + 14 record lama `missing_in_broker`
  sebagai lifecycle artifact append-only ledger). Tidak ada mismatch baru yang muncul
  akibat restart. Posisi T1 **tidak ditutup**.

## Evidence

- `docs/evidence/B-4-demo-validation.json` → section `t3`:
  - `t3.pre` (output stage pre) dan `t3.post` (output stage post) — **keduanya tersimpan**
    karena masing-masing proses menulis ke subkey-nya sendiri (`pre`/`post`), tidak saling
    menimpa. Plus `stages_present: ["pre","post"]` dan `both_stages_present: true`.
  - Section `t1`/`t2` tetap utuh.
- `docs/evidence/B-4-demo-validation.md` → dua section
  `## T3 — Restart recovery ('pre' stage)` / `('post' stage)`.

## Unit tests (mock/tmpfile-based, tanpa broker)

`services/python/tests/test_b4_demo_validation.py` — tambah 12 test T3 (total 49):

1. `test_recovery_check_dispatches_to_cmd` — CLI `recovery-check --stage pre` → `_cmd_recovery_check`.
2. `test_recovery_check_requires_stage` — `--stage` wajib (argparse menolak).
3. `test_rehydration_round_trip_state_survives_new_store` — tulis ledger → `OrderStateStore()`
   baru → state terbaca dari disk.
4. `test_rehydration_from_file_not_memory` — wipe memory → wiring store baru → state pulih dari FILE.
5. `test_recovery_pre_records_ledger_file_and_arm_state` — stage pre: record FILE + armed.
6. `test_recovery_pre_aborts_without_ledger_record` — fail-closed bila ticket tak ada di FILE.
7. `test_recovery_post_rehydrates_reconciles_and_rearms` — siklus penuh: rehidrasi + matched +
   arm-empty + re-arm.
8. `test_recovery_post_aborts_if_not_rehydrated` — fail-closed bila rehidrasi gagal.
9. `test_recovery_post_detects_arm_not_cleared` — bila arm ternyata tidak kosong → abort (surface bug).
10. `test_recovery_post_aborts_if_unmatched` — fail-closed bila reconciliation tak match.
11. `test_recovery_post_writes_t3_section_preserving_t1_t2` — `t3.post` di-merge, `t1`/`t2` utuh.
12. `test_recovery_pre_and_post_merge_into_both_stages` — pre+post (proses terpisah) → keduanya
    ada di JSON `t3`, `both_stages_present=true`.

Fixture autouse `isolate_order_ledger` (T2) menunjuk ledger ke `tmp_path` +
`reset_store()`+`set_store(None)`, jadi tidak bocor ke ledger operator.

## Acceptance checklist

- [x] Unit tests GREEN (mock/tmpfile): `tests/test_b4_demo_validation.py` → **49 passed**
      (T1 29 + T2 8 + T3 12).
- [x] `--stage pre` + `--stage post` dijalankan sebagai **DUA PROSES TERPISAH** terhadap bil2:
      pre → ticket di ledger FILE + armed=True; post → ticket rehidrasi + matched +
      arm EMPTY → re-armed. Keduanya exit **0**.
- [x] Evidence JSON section `t3` dengan **kedua** stage output (`t3.pre`, `t3.post`).
- [x] flake8 (`--max-line-length=100 --extend-ignore=E203,W503`) + black clean.
- [x] Full suite: **2242 passed** (baseline T2 2230 + 12 test T3 baru), tanpa regresi.

## Files changed

- `scripts/b4_demo_validation.py` — implement subcommand `recovery-check`
  (`run_recovery_check`, `_recovery_stage_pre`, `_recovery_stage_post`,
  `_write_recovery_evidence`, `_ledger_file_path`, `_read_ledger_records`,
  `_ledger_record_for_ticket`, `_arm_state_snapshot`, `_saved_selection`,
  `_wire_fresh_store`, `_store_state_for_ticket`) + parser `--stage` + `_cmd_recovery_check`.
- `services/python/tests/test_b4_demo_validation.py` — 12 test T3 (`FakeArmStateTerminals`,
  helper `_seed_ledger_record`/`_make_recovery_harness`).
- `docs/evidence/B-4-demo-validation.json` — section `t3` (`pre` + `post`).
- `docs/evidence/B-4-demo-validation.md` — dua section `## T3`.
- `docs/tasks/B4-T3-report.md` — laporan ini.

Tidak ada file `src/**` yang diubah (gate/arm/persistence tidak disentuh). Tidak ada commit.

## Catatan jumlah test

File test: baseline T1+T2 = 37, kini = 49 (+12 test T3). Full suite: baseline **2230**
(T2 report) → kini **2242** (+12, tepat). Test stub lama `recovery-check`
(`test_recovery_check_stub_raises`) digantikan oleh dua test dispatch/parse T3
(`test_recovery_check_dispatches_to_cmd`, `test_recovery_check_requires_stage`);
net keseluruhan tetap +12 karena stub lama ada di luar hitungan 37 baseline file ini
(tidak dihitung sebagai test T3 baru).

## Verification commands

```
services/python/.venv/Scripts/python.exe -m pytest tests/test_b4_demo_validation.py -q
services/python/.venv/Scripts/python.exe -m pytest -q
services/python/.venv/Scripts/python.exe -m flake8 --max-line-length=100 --extend-ignore=E203,W503 \
    scripts/b4_demo_validation.py services/python/tests/test_b4_demo_validation.py
services/python/.venv/Scripts/python.exe -m black --check \
    scripts/b4_demo_validation.py services/python/tests/test_b4_demo_validation.py
services/python/.venv/Scripts/python.exe scripts/b4_demo_validation.py recovery-check --stage pre
services/python/.venv/Scripts/python.exe scripts/b4_demo_validation.py recovery-check --stage post
```
