# CERT-C1 — Research evidence wiring (Gate C) — Report

Tanggal: 2026-09-26/27 · Status: **SELESAI (wiring + run nyata + tests hijau + Gate C 5/5 via endpoint)**
Restart service: **TIDAK dilakukan** (tugas orchestrator). Verifikasi live memakai `TestClient` in-proc.

## 1. Akar masalah
Collector `_research_results_store()` di `services/python/src/live_readiness/certification_evidence.py`
hanya membaca `runtime.research_inbox` — atribut yang **tidak ada** di runtime. Akibatnya seluruh check
Gate C bernilai `None` (unknown) ⇒ Gate C 0/5. Padahal data nyata ada di
`services/python/research_state.jsonl` (store resmi `src/research/store.py`).

## 2. Perubahan

### a. `services/python/src/live_readiness/certification_evidence.py`
- **Sumber utama baru**: `_research_results_store(store_path=None)` sekarang membaca store resmi
  `ResearchStore` (`src/research/store.py`). Path default =
  `services/python/research_state.jsonl` (dihitung dari lokasi file: `Path(__file__).parents[2]`).
  Override path berprioritas: argumen `store_path` → env `RESEARCH_STATE_PATH` → default. **Tidak ada path hardcoded tanpa override.**
- **Normalisasi** `_normalize_store_records()` memetakan record store mentah ke bentuk yang dibaca collector
  (`_research_evidence`):
  - `backtest_result` → `{"status": "COMPLETED", "metrics_summary": {trades, total_trades, win_rate, ...,
    walk_forward}, "validation_evidence": {walk_forward, experiment_id}}`.
  - `validation_evidence` → `{"status", "metrics_summary": {trades}, "validation_evidence": {walk_forward,
    monte_carlo, sensitivity}}`.
  - Record malformed/unknown di-skip.
- **Fallback dipertahankan**: `runtime.research_inbox` masih dibaca (kompatibilitas) dan digabung.
  Bila tak ada satu pun sumber yang terbaca → `None` (semua check tetap unknown, tidak pernah dipalsukan).
- `import os` ditambahkan; `__all__` mengekspor `_normalize_store_records` + `_research_results_store`.
- **Tidak ada angka hardcoded** di collector (semua dari isi store; diverifikasi via grep).

### b. `scripts/run_research_validation.py` (baru, run NYATA)
Script CLI (bootstrap import ala `b4_demo_validation.py`) yang:
1. `mt5.initialize()` + set `connector` live mode; **menolak berjalan** bila tidak live (tidak simulasi random).
2. Fetch bar nyata `connector.get_ohlc(symbol, timeframe, count)` — default XAUUSD H1, mulai 3000 bar,
   eskalasi (kelipatan 2) sampai `total_trades >= 100` atau cap `--max-bars` (20000).
3. `ResearchEngine.run_backtest(experiment, closes, walk_forward=True, highs, lows)` → persist ke store
   via engine (bukan raw append) + `record_run_provenance`.
4. `MonteCarloRunner(n_sims=500, seed=42).run(...)` atas bar nyata + `classify_status(...)`.
5. `parameter_sensitivity(evaluate, baseline)` — evaluator sederhana yang **memanggil ulang engine
   `_simulate` + `compute_metrics`** pada bar yang sama per parameter yang diperturbasi (net PnL).
   Probe TIDAK dipersist (store bersih dari eksperimen buangan).
6. Menulis record `{"type": "validation_evidence", "data": {...}}` **via API store** (`store.append`).
7. Mencetak ringkasan angka nyata + exit code jujur (1 bila `total_trades < target`).

