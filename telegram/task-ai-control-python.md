# Task C1 — AI Control (sisi Python): /tasks dari aktivitas nyata + /supervisor/status + rekonsiliasi budget

## Tujuan
Sisi Python berhenti mengembalikan data kosong/palsu untuk AI Control:
1. `/tasks` mengembalikan aktivitas agent NYATA dari tracker in-process (bukan `[]` hardcoded).
2. Endpoint baru `/supervisor/status` mengekspos state supervisor in-memory NYATA (`max_concurrency`, `token_budget`, `token_used`, `routing_policy`).
3. Budget advisor direkonsiliasi: setelah panggilan sukses, kelebihan estimate dikembalikan ke supervisor (estimate 1200 vs nyata ~60-220).

## Akar masalah (SUDAH diverifikasi — jangan diragukan)
1. `services/python/src/system/endpoints.py` ~line 286-297: `@router.get("/tasks")` mengembalikan `{"tasks": [], "counts": {...}, "source": "live"}` HARDCODED. Padahal `services/python/src/agents/activity.py` (singleton `get_activity_tracker()`) merekam `recent` per agent (deque maxlen=20, tiap entry `{signal, confidence, at}`) dan `main.py` ~514-524 sudah memakainya untuk `/health.agents[].recent`.
2. Node `apps/api/src/supervisorStatus.js` butuh sumber nyata untuk `token_budget`/`token_used`/`max_concurrency`. Probe langsung membuktikan: `runtime.pipeline.supervisor` ADA di proses dengan `max_concurrency=3, token_budget=8000, token_used=0, routing_policy='all_match'` (via `src/orchestration/runtime.py:430` + `:491`). `/scheduler/status.stats` TIDAK punya `max_concurrency`.
3. `services/python/src/llm/advisor.py:50` `DEFAULT_ESTIMATE_TOKENS = 1200` dikomit ke supervisor SEBELUM call (`_commit_budget` ~210-229 → `supervisor.check_token_budget`); panggilan nyata hanya ~60-220 token → `token_used` membengkak ~5x (probe live: 3800 vs nyata ~654). Tidak ada mekanisme refund.

## Perubahan yang diminta

### 1. `services/python/src/system/endpoints.py` — `/tasks` nyata
Ganti isi `tasks()` agar membaca `get_activity_tracker().snapshot()` (import lokal `from ..agents.activity import get_activity_tracker`, sama seperti `main.py`):
- Untuk tiap agent, tiap entry di `recent` → row: `{"id": f"{name}-{idx}-{at}", "timestamp": rec["at"], "agent": name, "action": f"analisis {rec['signal']} ({rec['confidence']})", "status": "success"}`.
- Urutkan rows terbaru dulu (`timestamp` desc); batasi total mis. 50.
- `counts`: `{"running": 0, "queued": 0, "completed": len(rows), "failed": 0}` (hitung dari rows — jangan fabrikasi).
- Tetap kembalikan `"source": "live"`. Bentuk response TIDAK berubah: `{tasks, counts, source}` (konsumen Node `buildActivityRows` membaca `timestamp/agent/action/status/duration_ms` — `duration_ms` opsional, tidak usah).
- Fail-safe: bungkus akses tracker dengan try/except → fallback `[]` (observability tidak boleh memecah endpoint).

### 2. `services/python/src/system/endpoints.py` — endpoint baru `/supervisor/status`
```python
@router.get("/supervisor/status", summary="Live supervisor runtime status")
async def supervisor_status() -> dict[str, Any]:
    runtime = get_runtime()
    supervisor = getattr(getattr(runtime, "pipeline", None), "supervisor", None)
    if supervisor is None:
        return {"supervisor": None, "source": "unavailable"}
    return {
        "supervisor": {
            "max_concurrency": int(getattr(supervisor, "max_concurrency", 0) or 0),
            "token_budget": int(getattr(supervisor, "token_budget", 0) or 0),
            "token_used": int(getattr(supervisor, "token_used", 0) or 0),
            "routing_policy": str(getattr(supervisor, "routing_policy", "") or ""),
        },
        "source": "live",
    }
```
(Router `system` tanpa prefix → path akhir `/supervisor/status`.)

