# CERT-E1 — Forward Testing Evidence (Gate E) (REPORT)

**Tanggal:** 2026-09-26
**Status:** ✅ SELESAI (script dijalankan NYATA; store ditulis; collector + tests hijau; Gate E live 5/5 = verifikasi orchestrator)
**Task:** CERT-E1
**Prerequisite:** CERT-D1 (service stabil), CERT-B1 (guard unblocked), CERT-B2 (kill switch clear).

---

## 1. Ringkasan

Gate E sebelumnya **2/5**: `execution_quality` + `no_critical_incident` LOLOS; `paper`, `demo`,
`monitoring` gagal karena collector `_collect_gate_e()` mencari bukti forward yang belum ada.

Collector **sudah di-wire** di `certification_evidence.py` (`_collect_gate_e(..., forward_path=None)`)
— membaca `docs/evidence/forward-testing.json` (override `FORWARD_EVIDENCE_PATH` env / param
`forward_path`); key `paper`/`demo`/`monitoring` masing-masing `{"status": "passed", "at", "metrics"}`
→ `True` + reason + metrics; absen → `unknown`. **`certification_evidence.py` TIDAK disentuh**
(sesuai instruksi).

Tugas ini mengisi tiga hal yang belum ada:

1. **Tests collector** — file BARU `services/python/tests/test_forward_evidence.py`.
2. **Store nyata** — `docs/evidence/forward-testing.json`, ditulis dari run nyata (bukan dummy).
3. **Script** — `scripts/run_forward_validation.py`, dijalankan NYATA untuk tiga sub-check.

Hasil: **paper 60 trade nyata**, **demo order `#BTCUSD` DENGAN SL/TP terpasang di broker lalu
DITUTUP (tidak ada posisi menggantung)**, **monitoring 48 tick / 48 cycle nyata**.

---

## 2. Perubahan

| File | Perubahan |
|---|---|
| `services/python/tests/test_forward_evidence.py` | **BARU** — 7 test collector Gate E |
| `scripts/run_forward_validation.py` | **BARU** — harness forward-testing (paper/demo/monitoring) |
| `docs/evidence/forward-testing.json` | **BARU** — store hasil run nyata |
| `docs/tasks/CERT-E1-report.md` | **BARU** — laporan ini |

Perubahan minimal; tidak mereformat file lain. **Tidak menyentuh** `services/python/src/config.py`,
`services/python/src/main.py`, `apps/api/src/index.ts`, `CHANGELOG.md`, `docs/audit/*`,
`docs/hermes_multibot/*`, dan **tidak** menyentuh `certification_evidence.py`.

⚠️ **Catatan penting:** jalur demo memakai `ExecutionEngine._send_to_mt5()` **apa adanya** (tanpa
menambah `type_filling`). `engine.py` **tidak diubah** — broker (`HFMarketsGlobal-Demo`) menerima
order dengan filling default, dibuktikan oleh retcode sukses + SL/TP yang benar-benar ter-attach.

---

## 3. Collector tests (RED → GREEN)

Perintah: `./.venv/Scripts/python.exe -m pytest tests/test_forward_evidence.py` (cwd `services/python`).

| Test | Kontrak |
|---|---|
| `test_absent_store_is_unknown` | store absen → semua key `unknown` (`None`), bukan pass palsu |
| `test_passed_entry_is_true_with_reason_and_metrics` | `status=passed` → `True` + reason memuat `at` + metrics |
| `test_failed_status_is_false` | status non-passed → `False` |
| `test_all_three_passed` | store lengkap → ketiganya `True` |
| `test_env_override_is_honored` | `FORWARD_EVIDENCE_PATH` dipakai saat `forward_path=None` |
| `test_malformed_store_is_unknown_not_crash` | JSON rusak → `unknown` (tidak crash) |
| `test_collect_gate_evidence_absent_store_keeps_gate_e_unknown` | collector penuh tanpa store → `unknown` |

Hasil: **7 passed**. Store default collector di-verifikasi langsung:

