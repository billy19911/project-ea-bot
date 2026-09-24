# Task: Signal Lifecycle Telegram (edit-in-place) + Risk-% Sizing + One-Entry Policy

Repo: C:/xampp/htdocs/project-ea-bot. Python service: services/python (venv: ./.venv/Scripts/python.exe).
Edit files only; DO NOT restart services; DO NOT touch .env.runtime; DO NOT commit.

## Background (kenapa)

Saat ini tiap siklus yang menghasilkan keputusan BUY/SELL (walau REJECTED oleh risk gate) langsung
mengirim pesan Telegram BARU setiap ~1-3 menit (screenshot user: 7 pesan hampir identik). User minta:

1. HANYA satu pesan per sinyal (hasil final analisis), berisi Entry/SL/TP1/TP2/TPmax yang rapi.
   Saat TP1/TP2/TPmax/SL terhit, tandai di pesan YANG SAMA (editMessageText) — bukan pesan baru.
   Sinyal yang ditolak risk gate TIDAK dikirim (silent; tetap tercatat di /decisions).
2. Lot size ditentukan dari % balance yang bisa diatur (knob UI), bukan lot asal dari synthesizer.
3. Kebijakan satu entry: saat sudah ada posisi bot terbuka (magic sendiri), entry baru diblok.
   Setelah posisi close → review (why TP/SL) sudah ada; hasil review di-append ke pesan sinyal.

## Aturan umum

- Fail-safe: SEMUA jalur baru tidak boleh melempar exception ke loop otonom (swallow + log).
- Modul `src/telegram/*` DILARANG import MT5/execution (ada guard test). Data harga/posisi
  disuntik dari luar (runtime/main).
- Line length 100, black, isort profile black, flake8 --max-line-length=100 --extend-ignore=E203,W503.
- Jangan mengubah `risk/gate.py`, `risk/engine.py`, `execution/engine.py`.
- Jangan mengubah test lama kecuali BENAR-BENAR perlu (jelaskan di laporan akhir). Test lama harus tetap lulus.

---

## 1. Transport: edit + message_id

File `services/python/src/telegram/transport.py`:

- `send_message(chat_id, text) -> Optional[int]`: setelah sukses, coba baca `response.json()["result"]["message_id"]`;
  kembalikan int itu; jika tidak ada → `None`. Tetap raise `TelegramTransportError` (sanitized, tanpa token) saat gagal.
- Tambah `edit_message_text(chat_id, message_id, text) -> bool`:
  - POST `{_API_BASE}/bot{token}/editMessageText` json `{"chat_id": str(chat_id), "message_id": int(message_id), "text": text}`.
  - Jika HTTP 400 dan body mengandung "message is not modified" → return True (idempotent, bukan error).
  - Gagal lain → raise `TelegramTransportError` sanitized (pola sama dengan send_message).
- Tetap tanpa import execution/mt5 (guard test `test_transport_module_does_not_import_execution_or_mt5`).

## 2. Gateway: kirim & edit terkontrol

File `services/python/src/telegram/gateway.py` (JANGAN ubah perilaku `notify`/`handle_message` yang ada):

- Tambah `send_tracked(self, text: str, chat_id: Any = None) -> dict[str, Optional[int]]`:
  - Target = `[chat_id]` bila diberikan, else `sorted(self.allowlist)`.
  - Untuk tiap target: panggil `self.transport.send_message(target, text)` (jika transport tidak ada → {}),
    simpan `{str(target): message_id_or_None}`. Exception per-target di-swallow (log). Never raises.
- Tambah `edit_tracked(self, message_ids: dict, text: str) -> bool`:
  - Untuk tiap `(chat_id, message_id)` dengan message_id tidak None: panggil `transport.edit_message_text`.
  - Jika transport tidak punya `edit_message_text` → return False (jangan raise).
  - Return True bila minimal satu edit terkirim. Exception di-swallow. Never raises.

## 3. Modul baru: `services/python/src/telegram/signal_lifecycle.py`

Pure formatting + state machine. DILARANG import mt5/execution. Gunakan pola singleton shared-slot
(seperti `notifier.py`: simpan di `builtins` slot agar identitas import `telegram.*` dan `src.telegram.*` berbagi satu objek).

Isi minimal:

```python
@dataclass
class SignalState:
    symbol: str
    direction: str            # BUY / SELL
    entry: float; sl: float; tp1: float; tp2: float; tpmax: float
    confidence: float
    consensus: str            # mis. "100%"
    created_at: float
    status: str               # MENUNGGU EKSEKUSI | ENTRY TERBUKA | GAGAL EKSEKUSI | SELESAI
    status_detail: str        # ticket / alasan gagal
    hits: dict[str, bool]     # {"tp1": False, "tp2": False, "tpmax": False, "sl": False}
    hit_times: dict[str, str] # waktu hit (HH:MM)
    review_text: str
    message_ids: dict[str, Optional[int]]
```

