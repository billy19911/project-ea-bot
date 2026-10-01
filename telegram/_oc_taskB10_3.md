# TASK B-10 #3 — Sapu sisa `execution_allowed` di test (b4 + dual_import)

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. BACA dulu: `docs/tasks/B-10-auto-detect-active-terminals.md` section "TASK 3".
Prasyarat: TASK 1 & TASK 2 SUDAH selesai & lulus gate. TASK 1 sudah menyapu `test_mt5_terminals.py`, `test_fanout_multi_terminal.py`, `test_task06_canonical_fanout.py`, `test_task12_adversarial_e2e.py` (semua sudah nol).

Safety: DISARMED by default; DILARANG `git commit`/`git push`; DILARANG menyentuh `services/python/mt5_terminals.json`; DILARANG mengubah `services/python/src/**` di task ini (hanya test); jangan start/stop server.

## GOAL
Bersihkan referensi terakhir field mati `execution_allowed` di test (fake view yang meniru bentuk respons API lama). Field diganti `armable` (= running). Perubahan murni kosmetik: `execution_permitted()`/`get_armed_terminals()` tidak membaca field itu lagi, jadi perilaku test tidak berubah.

## SISA REFERENSI (hasil grep verifier — sumber saja, bukan .pyc/.next)
```
services/python/tests/test_b4_demo_validation.py:201:                    "execution_allowed": True,
services/python/tests/test_b4_demo_validation.py:903:                    "execution_allowed": True,
services/python/tests/test_dual_import_unification.py:66:            {"id": "demo-x", "execution_allowed": True, "running": True, "attached": True}
```
(`apps/web/app/control-plane/page.tsx` 5 lokasi → TASK 5 UI, JANGAN disentuh sekarang.)

## PERUBAHAN (WAJIB)
1. `test_b4_demo_validation.py` line ~201 dan ~903: `"execution_allowed": True,` → `"armable": True,` (dua fake view berbeda; keduanya punya `running` + `attached` sehingga perilaku tetap sama).
2. `test_dual_import_unification.py` line ~66: `{"id": "demo-x", "execution_allowed": True, "running": True, "attached": True}` → `{"id": "demo-x", "armable": True, "running": True, "attached": True}`.
3. Tambahkan komentar singkat di dekat field (opsional, max 1 baris): `# B-10: armable mirrors running; execution_allowed is gone.`
4. TIDAK ADA perubahan lain. Test TIDAK BOLEH diubah logikanya.

## VERIFIKASI (STOP GATE)
1. Grep nol (sumber saja):
```
grep -rn "execution_allowed" services/python/src services/python/tests apps/api/src 2>/dev/null | grep -v "\.pyc"
```
→ harus KOSONG (0 baris). `apps/web` masih ada 5 (TASK 5 — boleh, sebutkan di report).
2. Test hijau:
```
cd services/python && .venv/Scripts/python.exe -m pytest tests/test_b4_demo_validation.py tests/test_dual_import_unification.py tests/test_task06_canonical_fanout.py tests/test_task12_adversarial_e2e.py -q --basetemp="C:\Users\billy\AppData\Local\Temp\pa_b10_t3"
```
→ 0 failed.
3. Lint pada 2 file test yang diubah (black/isort/flake8, line-length 100).

## COMPLETION REPORT (Indonesia, format sama TASK 1/2)
```
TASK: B-10 #3 / STATUS: PASS atau BLOCKED
FILES CHANGED / ROOT CAUSE / FIX / TESTS / RUNTIME VERIFICATION (grep + test) / REMAINING ISSUES / NEXT TASK: NOT STARTED
```
Jika ada acceptance gagal → BLOCKED dan STOP.