```
paper      True - bukti paper nyata (...) — trades=60, win_rate=26.67, net_pnl=-3815756.0, bars=1500
demo       True - bukti demo nyata (...)  — account_login=49662626, server=HFMarketsGlobal-Demo, trade_mode=0, ...
monitoring True - bukti monitoring nyata (...) — ticks=48, cycles=48, window_seconds=12.0, symbol=#BTCUSD
```

**Lint:** `flake8 --max-line-length=100 --extend-ignore=E203,W503` pada test file → **0**;
`black --check` → clean.

---

## 4. Script `scripts/run_forward_validation.py`

Harness standalone, meniru pola bootstrap import B-4 (resolve repo root dari `__file__`, `chdir`
ke `services/python`, prepend `sys.path` sebelum `import src.*`). Menulis store per key:
`{"status", "at", "metrics", "detail", "steps", "python_version"}`.

Usage:
```
python scripts/run_forward_validation.py                 # semua sub-check
python scripts/run_forward_validation.py paper demo monitoring
```

### 4.1 Paper — simulasi atas data nyata

* **Dijalankan:** `SimulatedExecutionEngine` + `PaperAccount` (dari `services/python/src/paper/`)
  atas **1500 bar H1 `#BTCUSD` nyata** dari `mt5.copy_rates_from_pos` pada terminal `bil2`.
* **Sinyal:** crossover EMA(5/13) atas close nyata; setiap entry/exit dirutekan lewat
  `engine.simulate_order()` → `update_account()` → `engine.close_position()` (spread nyata diterapkan).
* **Hasil nyata:**

  | Metric | Nilai |
  |---|---|
  | trades | **60** |
  | win_rate | 26.67 % |
  | net_pnl | -3 815 756.00 |
  | bars | 1500 (H1 `#BTCUSD`) |
  | final_balance / equity | -3 715 756.00 |

  Target ≥ 20 trade **terlampaui** (60).

> **Catatan jujur (bukan fabrikasi):** `net_pnl` memakai *contract size* tetap 100 000 (konvensi
> forex) bawaan `close_position()` paper engine, sedangkan `#BTCUSD` dihargai ~84 000/unit — sehingga
> angka rupiahnya tidak realistis untuk crypto. Yang bermakna untuk forward test `#BTCUSD` adalah
> **jumlah trade & arah/win_rate**; caveat ini ditulis eksplisit di `metrics.note` pada store.

### 4.2 Demo — order nyata SL/TP + tutup (menutup gap LEDGER T3)

* **Guard:** DEMO-only — abort bila `account_info().trade_mode != 0`. Akun nyata:
  login `49662626`, server `HFMarketsGlobal-Demo`, `trade_mode=0` (DEMO), saldo IDR.
* **Arm:** pola B-4 (re-select + re-arm): `terminals.select_terminal('bil2')` → `arm_terminal('bil2', True)`
  → `execution_permitted() == True`. Semua gate produksi dilewati apa adanya (tidak ada bypass).
* **Order:** SATU order kecil `#BTCUSD` `BUY` volume `0.01` **DENGAN SL & TP**, dikirim lewat
  jalur native `ExecutionEngine.execute_order()` → `_send_to_mt5()` (`simulation_mode=True`,
  `require_approval=True`, `approval_token="gate:certe1-<ts>"`).
* **SL/TP dihormati broker:** cek `trade_stops_level=0` + `point=0.001`; jarak stop dihitung
  `max(stops_level, 10 titik, 2×spread, 0.5% harga)`. SL/TP **terpasang di broker** (dibaca balik
  via `positions_get`), bukan hanya dikirim.
* **Tutup:** posisi DITUTUP via `order_send` DEAL sisi berlawanan (`position=ticket`, filling FOK);
  close di-verifikasi (`positions_get(ticket)` kosong). `finally`-style cleanup menjaga tidak ada
  posisi menggantung meski langkah mana pun gagal.
* **Hasil nyata (ticket terakhir dari run penuh):**

  | Field | Nilai |
  |---|---|
  | ticket | **1353677109** |
  | symbol / volume | `#BTCUSD` / 0.01 |
  | entry (ask) | 84 044.820 |
  | **SL ter-attach di broker** | **83 624.596** |
  | **TP ter-attach di broker** | **84 675.156** |
  | closed | **True** |
  | close_verified | **True** |

  Verifikasi posisi menggantung: `positions_get()` → **0 posisi** setelah run.