Fungsi/kelas:

- `render_signal_message(state) -> str` — PURE, unit-testable. Format RAPI (plain text, tanpa parse_mode):

```
🎯 SIGNAL FINAL · XAUUSD SELL
🕒 22:47 · konsensus 100% · conf 0.86

📐 RENCANA
Entry : 4284.97
SL    : 4294.65
TP1   : 4275.29
TP2   : 4265.62
TPmax : 4255.94

📌 Status: ENTRY TERBUKA #12345678
   ⏳ TP1
   ✅ TP2 — HIT 22:58
   ⏳ TPmax
   ⏳ SL
```

  - Level yang hit → `✅`/`❌` (SL pakai ❌) + `— HIT HH:MM`.
  - Bila `status == "SELESAI"` tambahkan baris `🏁 SELESAI: <detail>` dan bila ada
    `review_text` tambahkan `📝 Review: <review_text>`.
  - Bila entry/sl tidak tersedia (levels None) → tetap kirim, tanpa blok RENCANA.

- `class SignalLifecycleTracker`:
  - `__init__(self, gateway_provider=None, clock=None)` — `gateway_provider` default memanggil
    `get_report_gateway()` dari notifier (lazy import di dalam method untuk hindari siklus import).
  - `observe_cycle_result(self, record: dict) -> bool` (dipanggil per siklus selesai):
    - `decision = str(record.get("decision") or "").upper()`.
    - Bila decision BUKAN BUY/SELL → return False (biar caller meneruskan ke digest lama).
    - Bila `record.get("risk_approved")` falsy → return True TANPA kirim apa pun (rejected = silent).
    - Bila symbol kosong → return False.
    - Levels dari `record.get("levels")` (dict: entry/sl/tp1/tp2/tpmax/direction). Bila entry/sl
      tidak ada → tetap lanjut (message tanpa RENCANA).
    - State aktif per symbol:
      - Belum ada → SEND pesan via `gateway.send_tracked(text)`, simpan state + message_ids.
        Status: `ENTRY TERBUKA #<ticket>` bila `record.get("executed")` dan ada ticket dari
        `execution_result.ticket`; `GAGAL EKSEKUSI: <error>` bila `status == "ERROR"`; selain itu
        `MENUNGGU EKSEKUSI` (+ detail bila ada `error`).
      - Ada, arah SAMA → jangan kirim pesan baru. Edit HANYA bila status/status_detail berubah
        (mis. MENUNGGU → ENTRY TERBUKA). Confidence baru lebih tinggi boleh update state (tanpa edit).
      - Ada, arah BERBEDA → bila state lama sudah `ENTRY TERBUKA` → ignore sinyal baru (log).
        Bila belum → ganti state (edit pesan yang sama: arah + RENCANA + reset hits).
    - Semua operasi dalam try/except (return False saat error tak terduga, jangan raise).
  - `observe_price(self, symbol: str, price: float, ts: float | None = None) -> bool`:
    - Tidak ada state aktif untuk symbol → False.
    - Arah BUY: hit tp bila `price >= level`; arah SELL: hit bila `price <= level` (tp1/tp2/tpmax).
      SL: BUY `price <= sl`; SELL `price >= sl`.
    - Hanya saat ada perubahan hits → edit pesan (via message_ids). Return True bila mengedit.
  - `on_review(self, record: dict) -> bool`: cari state via `record["trade_id"]`/`ticket` (string bandingkan)
    atau bila hanya satu state aktif → symbol-nya. Isi `review_text = f"{outcome} · {root_cause} · {summary}"`
    (potong 200 char), `status="SELESAI"`, `status_detail` dari outcome/pnl, edit pesan, lalu HAPUS state
    dari aktif (sinyal berikutnya boleh kirim pesan baru). Return bool. Never raises.
  - `active_symbols(self) -> list[str]`.
- `reset_signal_lifecycle()` untuk test; `get_signal_lifecycle()` singleton.

- Export dari `services/python/src/telegram/__init__.py`: `get_signal_lifecycle`, `reset_signal_lifecycle`.

## 4. Runtime wiring

File `services/python/src/orchestration/runtime.py`:

- `_notify_cycle_result(result)`: ganti isinya →
  1. payload = result.to_dict()
  2. coba `observe_cycle_result(payload)` (import ganda pola try/except ImportError); bila return True → selesai.
  3. bila False → `queue_pipeline_result(payload)` seperti sekarang.
  - Semua dibungkus try/except existing (Telegram tidak boleh memutus loop).
