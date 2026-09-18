# PHASE 5 — Telegram Transport Nyata + Report ke User

> Bagian dari [MASTER_PLAN_V2_OPERATIONAL_LOOP.md](./MASTER_PLAN_V2_OPERATIONAL_LOOP.md) | Status: PENDING

## Goal

Sambungkan `TelegramGateway` (sudah ada, read-only) ke **transport HTTP nyata**
(`httpx` → `api.telegram.org`) dan kirim **report otomatis** hasil analisis
pipeline ke user — tanpa pernah memberi Telegram kemampuan memicu order.

## Lokasi

- **File baru:** `services/python/src/telegram/transport.py` — `HttpTelegramTransport`
- **File baru:** `services/python/src/telegram/notifier.py` — ringkasan report + kirim
- **Update:** `services/python/src/telegram/gateway.py` — tambah label `pipeline_result` di `format_notification` (backward-compat)
- **Update:** `services/python/src/telegram/__init__.py` — ekspor helper baru + singleton `get_gateway()`
- **Update:** `services/python/src/system/endpoints.py` — `/telegram/status` jujur: `connected:true` hanya bila transport nyata terbentuk
- **Update:** `services/python/src/orchestration/runtime.py` — panggil notifier setelah tiap `run_cycle` (fail-safe)
- **Test baru:** `services/python/tests/test_telegram_transport.py`, `tests/test_telegram_notifier.py`

## Desain

### Transport (file baru, hanya httpx + stdlib)

```python
class HttpTelegramTransport:
    """POST https://api.telegram.org/bot<TOKEN>/sendMessage (timeout 10s)."""
    def __init__(self, token: str, client: Any = None, timeout: float = 10.0): ...
    def send_message(self, chat_id: object, text: str) -> None:
        # raise on HTTP/network error — gateway.notify() sudah menangkap
        # exception dan mengubahnya menjadi return False (fail-safe).
```

- `client` injectable (`httpx.Client`) agar test pakai `httpx.MockTransport` — tanpa network nyata.
- **Tidak pernah** menyimpan/melog token di luar URL request; URL dibangun saat kirim.
- Module ini **tidak boleh** mengimport modul execution/MT5 (guard test, pola sama dengan gateway).

### Gateway dari environment (di `telegram/__init__.py` atau `notifier.py`)

```python
def build_gateway_from_env(**providers) -> TelegramGateway:
    # TELEGRAM_BOT_TOKEN + TELEGRAM_ALLOWED_CHAT_IDS (sudah dibaca endpoints)
    # token ada  -> transport nyata; token kosong -> transport None (perilaku lama)
```

- Singleton `get_gateway()` / `set_gateway()` — dibuat sekali, dipakai endpoints + notifier.
- `/telegram/status`: `connected = bool(transport is not None and allowlist)` — jujur, tidak mengklaim live tanpa token.

### Notifier (file baru)

```python
def summarize_pipeline_result(result: dict) -> dict:
    """Ringkasan ringkas: event_type, decision, confidence, reasons (max 3),
    risk_reason, executed, trace_id."""

def notify_pipeline_result(result: dict, gateway: TelegramGateway | None = None) -> bool:
    """Kirim report 'pipeline_result' ke allowlist. Fail-safe: tidak pernah raise.
    Return False (tanpa log spam) bila transport/allowlist kosong."""
```

- Dipanggil dari `OrchestrationRuntime.run_cycle()` **setelah** `_record_decision`
  (semua jalur lewat sini: `/pipeline/run` + scheduler).
- Wrap `try/except` — Telegram tidak boleh memutus loop otonom.
- Label baru di `format_notification`: `"pipeline_result": "🧠 Market Analysis"`.

### Env (`.env`, tidak di-commit)

```
TELEGRAM_BOT_TOKEN=<dari @BotFather>       # kosong = fitur mati, sistem tetap jalan
TELEGRAM_ALLOWED_CHAT_IDS=<chat id user>   # wajib; allowlist penerima + pengirim perintah
```

## Langkah Implementasi (TDD)

1. Tulis `tests/test_telegram_transport.py` (RED):
   - POST ke URL benar + body `{"chat_id": ..., "text": ...}` via `httpx.MockTransport`
   - HTTP error → raise (ditangkap gateway) ; tanpa token → error jelas saat konstruksi
   - guard: modul transport tidak mengimport execution/MT5
2. Tulis `src/telegram/transport.py` → GREEN.
3. Tulis `tests/test_telegram_notifier.py` (RED):
   - `summarize_pipeline_result` memuat field wajib + reasons dibatasi
   - `notify_pipeline_result` dengan transport rekam → terkirim; tanpa transport → `False` tanpa raise
   - `build_gateway_from_env` tanpa token → `transport is None`
4. Tulis `src/telegram/notifier.py` + update `__init__.py` + label gateway → GREEN.
5. Update `system/endpoints.py` (`/telegram/status` pakai `get_gateway()`) + test endpoint.
6. Wire `runtime.run_cycle()` → `notify_pipeline_result(record)` (fail-safe).
7. Jalankan full suite; format (black/isort/flake8); commit + push.

## Acceptance Criteria

- [ ] `HttpTelegramTransport` mengirim POST nyata via httpx (terverifikasi dengan MockTransport)
- [ ] `/telegram/status` → `connected:true` **hanya** bila token + allowlist terisi
- [ ] Setiap `run_cycle` memicu notifikasi report (fail-safe; diam bila token kosong)
- [ ] Token tidak pernah muncul di log/kode/repo; `.env.example` berisi placeholder
- [ ] Guard test: gateway & transport tidak bisa menyentuh execution/MT5
- [ ] Full suite lulus; Flake8/black/isort bersih; commit + push

## Verifikasi Manual (oleh user, setelah token tersedia)

1. Isi `.env` → restart server Python.
2. `GET /telegram/status` → `connected:true`.
3. `POST /pipeline/run` dengan event apa pun → pesan "🧠 Market Analysis" masuk ke Telegram.
