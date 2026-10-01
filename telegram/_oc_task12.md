# TASK 12 — ADVERSARIAL E2E CERTIFICATION

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. HEAD = (setelah TASK 11).
Master plan: telegram/_MASTER_PLAN.md — BACA section 14 (TASK 12) + section 17.
Safety: semua MT5 execution tetap DISARMED default. DILARANG enable LIVE / ubah default arm.

## ⚠ LESSON: JANGAN jalankan server blocking di foreground. Semua command harus selesai < 60 detik.
Web dev server :4321, python :5302, node :3789 SUDAH JALAN — JANGAN start/stop/restart.

## GOAL
Buat test E2E adversarial yang membuktikan invariant LINTAS STACK untuk 13 skenario (A-M):

### A. No event
market feed polls → no qualifying event → supervisor tetap idle → no proposal

### B. Event
qualifying event → wake → supervisor → committee → ONE signal

### C. Duplicate event
same event → TIDAK ada duplicate signal

### D. Multi-account
one signal → 3 accounts → 3 execution attempts → SAME signal_id

### E. One account fails
A success, B failure, C success → TIDAK ada AI analysis kedua

### F. Risk
existing exposure 25% + proposal 10% > limit 30% → BLOCK

### G. Restart
open broker position → restart → reconcile → state restored

### H. R
entry 2500, initial SL 2495, exit 2510 → risk=5, reward=10, R=+2, RR = planned reward/risk

### I. Trailing
initial SL 2495, trailing SL 2506, exit 2510 → R tetap dihitung dari 2495

### J. AI provider 503
LLM → 503 → agent error classified → no order → UI shows provider 503 (BUKAN "agent error" generik)

### K. Python service down
Python down → Node returns 503 → UI says Python unavailable

### L. LIVE disarmed
LIVE terminal configured → startup → DISARMED → signal boleh dianalisis → NO native order

### M. DEMO armed
DEMO terminal → explicit ARM → signal lolos semua gate → execution allowed

## Aturan
- Test harus pakai komponen NYATA (pipeline, supervisor, risk gate, fanout, reconciliation) — bukan mock karangan; broker boleh di-fake di boundary MT5 client saja.
- Test file: mis. tests/test_task12_adversarial_e2e.py (pytest).
- Setiap skenario = minimal 1 test dengan assertion eksplisit.
- Jalankan juga full suite — semua harus pass.
- Safety: pastikan di akhir tidak ada terminal armed; test M harus cleanup (disarm) setelah selesai.

## COMPLETION REPORT (format section 15 plan)
TASK: 12 / STATUS: PASS atau BLOCKED / FILES CHANGED / ROOT CAUSE / FIX / TESTS (command+result) /
RUNTIME VERIFICATION (per skenario A-M) / REMAINING ISSUES / NEXT TASK: NOT STARTED
Kalau satu skenario gagal: STATUS: BLOCKED dan STOP.