- Tambah helper `_observe_signal_prices(self)` (fail-safe): untuk tiap symbol di
  `get_signal_lifecycle().active_symbols()`, baca snapshot `trading.market_snapshot.get_latest_snapshot(symbol)`
  → `snapshot["volatility"]["price"]` (>0) → `observe_price(symbol, price)`. Panggil dari
  `_monitor_positions()` (setelah monitor posisi) DAN di akhir `run_cycle()` (setelah `_monitor_positions()`),
  cukup sekali per pemanggilan `_monitor_positions` (jangan dobel di run_cycle bila sudah dipanggil via monitor).
- `_build_pipeline`: baca env `ONE_ENTRY_POLICY` (default "true") → pass `single_entry_policy=<bool>`
  ke TradingPipeline; env `ENTRY_MAGIC` (default 70000) → pass `entry_magic=<int>`.

File `services/python/src/main.py`:

- `set_auto_trigger(...)` (baris ~104): ganti `on_review` menjadi fungsi kecil `_on_review(record)` yang:
  1. `record_review_lesson(get_lesson_store(), record)` (existing), lalu
  2. fail-safe panggil `get_signal_lifecycle().on_review(record.to_dict() if hasattr(record,"to_dict") else record)`.
- Lifespan startup: buat task `_signal_price_watch()` (fail-safe, dibatalkan saat shutdown):
  loop `await asyncio.sleep(15)`; untuk tiap symbol aktif → `connector.get_tick(symbol)`;
  price = bid bila >0 else ask; `observe_price(symbol, price)`. Import connector yang sudah ada pola di main.py.
  Bungkus seluruh body per-iterasi dengan try/except (log debug/warning).
  Batalkan task di shutdown (pola sama seperti feed_task).

## 5. Risk-% sizing + cap lot (knob UI)

File `services/python/src/system/settings_store.py` — tambah 2 KNOBS (deskripsi Indonesia, applied_to jelas):

```python
Knob(key="risk_per_trade_pct", kind="float", minimum=0.1, maximum=5.0, default=1.0,
     description="Risiko per entry (% dari equity/balance). Lot dihitung dari jarak SL.",
     applied_to="TradingPipeline.default_risk_pct")
Knob(key="max_lot_per_trade", kind="float", minimum=0.01, maximum=10.0, default=1.0,
     description="Batas maksimum lot per entry (cap keamanan).",
     applied_to="TradingPipeline.max_lot_per_trade")
```

File `services/python/src/system/endpoints.py`:
- `SettingsPatch` tambah field `risk_per_trade_pct: float | None = None` dan `max_lot_per_trade: float | None = None`.
- `_apply_to_runtime`: push keduanya ke `runtime.pipeline.default_risk_pct` / `runtime.pipeline.max_lot_per_trade`
  (set hanya bila attribute ada; konversi float). Masukkan ke dict `applied` seperti knob lain.

File `services/python/src/orchestration/pipeline.py`:
- `__init__` tambah param: `default_risk_pct: float = DEFAULT_RISK_PCT`,
  `max_lot_per_trade: float = 1.0`, `force_risk_sizing: bool = False`,
  `single_entry_policy: bool = False`, `entry_magic: int = 70000`. Simpan sebagai attribute.
- `_complete_proposal`:
  - Ganti `DEFAULT_RISK_PCT` → `self.default_risk_pct` (fallback ke DEFAULT bila <=0).
  - Resolusi point/contract: `market_info.get("point_value")` / `market_info.get("contract_size")`;
    bila salah satu kosong → coba `market.symbol_spec.get_symbol_spec(proposal.get("symbol"))`
    (import lokal try/except; ambil `point` & `contract_size`; default lama bila gagal).
  - Hitung `sl_pips = abs(entry-sl)/point` (point>0).
  - Setelah `lot` dihitung: `lot = self.money_manager.cap_lot_size(lot, max_lot_per_trade=self.max_lot_per_trade)`.
  - Bila `self.force_risk_sizing` dan sl>0 dan equity>0: hitung lot dari risk % MESKI proposal
    sudah punya size (override) — tetapi JANGAN override bila hasil <= 0 atau error (fallback ke nilai lama).
    Catat `proposal["risk_pct"] = risk_pct` dan `proposal["size"] = round(lot, 2)`.
  - Penting: perilaku default (`force_risk_sizing=False`) HARUS sama seperti sekarang
    (test `test_completion_never_overrides_provided_values` harus tetap lulus).
- Guard satu-entry (setelah semua guard dependency/reconciliation, sebelum `_build_order_request`):
  ```python
  if self.single_entry_policy and self._has_own_position(validation["current_positions"]):
      result.status = STATUS_BLOCKED
      result.risk_reason = f"kebijakan satu entry: posisi #{ticket} masih terbuka"
      result.add_stage("single_entry", STAGE_BLOCKED, result.risk_reason)
      result.add_stage("execution", STAGE_SKIPPED, "single entry policy")
      self._finalise(result); return result
  ```
  `_has_own_position(positions)`: iterasi list; baca `magic` dari dict ATAU object (getattr);
  return True bila ada `int(magic) == self.entry_magic`. Fail-safe (error → False).