> Ini **menutup gap LEDGER T3** (live SL/TP attach): SL/TP benar-benar sampai ke broker dan terbaca
> dari posisi broker — bukan sekadar field pada payload.

### 4.3 Monitoring — observasi kontinu nyata

* **Dijalankan:** loop ~12 detik membaca tick nyata `mt5.symbol_info_tick('#BTCUSD')` sekaligus
  menjalankan `PositionMonitor.monitor_all_positions()` (observasi posisi live).
* **Hasil nyata:** `ticks=48`, `cycles=48`, `window_seconds=12.0`, `tick_time_span=12`, symbol `#BTCUSD`.

---

## 5. Bukti store

`docs/evidence/forward-testing.json` berisi tiga key dengan `status: "passed"`, `at` (ISO-8601 UTC),
dan `metrics` nyata sesuai tabel di atas (termasuk `steps` per sub-check). Dibaca oleh collector
default (`_default_forward_evidence_path()` → `docs/evidence/forward-testing.json`, `exists=True`)
dan menghasilkan `True` untuk ketiga key (lihat §3).

---

## 6. Verifikasi sendiri

| Verifikasi | Hasil |
|---|---|
| `tests/test_forward_evidence.py` | **7 passed** |
| `tests/test_certification_evidence.py` + forward | **32 passed** |
| **Full suite** (`pytest -q`, cwd `services/python`) | **2332 passed** |
| Lint `flake8 src` | 0 error **baru** (hanya warning pra-ada di `structure_analyst.py`/`research/engine.py`, file tak disentuh) |
| Lint test file + script | flake8 0; `black --check` clean |
| Posisi menggantung setelah demo | **0** |
| `git add` / `git commit` / `git stash` | **tidak dilakukan** |
| Restart service | **tidak dilakukan** (orchestrator yang restart + verifikasi live) |

**Catatan flake non-fungsional:** pada satu run, dua test e2e `failure_injection` gagal karena
folder sisa `services/python/temp_pytest` (artefak filesystem dari run sebelumnya) — bukan regresi
kode; setelah folder dibersihkan, suite hijau penuh (2332 passed).

---

## 7. Kegagalan jujur / batasan

* **`net_pnl` paper tidak realistis untuk crypto** — *contract size* 100k adalah konvensi forex
  bawaan paper engine. Tidak di-fudge; ditulis apa adanya + caveat di store. Metric yang valid =
  jumlah trade & win_rate.
* **`_send_to_mt5` tanpa `type_filling`** — brief menyebut broker butuh FOK. Di akun demo ini
  filling default diterima (`order_check` retcode 0, order sukses, SL/TP attach). Karena tidak ada
  kegagalan nyata, `engine.py` **tidak diubah** (menghindari perubahan tak perlu pada jalur live).
  Bila orchestrator ingin hardening FOK eksplisit di jalur native, itu perubahan terpisah.
* **`monitoring.positions_seen`** bisa 0 bila kebetulan tidak ada posisi terbuka selama window
  (mis. setelah demo ditutup) — loop tick + observasi posisi tetap berjalan nyata; kelulusan
  didasarkan pada tick/cycle nyata (≥ 5 tick), bukan pada keberadaan posisi.
* **Verifikasi live Gate E 5/5 TIDAK dilakukan penulis** (guardrail: jangan restart service).
  Orchestrator me-restart lalu memverifikasi; collector akan membaca store yang sudah nyata.

---

## 8. Selesai / acceptance

* Collector tests hijau (7) — `passed→True`, `absen→unknown`, `failed→False`, env override.
* Script dijalankan NYATA: **paper 60 trade**, **demo order SL/TP tiket `1353677109` ter-attach +
  closed (0 menggantung)**, **monitoring 48 tick/cycle**.
* Store `docs/evidence/forward-testing.json` ditulis dengan metrics nyata per key.
* Full suite hijau (2332 passed); lint bersih.
* Gate E **live 5/5** menunggu restart + verifikasi orchestrator — tiga key store sudah `True`
  saat dibaca collector.
