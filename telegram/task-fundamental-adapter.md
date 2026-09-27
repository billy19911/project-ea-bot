# Task A — Fundamental: sambungkan payload news_feed → fundamental_analyst (FIX WIRING)

## Tujuan
Fundamental analyst harus menganalisis **data event nyata** dari news feed, bukan selalu jatuh ke NEUTRAL 0.55 karena key payload tidak cocok. Tidak ada perubahan pada scoring/lexicon/ambang — hanya menyambungkan bentuk data.

## Akar masalah (SUDAH diverifikasi, jangan diragukan)
1. Produsen `services/python/src/market/news_feed.py` → `NewsFeedProvider.get_news_context()` blok `formatted_events` (~line 655-700) mengirim per event keys:
   `headline`, `impact`, `sentiment` (hardcoded `0.0`), `date`, `forecast`, `previous`.
2. Konsumen `services/python/src/agents/analysts/fundamental_analyst.py` → `_parse_events()` (~line 245-266) membaca keys:
   `title`, `currency`, `actual`, `forecast`, `previous`, `sentiment`, `category`.
3. Akibat: `title`/`currency`/`actual` SELALU kosong → `_text_sentiment("")` = 0.0 dan `event.sentiment` = 0.0 → semua event netral → signal NEUTRAL 0.55.
   Bukti probe: payload bentuk produksi → NEUTRAL 0.55; payload dengan key benar (title/currency/actual) → BEARISH 0.78.
4. Sumber feed `ff_calendar_thisweek.json` TIDAK memiliki field `actual`. Jadi `actual` harus tetap string kosong bila tidak ada — **jangan fabrikasi**.

## Perubahan yang diminta

### 1. `services/python/src/market/news_feed.py` — `formatted_events`
Tambahkan key yang dibaca konsumen **tanpa menghapus key lama** (konsumen lain seperti `market/endpoints.py` dan `orchestration/runtime.py` memakai dict `sentiment` ini — jangan merusak):
- `title`: `ev.title` (judul asli tanpa prefix country).
- `currency`: `ev.country` (mis. `"USD"`).
- `actual`: ambil `getattr(ev, "actual", "")` → `""` bila tidak ada.
- `sentiment`: JANGAN lagi hardcoded `0.0`. Hitung deterministik memakai helper yang SUDAH ada di file yang sama: `score_headline_sentiment(...)` (~line 217) → `score_headline_sentiment(f"{ev.country} {ev.title}")[0]`. Simpan sebagai float.
- Pertahankan: `headline` (`f"{ev.country} {ev.title}"`), `impact` (`ev.impact.upper()`), `date`, `forecast`, `previous`.
- Jangan mengubah `formatted_news`, `sentiment_override`, `symbol`, `currency`, `updated_at`.

### 2. `services/python/src/agents/analysts/fundamental_analyst.py` — `_parse_events()`
Buat parser toleran terhadap kedua bentuk (lama & baru), tanpa mengubah skema `EconomicEvent`:
- `title = item.get("title") or item.get("event") or item.get("headline") or ""`
- `currency = item.get("currency") or ""`; bila kosong dan `title`/`headline` dimulai token 3 huruf A-Z + spasi, pakai token itu sebagai currency (mis. `"USD CPI m/m"` → `"USD"`). Implementasi kecil & deterministik (regex sederhana), bukan tebakan.
- `actual = str(item.get("actual") or "")`
- `impact`, `forecast`, `previous`, `sentiment` seperti sekarang; `sentiment` dibaca sebagai float bila bisa, default 0.0 (bila `None`/string aneh → 0.0, jangan crash).
- Jangan mengubah `analyze()`, scoring, lexicon, ambang, atau pesan NEUTRAL 0.55 saat tidak ada event (fail-closed tetap).

## Tests (TDD — tulis test yang GAGAL dulu, lalu implementasi)
1. `services/python/tests/test_news_feed.py` — test baru: `get_news_context` (mock `fetch_calendar` dengan `EconomicEventItem` yang punya country/title/impact) menghasilkan events dengan:
   - key `title`, `currency`, `actual` ada;
   - `currency == "USD"`, `title` tanpa prefix;
   - `actual` string (boleh `""`);
   - `sentiment` numerik dan **bukan selalu 0.0**: headline hawkish (mis. `"Fed hikes rates"`) → `sentiment > 0`.
2. `services/python/tests/test_fundamental_analyst.py` — test baru:
   - `test_parse_events_accepts_production_payload`: parse list berbentuk produksi (headline/impact/sentiment/date/forecast/previous) → `title`/`currency` terisi.
   - `test_analyze_production_payload_not_blind_neutral`: `analyze({"sentiment": {...events bentuk produksi...}})` pada event high-impact dengan keyword hawkish → `signal` bukan NEUTRAL atau `metrics["hawkish_score"] > 0` (bukan lagi buta).
3. Semua test LAMA di 2 file itu harus tetap hijau (perilaku default tanpa event tetap NEUTRAL 0.55).

## Verifikasi (WAJIB dijalankan, laporkan output ASLI — bukan simulasi)
```bash
cd services/python
./.venv/Scripts/python.exe -m pytest tests/test_news_feed.py tests/test_fundamental_analyst.py tests/test_llm_advisor.py tests/test_supervisor.py tests/test_system_endpoints.py tests/test_agent_activity.py -q
./.venv/Scripts/python.exe -m flake8 src/market/news_feed.py src/agents/analysts/fundamental_analyst.py --max-line-length=100 --extend-ignore=E203,W503
./.venv/Scripts/python.exe -m black --check --line-length 100 src/market/news_feed.py src/agents/analysts/fundamental_analyst.py
```

## Batasan keras
- JANGAN menyentuh `services/python/src/config.py`, `services/python/src/main.py`, `apps/api/src/index.ts`, atau file lain di luar 2 file target + 2 file test.
- JANGAN reformat massal; hanya baris yang diubah (black boleh memformat file yang diubah saja bila perlu).
- JANGAN commit/push.
- JANGAN menjalankan `restart-py.ps1`, `restart-all.ps1`, `run_ops_drills.py`, atau perintah apa pun yang menunggu service hidup.
- JANGAN memakai `&` di perintah terminal.
- JANGAN menambah dependency baru.

## Output yang diharapkan
1. Diff final 2 file sumber + 2 file test.
2. Log verifikasi asli (pytest, flake8, black).
3. Ringkasan 3-6 baris: apa yang diubah dan kenapa.
