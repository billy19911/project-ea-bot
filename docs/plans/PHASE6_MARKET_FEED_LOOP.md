# PHASE 6 — Market Feed Loop (MT5 → Event → Queue → Pipeline)

> Bagian dari [MASTER_PLAN_V2_OPERATIONAL_LOOP.md](./MASTER_PLAN_V2_OPERATIONAL_LOOP.md) | Status: PENDING FASE 5

## Goal

Buat loop latar belakang yang **membaca OHLC dari MT5 (read-only)** → deteksi event
market (`EventDetector`) → **enqueue ke queue runtime** → scheduler memproses →
pipeline menganalisis. Setelah fase ini, sistem menganalisis market **sendiri**
tanpa dipicu manual, dengan **default DISABLED** (operator harus menyalakan).

## Lokasi

- **File baru:** `services/python/src/trading/feed_loop.py` — `MarketFeedLoop`
- **Update:** `services/python/src/config.py` — settings feed (4 field baru)
- **Update:** `services/python/src/main.py` — start/stop loop di lifespan
- **Test baru:** `services/python/tests/test_market_feed_loop.py`

## Desain

### MarketFeedLoop

```python
class MarketFeedLoop:
    """Poll MT5 OHLC (read-only) -> detect events -> enqueue. Fail-safe."""

    def __init__(
        self,
        queue: EventQueue,                 # runtime.queue (queue produksi)
        symbols: list[str],                # mis. ["XAUUSD"]
        timeframe: str = "M5",
        interval_s: float = 60.0,
        count: int = 200,                  # jumlah bar per poll
        connector: Any = None,             # injectable untuk test; default mt5.connector
        detector_factory: Callable = ...,  # default EventDetector ber-queue
    ) -> None: ...

    def poll_once(self) -> int:            # 1 siklus: baca -> detect -> enqueue; return jumlah event
    async def run(self) -> None:           # loop: poll_once -> sleep(interval_s); CancelledError-safe
    def stop(self) -> None: ...
```

- **Detector produksi:** `EventDetector(deduplicator=EventDeduplicator(),
  queue=<runtime queue>, history=EventHistory())` — `_process_and_route` sudah
  menangani dedupe + enqueue + history (tidak perlu logika baru).
- **Konversi:** `connector.get_ohlc(symbol, timeframe, count)` → `list[OHLC]` dataclass →
  `list[dict]` (`time/open/high/low/close/volume`) sesuai kontrak `EventDetector.detect()`.
- **State per simbol:** `prev_state` disimpan agar deteksi berbasis transisi bar bekerja.
- **Fail-safe:** exception dari MT5/detector → `logger.warning`, siklus dilewati,
  loop **tidak pernah mati**. Queue penuh → `enqueue` mengembalikan `False` (sudah aman).

### Config (config.py)

| Env | Default | Keterangan |
|-----|---------|------------|
| `MARKET_FEED_ENABLED` | `false` | **Default OFF** — operator menyalakan eksplisit |
| `MARKET_FEED_SYMBOLS` | `XAUUSD` | comma-separated |
| `MARKET_FEED_TIMEFRAME` | `M5` | timeframe MT5 |
| `MARKET_FEED_INTERVAL_S` | `60` | jeda antar poll |

### Wiring lifespan (main.py)

```python
feed_task = None
if settings.market_feed_enabled:
    runtime = get_runtime()
    feed = MarketFeedLoop(queue=runtime.queue, symbols=..., ...)
    feed_task = asyncio.create_task(feed.run())
# shutdown: feed.stop(); (pola sama dengan scheduler_task yang sudah ada)
```

- **Prasyarat beroperasi:** `SCHEDULER_ENABLED=true` (agar queue diproses) +
  `MARKET_FEED_ENABLED=true`. Feed hanya *mengisi*; scheduler yang *mengolah*.
- **Read-only ketat:** hanya `get_ohlc`/`get_tick`. Tidak pernah menyentuh order/execution.
- MT5 live `armed=false` tetap berlaku — loop tidak mengubah status arming.

## Langkah Implementasi (TDD)

1. Tulis `tests/test_market_feed_loop.py` (RED) dengan connector palsu:
   - `poll_once()` → queue terisi event yang diharapkan (mis. breakout dari bar sintetis)
   - MT5 melempar exception → `poll_once()` return 0, tidak raise, loop lanjut
   - dedupe: bar identik dua kali → tidak dobel-enqueue
   - `stop()` → `run()` berhenti bersih (tanpa CancelledError bocor)
   - guard: modul feed tidak mengimport execution/order
2. Tulis `src/trading/feed_loop.py` → GREEN.
3. Update `config.py` (4 field) + `main.py` lifespan (start/stop) → test wiring.
4. Full suite; format; commit + push.

## Acceptance Criteria

- [ ] `MARKET_FEED_ENABLED=false` (default) → tidak ada task tambahan; perilaku lama utuh
- [ ] Enabled → queue terisi otomatis; `/scheduler/status` `events_processed` naik
- [ ] MT5 down → loop tetap hidup, hanya log warning (fail-safe terbukti di test)
- [ ] Dedupe mencegah event kembar; history event terekam
- [ ] Tidak ada jalur kode yang bisa memicu order dari feed
- [ ] Full suite lulus; Flake8/black/isort bersih; commit + push

## Verifikasi Manual

1. Set `MARKET_FEED_ENABLED=true` + `MARKET_FEED_SYMBOLS=XAUUSD` → restart.
2. `GET /scheduler/status` → `events_processed` > 0 setelah beberapa interval.
3. `GET /decisions?limit=5` → ada decision baru dari event feed (tanpa POST manual).