## 3. Perintah run
```bash
# dari repo root, di luar service (MT5 tersedia di venv python service)
cd C:/xampp/htdocs/project-ea-bot
services/python/.venv/Scripts/python.exe scripts/run_research_validation.py
```
Output ringkas:
```
[run_research_validation] MT5 live mode aktif.
[run_research_validation] store: ...\services\python\research_state.jsonl (persisted=True)
[run_research_validation] backtest bars=3000 trades=362 wr=32.04% pnl=392.67
[run_research_validation] Monte Carlo: 500 sims over 362 trade PnLs
[run_research_validation] MC status=FRAGILE median_return=58707.0550 p5=-694.0062 worst_dd=856053.5900
[run_research_validation] sensitivity cliff_edge=True worst_drop_pct=47.14
[run_research_validation] validation_evidence record ditulis ke store.
```
Exit code 0.

## 4. Angka NYATA (bukan hardcoded)

| Metrik | Nilai | Sumber |
|---|---|---|
| Symbol / timeframe | XAUUSD H1 | MT5 account 49662626 `HFMarketsGlobal-Demo` (IDR) |
| Bars | 3000 | `connector.get_ohlc` (first 2025-11-20 → last 2026-09-26) |
| `total_trades` | **362** | `BacktestResult.total_trades` (≥ 100 ⇒ `sufficient_sample`) |
| Win rate | **32.04 %** | `BacktestResult.win_rate` |
| Profit factor | 1.0885 | `BacktestResult.profit_factor` |
| Net PnL | **392.67** | `BacktestResult.net_pnl` |
| Walk-forward | enabled=True | `run_backtest(walk_forward=True)` |
| Monte Carlo status | **FRAGILE** | `classify_status` (500 sims) |
| MC median return | 58707.055 | `MonteCarloResult.median_return` |
| MC 5th pct return | −694.006 | `MonteCarloResult.perc5_return` |
| MC worst drawdown | 856053.59 | `MonteCarloResult.worst_drawdown` |
| MC max loss streak | 31 | `MonteCarloResult.max_loss_streak` |
| MC P(severe DD) | 1.0 | `probability_severe_drawdown` (>20% DD) |
| Sensitivity cliff edge | **True** | `ParameterSensitivity.cliff_edge` |
| Sensitivity worst drop | 47.14 % | `ParameterSensitivity.worst_drop_pct` (baseline net PnL 392.67) |

**Catatan jujur**: Strategi ini **TIDAK** robust. Monte Carlo mengklasifikasikan **FRAGILE** (median return
positif besar, tapi 5th-percentile return negatif dan P(severe drawdown)=1.0), dan parameter sensitivity
mendeteksi **cliff edge** (worst drop 47.14 % > 40 %). Ini fakta dari run nyata — tidak ada angka yang
diperhalus. Gate C tetap **5/5** karena check Gate C hanya menuntut *keberadaan bukti* (backtest,
walk-forward, monte-carlo, sensitivity, sampel cukup), **bukan** klasifikasi ROBUST. Semantik gate tidak diubah.

## 5. Bukti store
Store: `services/python/research_state.jsonl` (74 baris). Distribusi tipe:
```
experiment: 25 · backtest_result: 21 · run_provenance: 21 · strategy_version: 5 · hypothesis: 1 · validation_evidence: 1
```
Record `validation_evidence` terakhir:
```json
{
  "type": "validation_evidence",
  "data": {
    "experiment_id": "6479b62a-eaa9-4768-9eb9-85be79abb459",
    "status": "COMPLETED",
    "metrics_summary": {"trades": 362, "win_rate": 32.044, "profit_factor": 1.0885, "net_pnl": 392.67},
    "validation_evidence": {
      "walk_forward": true,
      "monte_carlo": {"status": "FRAGILE", "median_return": 58707.055, "5th_percentile_return": -694.006,
                      "worst_drawdown": 856053.59, "max_loss_streak": 31, "probability_severe_drawdown": 1.0,
                      "n_sims": 500, "trades_resampled": 362},
      "sensitivity": {"cliff_edge": true, "worst_drop_pct": 47.14, "baseline_metric": 392.67}
    },
    "provenance": {"symbol": "XAUUSD", "timeframe": "H1", "bars": 3000, "source": "live",
                   "ran_at": "2026-09-26T17:03:02+00:00", "script": "run_research_validation.py"}
  }
}
```
Catatan: `research_state.jsonl` adalah artefak runtime (gitignored). Sebelum wiring, store berisi 68 baris
(20 `backtest_result` + 20 `run_provenance` + 23 `experiment` + 4 `strategy_version` + 1 `hypothesis`).
Run nyata menambah 6 baris (1 eksperimen validasi + 1 backtest + 1 provenance + 1 strategy_version + 2
append `experiment` dari engine). **Tidak ada** eksperimen probe buangan (0 record `probe-`).