### 3. `services/python/src/agents/supervisor.py` — refund budget
Tambah method di kelas `SupervisorAgent` (dekat `reset_token_budget` ~line 354):
```python
def refund_token_budget(self, amount: int) -> None:
    """Return unused estimate tokens after a real call used fewer tokens."""
    self.token_used = max(0, self.token_used - max(0, int(amount)))
```

### 4. `services/python/src/llm/advisor.py` — rekonsiliasi setelah call sukses
Setelah `total_tokens` dihitung (~line 325, sebelum update `self._calls`):
```python
if total_tokens > 0:
    unused = DEFAULT_ESTIMATE_TOKENS - total_tokens
    if unused > 0:
        supervisor = self._ensure_supervisor()
        if supervisor is not None:
            try:
                supervisor.refund_token_budget(unused)
            except Exception as exc:  # noqa: BLE001 - observability must not break advise
                logger.debug("advisor: refund budget gagal: %s", exc)
```
Jangan mengubah jalur refusal (refusal tidak commit budget, tidak perlu refund).

## Tests (TDD — tulis test GAGAL dulu, lalu implementasi)
1. `services/python/tests/test_system_endpoints.py`:
   - UPDATE `test_tasks_empty_is_honest` (~193-202): tetap assert 200 + `source == "live"` + `isinstance(data["tasks"], list)`; JANGAN assert `== []` tanpa syarat — singleton tracker bisa terisi dari test lain. Ganti jadi: bila `data["tasks"] == []` maka `counts["completed"] == 0`.
   - TAMBAH `test_tasks_reflect_real_activity`: `get_activity_tracker().record("technical_analyst", "BEARISH", 0.8)` → `GET /tasks` → ada row dengan `agent == "technical_analyst"`, `timestamp` non-kosong; lalu `get_activity_tracker().reset()` di akhir (try/finally).
   - TAMBAH `test_supervisor_status_reports_live_state`: `GET /supervisor/status` → 200, `source == "live"`, `supervisor["max_concurrency"] >= 1`, `token_budget >= 1`.
2. `services/python/tests/test_supervisor.py`: TAMBAH `test_refund_token_budget`: commit 300 → refund 240 → `token_used == 60`; refund 999 → `token_used == 0` (tidak pernah negatif).
3. `services/python/tests/test_llm_advisor.py`:
   - UPDATE `FakeSupervisor` (tambah `refund_token_budget` yang sama semantiknya).
   - UPDATE `test_status_reports_real_usage_and_budget`: `token_used == 60` (usage FakeClient 40+20) — bukan 1200; ini BUKTI rekonsiliasi.
   - TAMBAH `test_budget_reconciled_after_successful_call`: setelah advise sukses, `supervisor.token_used == 60` dan `supervisor.commits[0] == ("llm_advisor", 1200)`.
4. Semua test LAMA lain di 3 file itu harus tetap hijau.

## Verifikasi (WAJIB jalankan, laporkan output ASLI — bukan simulasi)
```bash
cd services/python
./.venv/Scripts/python.exe -m pytest tests/test_system_endpoints.py tests/test_supervisor.py tests/test_llm_advisor.py tests/test_agent_activity.py -q
./.venv/Scripts/python.exe -m flake8 src/system/endpoints.py src/agents/supervisor.py src/llm/advisor.py --max-line-length=100 --extend-ignore=E203,W503
./.venv/Scripts/python.exe -m black --check --line-length 100 src/system/endpoints.py src/agents/supervisor.py src/llm/advisor.py
```

## Batasan keras
- JANGAN menyentuh `services/python/src/config.py`, `services/python/src/main.py`, `services/python/src/market/news_feed.py`, `services/python/src/agents/analysts/fundamental_analyst.py` (task lain memegang file itu), atau apa pun di `apps/**`.
- JANGAN reformat massal; hanya baris/fungsi yang diubah.
- JANGAN commit/push.
- JANGAN menjalankan `restart-py.ps1`, `restart-all.ps1`, `run_ops_drills.py`, atau perintah apa pun yang menunggu service hidup.
- JANGAN memakai `&` di perintah terminal.
- JANGAN menambah dependency baru.

## Output yang diharapkan
1. Diff final file yang diubah.
2. Log verifikasi asli (pytest, flake8, black).
3. Ringkasan 3-6 baris: apa yang diubah dan kenapa.
