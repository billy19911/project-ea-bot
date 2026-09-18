# PHASE 7 — Learning Feedback Loop (Lessons → Analisis)

> Bagian dari [MASTER_PLAN_V2_OPERATIONAL_LOOP.md](./MASTER_PLAN_V2_OPERATIONAL_LOOP.md) | Status: PENDING FASE 6

## Goal

Tutup loop belajar: lessons dari review **disimpan permanen** (lintas restart),
**dibaca kembali** saat analisis berikutnya (surface ke agen + report), dan
`/learning/analytics` melaporkan data **nyata** — bukan hardcoded `unavailable`.

## Lokasi

- **File baru:** `services/python/src/learning/lesson_store.py` — `JsonlLessonStore` (persist)
- **File baru:** `services/python/src/learning/feedback.py` — `LessonFeedbackProvider`
- **Update:** `services/python/src/agents/analysts/review_agent.py` — `set_lesson_store()` (inject)
- **Update:** `services/python/src/orchestration/pipeline.py` — inject `lessons` ke analysis context
- **Update:** `services/python/src/market/intelligence.py` + `src/risk/intelligence.py` — surface lessons di reasons
- **Update:** `services/python/src/system/endpoints.py` — `/learning/analytics` baca store nyata
- **Update:** `services/python/src/main.py` — wire store + bridge `ReviewAutoTrigger`
- **Test baru:** `tests/test_jsonl_lesson_store.py`, `tests/test_learning_feedback.py`

## Desain

### 1. Persistensi — JsonlLessonStore

```python
class JsonlLessonStore:
    """Append-only JSONL + in-memory cache. API identik InMemoryLessonStore."""
    def __init__(self, path: str): ...      # default: logs/lessons.jsonl (env LESSON_STORE_PATH)
    def add_lesson(self, lesson: dict) -> None:   # append 1 baris JSON; gagal tulis -> cache tetap
    def all_lessons(self) -> list[dict]: ...
    def get_lessons(self) -> list[dict]: ...      # alias
```

- Load saat init (file ada → baca; corrupt per-baris → skip baris rusak, fail-safe).
- **Tidak menyentuh** `memory/trade_memory.py` (constraint) — store berdiri sendiri.

### 2. Feedback — LessonFeedbackProvider

```python
class LessonFeedbackProvider:
    """Ringkas lessons relevan untuk context analisis (fail-safe, read-only)."""
    def summarize_for_symbol(self, symbol: str, max_lessons: int = 5) -> dict:
        # {"count": n, "wins": x, "losses": y,
        #  "recent": [{"category", "lesson", "outcome"} ...max_lessons]}
```

- `symbol="*"` → semua lessons (untuk event tanpa simbol).

### 3. Injeksi ke analisis

- `TradingPipeline(lesson_provider=None)` — param baru, **default None = perilaku lama**.
- `_build_analysis_context()`: bila provider ada → `context["lessons"] = provider.summarize_for_symbol(symbol)`
  (try/except — kegagalan provider tidak boleh memutus pipeline).
- **Konsumen (advisory, konservatif):**
  - `MarketLead.analyze()` + `RiskLead.analyze()`: bila `context["lessons"]` ada →
    tambah reason `"Historical lessons: {count} (W {wins}/L {losses}) — last: {ringkas}"`.
  - **Signal & confidence TIDAK diubah** di fase ini (deterministik tetap utuh).
    Pengaruh otomatis ke bobot keputusan dicatat sebagai follow-up terpisah.

### 4. Analytics nyata — `/learning/analytics`

```json
{"available": true, "source": "lesson_store",
 "lessons": [{"category": "...", "outcome": "...", "symbol": "..."}],
 "by_outcome": {"win": 3, "loss": 1}, "total": 4}
```

- `available:true` hanya bila ada ≥1 lesson; kosong → `available:false` (jujur).
- Update test existing yang meng-assert `available:false` bila ada.

### 5. Bridge ReviewAutoTrigger → store

- Jalur lama (`paper/simulated_execution.py` → `on_position_closed`) saat ini hanya
  menghitung review tanpa menyimpan lesson. Di lifespan: `set_auto_trigger(ReviewAutoTrigger(
  on_review=<callback tulis lesson ringkas ke store yang sama>))` — fail-safe.
- Dengan ini **kedua jalur review** (ReviewLead events + paper-close hook) menulis ke satu store.

## Langkah Implementasi (TDD)

1. `tests/test_jsonl_lesson_store.py` (RED): add → file bertambah; reload instance baru → lessons ada;
   file corrupt → fail-safe; API kompatibel `add_lesson`/`all_lessons`/`get_lessons`.
2. `src/learning/lesson_store.py` → GREEN.
3. `tests/test_learning_feedback.py` (RED):
   - `summarize_for_symbol` benar (count/win/loss/recent)
   - pipeline dengan provider → `context["lessons"]` terisi; tanpa provider → absen (backward-compat)
   - MarketLead/RiskLead reasons memuat "Historical lessons" saat ada data
   - `/learning/analytics` → `available:true` + by_outcome benar setelah ada lessons
4. Implementasi feedback + injeksi + surface + endpoint → GREEN.
5. `main.py`: wire `JsonlLessonStore` sebagai default store + bridge auto-trigger.
6. Full suite (termasuk test lama — pastikan tidak ada regresi); format; commit + push.

## Acceptance Criteria

- [ ] Lessons bertahan lintas restart (JSONL) — dibuktikan test reload
- [ ] `context["lessons"]` muncul di analisis & reasons MarketLead/RiskLead (advisory, tanpa ubah signal)
- [ ] `/learning/analytics` melaporkan lessons nyata (`available:true`, by_outcome benar)
- [ ] Kedua jalur review menulis ke store yang sama
- [ ] Fail-safe: store korup / provider error tidak memutus pipeline
- [ ] Backward-compat: tanpa provider/store baru, semua perilaku lama utuh
- [ ] Full suite lulus; Flake8/black/isort bersih; commit + push

## Follow-up (di luar fase ini)

- **Learning influence:** menyesuaikan bobot/confidence berbasis lessons (butuh desain
  hati-hati + backtest; sengaja dipisah agar keputusan deterministik tidak berubah diam-diam).
- Evaluasi berkala win-rate per regime dari lessons → bahan eksperimen (LearningLoop sudah ada).
