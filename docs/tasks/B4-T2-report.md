# B-4 T2 — Live Reconciliation Validation (Report)

Status: DONE (kode + unit test + live run terhadap bil2). No commit.
Parent plan: `docs/plans/B4-LIVE-DEMO-VALIDATION.md` (T2)
Blocker ref: `docs/audit/RELEASE_BLOCKERS.md` → B-4 (lines 64–79)
Depends on: T1 (`scripts/b4_demo_validation.py`, posisi T1 ticket `1353670649` dibiarkan OPEN)

## What ran

`python scripts/b4_demo_validation.py reconcile` (dijalankan dari `services/python`,
import bootstrap T1 meng-`chdir` + menaruh `services/python` di `sys.path`).

Alur in-process (sama persis dengan jalur service, TIDAK lewat HTTP/API key):

1. **Join key** — baca ticket T1 dari `docs/evidence/B-4-demo-validation.json` (`t1`),
   sumber pertama `execution_result.ticket` → **`1353670649`**.
2. **Internal side** — `set_store(OrderStateStore())` (sama seperti `main.py`), jadi
   `execution.state_machine._order_store` di-rehidrasi dari
   `services/python/logs/order_state.jsonl`.
3. **Broker side** — `connector.use_live_data_mode(path=<terminal64.exe bil2>)`
   (mekanisme yang sama dipakai `mt5.terminals.select_terminal`), sehingga
   `MT5ReconciliationProviders.broker_positions()` membaca posisi broker yang asli.
4. **Providers wiring** — `OrchestrationRuntime._default_reconciliation_providers()`
   (dipakai ulang, tidak ditulis ulang): connector live → `MT5ReconciliationProviders()`.
5. **Run** — `ReconciliationRunner(interval=1, providers=...).run_once()` →
   `Reconciler.compare(...)` → `ReconciliationReport`.

Output live (verbatim):

```
[OK  ] t1_ticket: t1 ticket=1353670649
[OK  ] attach_connector: connector live_mode=True path=E:\MT5 XYNN EA\MetaTrader 5 BIL 2\terminal64.exe
[OK  ] reconcile: t1 ticket=1353670649 matched=True critical=True mismatches=17
T1 ticket: 1353670649
Matched tickets: [1353670649]
Missing in broker: [1348784058, 1348874223, 1348874358, 1348963010, 1348984819, 1349697094, 1349909054, 1350068378, 1350246238, 1352094141, 1352313902, 1352414292, 1352414491, 1352688152]
Missing internal: []
has_critical: True
  field diff ticket=1353670649 field=volume internal=None broker=0.01 [expected_ledger_shape_gap]
  field diff ticket=1353670649 field=symbol internal= broker=#BTCUSD [expected_ledger_shape_gap]
  field diff ticket=1353670649 field=magic internal=0 broker=84004 [expected_ledger_shape_gap]
Reconciliation complete — T1 ticket MATCHED; position left OPEN (not closed).
```

Exit code: **0** (T1 ticket matched). Posisi T1 **tidak ditutup**.

## Matched ticket

| Field | Value |
| --- | --- |
| T1 ticket | `1353670649` |
| Matched (by ticket) | ✅ ya — `matched == [1353670649]` |
| `missing_internal` | `[]` (broker tidak punya posisi yang tidak diketahui ledger) |
| `broker_live` | `True` (connector attach ke terminal bil2) |
| `has_critical()` | `True` |

## Raw report JSON (`docs/evidence/B-4-demo-validation.json` → `t2.raw_report`)

```json
{
  "matched": [1353670649],
  "missing_in_broker": [
    1348784058, 1348874223, 1348874358, 1348963010, 1348984819,
    1349697094, 1349909054, 1350068378, 1350246238, 1352094141,
    1352313902, 1352414292, 1352414491, 1352688152
  ],
  "missing_internal": [],
  "volume_mismatches": [
    {"ticket": 1353670649, "field": "volume", "internal": null, "broker": 0.01}
  ],
  "sltp_mismatches": [],
  "symbol_mismatches": [
    {"ticket": 1353670649, "field": "symbol", "internal": "", "broker": "#BTCUSD"}
  ],
  "magic_mismatches": [
    {"ticket": 1353670649, "field": "magic", "internal": 0, "broker": 84004}
  ],
  "matched_orders": [],
  "orphan_orders": [],
  "total_mismatches": 17,
  "critical": true
}
```

## Mismatch list — diklasifikasikan

| # | Kategori | Ticket | Klasifikasi | Alasan |
| --- | --- | --- | --- | --- |
| 1 | `volume_mismatches` | 1353670649 | **expected (data-shape gap)** | Record ledger hanya `{intent_id, state, ticket, timestamp}` — tanpa `volume`, jadi sisi internal `None` vs broker `0.01`. |
| 2 | `symbol_mismatches` | 1353670649 | **expected (data-shape gap)** | Ledger tidak menyimpan `symbol` → internal `""` vs broker `#BTCUSD`. |
| 3 | `magic_mismatches` | 1353670649 | **expected (data-shape gap)** | Ledger tidak menyimpan `magic` → internal `0` vs broker `84004` (B4_MAGIC). |
| 4–17 | `missing_in_broker` | 14 ticket lama | **expected (lifecycle artifact)** | 14 record `position_confirmed` dari 24–25 Sep masih tersimpan di ledger append-only; posisinya sudah ditutup di broker. Ledger tidak menulis state "closed", jadi record lama tetap dianggap posisi internal. |