- `PipelineResult`: tambah field `agent_results: dict = {}` dan `supervisor_summary: str = ""`;
  sertakan di `to_dict()`; isi di `run()` dari `analysis` (setelah `result.add_stage("supervisor", ...)`):
  `result.agent_results = analysis.get("agent_results") if isinstance(analysis.get("agent_results"), dict) else {}`
  dan `result.supervisor_summary = str(analysis.get("summary") or "")`.

File `services/python/src/mt5/schemas.py`: `class Position` tambah `magic: Optional[int] = None`
(taruh setelah field `margin` agar aman; field opsional additive).

File `services/python/src/mt5/connector.py`: di `get_positions()` jalur live, isi `magic=int(getattr(p, "magic", 0) or 0) or None`;
jalur simulasi → `magic=None` untuk kedua sample position.

## 6. Tests (WAJIB)

File baru `services/python/tests/test_signal_lifecycle.py`:
- Fake transport (send_message → incrementing ids, edit_message_text mencatat; tanpa jaringan).
  Set gateway via `set_gateway(TelegramGateway(transport=..., allowlist=["1"]))`, `set_signal_gateway(None)`, `reset_signal_lifecycle()`.
- Kasus: (a) siklus BUY/SELL approved+executed → tepat 1 pesan, berisi "SIGNAL FINAL" & ticket;
  (b) siklus berikutnya arah sama → TIDAK ada pesan baru (len(sent)==1);
  (c) siklus REJECTED (risk_approved False) → tidak ada pesan; return True (consumed);
  (d) observe_price menyentuh TP1 → 1 edit berisi "✅"; observe_price sama lagi → tidak ada edit tambahan;
  (e) SL hit → edit berisi "❌"; (f) on_review → edit "📝 Review" & "SELESAI", state aktif dibersihkan
  (sinyal baru berikutnya → pesan baru); (g) transport rusak → return False/True tanpa raise;
  (h) `render_signal_message` pure: arah BUY/SELL, hit markers, level None.
- Guard import: assert modul `src.telegram.signal_lifecycle` tidak meng-import mt5/execution (ast, pola seperti test transport).

File baru `services/python/tests/test_risk_sizing.py`:
- Force sizing: pipeline `force_risk_sizing=True`, equity 10_000, risk 1%, SL distance 10, point 0.01,
  contract 100 → lot == 0.1 (cap 1.0); dengan `max_lot_per_trade=0.05` → lot == 0.05.
- Default mode: proposal punya size 0.42 → tetap 0.42 (tidak override).
- Single entry: pipeline `single_entry_policy=True`, context current_positions=[{"magic":70000,...}]
  → status BLOCKED, reason mengandung "satu entry", execution engine TIDAK dipanggil.
- Settings: knob baru ada di KNOBS & `_apply_to_runtime({"risk_per_trade_pct": 2.0})` mengubah
  `runtime.pipeline.default_risk_pct` (simpan/restore nilai asli seperti test_runtime_settings).
- `agent_results` tersurface: jalankan pipeline dengan supervisor fake ber-`agent_results` →
  `result.to_dict()["agent_results"]` berisi dict tersebut.

## 7. Verifikasi (jalankan, laporkan output ringkas)

```
cd services/python
./.venv/Scripts/python.exe -m pytest tests/test_signal_lifecycle.py tests/test_risk_sizing.py \
  tests/test_telegram_transport.py tests/test_telegram_gateway.py tests/test_telegram_notifier.py \
  tests/test_telegram_digest.py tests/test_telegram_signal_bot.py tests/test_runtime_settings.py \
  tests/test_entry_completion.py tests/test_level_reporting.py -q
./.venv/Scripts/python.exe -m flake8 src/telegram/signal_lifecycle.py src/telegram/transport.py \
  src/telegram/gateway.py src/orchestration/pipeline.py src/orchestration/runtime.py src/system/settings_store.py \
  src/system/endpoints.py src/main.py tests/test_signal_lifecycle.py tests/test_risk_sizing.py \
  --max-line-length=100 --extend-ignore=E203,W503
./.venv/Scripts/python.exe -m black --check --line-length=100 src/telegram/signal_lifecycle.py \
  src/telegram/transport.py src/telegram/gateway.py src/orchestration/pipeline.py src/orchestration/runtime.py \
  src/system/settings_store.py src/system/endpoints.py src/main.py
```

Laporan akhir: file yang diubah + hasil test + catatan deviasi.