## 6. Bukti Gate C 5/5 (via endpoint, tanpa restart)
`GET /v2/certification/gate` melalui `TestClient` in-proc:
```
Gate C passed: True
  backtest               True   | 22 backtest selesai
  walk_forward           True   | 22 hasil walk-forward
  monte_carlo            True   | 1 hasil Monte Carlo
  parameter_sensitivity  True   | 1 hasil sensitivitas
  sufficient_sample      True   | sampel maksimum 362 trade
```

## 7. Tests (RED → GREEN)
Ditambahkan ke `tests/test_certification_evidence.py`:
- `test_normalize_backtest_result_record`, `test_normalize_backtest_result_without_walk_forward`
- `test_normalize_validation_evidence_record`, `test_normalize_skips_malformed_and_unknown_records`
- `test_store_read_uses_research_state_path` (env override), `test_store_read_uses_explicit_path`
- `test_store_read_absent_path_is_observable_empty`
- `test_gate_c_all_five_pass_from_real_store` (fixture tmp path → 5/5)
- `test_collector_reads_real_store_no_hardcoded_numbers` (membuktikan angka mengikuti isi store)

**RED terbukti**: reader lama (inbox-only) mengembalikan `None` di proses test → semua check Gate C unknown.
Setelah fix, seluruh test GREEN. Target: `25 passed`.

Full suite: **2309 passed** (0 gagal). Lint bersih:
`black --check` + `flake8 --max-line-length=100 --extend-ignore=E203,W503` → bersih.

## 8. Guardrails dipatuhi
- Tidak ada commit / `git add` / `git stash`.
- Tidak menjalankan `restart-py.ps1` / `restart-all.ps1` / daemon apa pun.
- Hanya 3 berkas diubah: `certification_evidence.py`, `test_certification_evidence.py`, `scripts/run_research_validation.py`.
- Tidak menyentuh `config.py`, `main.py`, `index.ts`, `CHANGELOG.md`, `docs/audit/*`, `docs/hermes_multibot/*`.
- Gate check names/semantik tidak diubah — hanya wiring data.
- Demo/paper only; tidak ada secret yang dicetak.

## 9. Kegagalan jujur
1. **Strategi FRAGILE / cliff-edge** (lihat §4): meski Gate C 5/5, hasil robust-nya NEGATIF. Ini bukan
   bug wiring — wiring melaporkan apa adanya.
2. **temp_pytest cleanup**: full-suite sekali gagal dengan 2 error `FileExistsError` pada direktori
   `temp_pytest` (Windows tak bisa hapus direktori non-kosong saat basetemp dibuat ulang). Setelah
   `rm -rf temp_pytest`, suite hijau total (2309 passed). Ini isu lingkungan test, bukan regresi kode.
3. **Monte Carlo MC dipanggil dengan `Bar` sintetis** dari closes/highs/lows nyata (timestamp jam monotonik)
   karena `MonteCarloRunner` butuh `backtest_v2.Bar`; harga & range tetap nyata dari MT5, hanya sumbu waktu
   tidak disimpan. Sinyal EMA & resampling PnL memakai data transaksi nyata (362 trade).

## 10. File tersentuh
- `M services/python/src/live_readiness/certification_evidence.py`
- `M services/python/tests/test_certification_evidence.py`
- `?? scripts/run_research_validation.py`
- `?? docs/tasks/CERT-C1-report.md` (dokumen ini)