**Tidak ada** mismatch yang terklasifikasi sebagai *real bug di T2*. Verifikasi 14
ticket lama: seluruhnya `position_confirmed` terakhir pada 24–25 Sep
(`b4_demo_validation` recon sebelumnya mencatat ticket-ticket ini sebagai order demo
lama), sedangkan broker saat ini hanya memegang 1 posisi (`1353670649`, magic `84004`,
comment `B4DEMO`) — dikonfirmasi independen via `mt5.positions_get()`.

## Verdict

- ✅ **T1 ticket `1353670649` MATCHED by ticket** — bukti inti T2 terpenuhi.
- ✅ **`missing_internal == []`** — broker tidak memegang posisi yang tidak ada di ledger
  (tidak ada posisi misterius / tidak ada order orphan).
- ⚠️ `has_critical() == True` — **bukan** karena T1 tidak match, melainkan karena
  (a) 3 field diff pada pasangan matched (data-shape gap ledger, *expected*), dan
  (b) 14 record lama `missing_in_broker` (lifecycle artifact append-only ledger, *expected*).
- **Implikasi gate:** `ReconciliationGuard` akan memblokir order BARU selama ledger
  masih memuat 14 record basi ini (`last_ok=False`). Ini adalah perilaku fail-closed
  yang benar — bukan sesuatu yang boleh "diakali" untuk lolos T2. Membersihkan record
  basi (menandai closed / pruning / lifecycle provider) **di luar scope T2**
  (dilarang: mengubah toleransi/provider/gate) dan dicatat sebagai temuan untuk B-4 T4
  atau task terpisah.
- Tidak ada kode reconciler/gate yang diubah untuk memaksa pass. `has_critical()`
  dilaporkan apa adanya.

## Acceptance checklist

- [x] Unit test GREEN (mock-based): `tests/test_b4_demo_validation.py` → **37 passed**
      (T1 29 + T2 8 baru).
- [x] Live `reconcile` terhadap bil2: T1 ticket `1353670649` **matched**, verdict dicatat,
      exit code **0**.
- [x] Evidence JSON `t2` section ditulis dengan `raw_report` + verdict
      (`result: "matched"`), plus evidence MD (`## T2 — Live reconciliation`).
- [x] Semua mismatch diklasifikasikan eksplisit (data-shape gap vs lifecycle artifact
      vs real bug); tidak ada perubahan kode reconciler/gate.
- [x] flake8 (`--max-line-length=100 --extend-ignore=E203,W503`) + black clean.
- [x] Full suite: **2230 passed** (baseline T1 2222 + 8 baru = 2230, tepat; tanpa regresi).

## Unit tests T2 (mock-based, tanpa broker)

`tests/test_b4_demo_validation.py`:

1. `test_reconcile_dispatches_to_cmd` — CLI `reconcile` memanggil `_cmd_reconcile`.
2. `test_reconcile_matched_ticket_passes` — ticket di kedua sisi → matched, exit 0.
3. `test_reconcile_missing_ticket_fails` — ticket absen di broker → **exit 3**,
   `missing_in_broker` memuat ticket.
4. `test_reconcile_volume_gap_is_reported_not_hidden` — volume gap muncul sebagai
   `field_differences` terklasifikasi `expected_ledger_shape_gap`; `has_critical()`
   tidak dipalsukan jadi False.
5. `test_reconcile_symbol_and_magic_gaps_classified_expected` — symbol/magic gap
   terklasifikasi expected.
6. `test_reconcile_no_t1_evidence_aborts` — tanpa evidence T1 → abort (exit 2).
7. `test_reconcile_attaches_connector` — connector di-attach (`use_live_data_mode`).
8. `test_reconcile_uses_durable_ledger` — sisi internal berasal dari ledger durable
   (`MT5ReconciliationProviders` asli + store yang di-rehidrasi).
9. `test_reconcile_writes_t2_evidence` — `t2` di-merge ke JSON, section MD ditambahkan,
   section `t1` tetap utuh.

Fixture autouse `isolate_order_ledger` diperluas untuk juga `reset_store()` +
`set_store(None)` sesudah tiap test, sehingga ticket dari satu test tidak bocor sebagai
phantom `missing_in_broker` di test lain.

## Files changed

- `scripts/b4_demo_validation.py` — tambah subcommand `reconcile` (`run_reconcile`,
  `_t1_ticket`, `_attach_connector`, `_build_providers`, `_build_runner`,
  `_classify_mismatch`, `_collect_report`, `_write_reconcile_evidence`,
  `_print_reconcile_summary`) + seam injeksi (`connector_module`, `providers_factory`,
  `runner_factory`).
- `services/python/tests/test_b4_demo_validation.py` — 8 test T2 + fixture isolation.
- `docs/evidence/B-4-demo-validation.json` — section `t2`.
- `docs/evidence/B-4-demo-validation.md` — section `## T2 — Live reconciliation`.
- `docs/tasks/B4-T2-report.md` — laporan ini.

Tidak ada file `src/**` yang diubah. Tidak ada commit.

## Verification commands

```
services/python/.venv/Scripts/python.exe -m pytest tests/test_b4_demo_validation.py -q
services/python/.venv/Scripts/python.exe -m flake8 --max-line-length=100 --extend-ignore=E203,W503 \
    scripts/b4_demo_validation.py services/python/tests/test_b4_demo_validation.py
services/python/.venv/Scripts/python.exe -m black --check \
    scripts/b4_demo_validation.py services/python/tests/test_b4_demo_validation.py
services/python/.venv/Scripts/python.exe scripts/b4_demo_validation.py reconcile
```
