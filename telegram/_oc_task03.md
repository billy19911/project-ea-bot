# TASK 03 — SUPERVISOR + COMMITTEE BEHAVIOR

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. HEAD = 76a6bf9 (TASK 01+02 done).
Master plan: telegram/_MASTER_PLAN.md — BACA section 5 (TASK 03) + section 0 + section 15.
Safety: semua MT5 execution tetap DISARMED default. Dilarang enable LIVE.

## ATURAN EKSEKUSI
1. READ: telegram/_MASTER_PLAN.md section 5.
2. TRACE dulu arsitektur aktual: supervisor → department leads → specialists → committee synthesis → decision.
3. Audit-first: SKIP yg sudah benar, PATCH yg rusak, ADD hanya yg hilang.
4. Hanya TASK 03.

## GOAL
Hierarki logis + committee conversation natural.

Masalah saat ini: synthesis menghasilkan string template seperti "Konsensus: BUY (...)", "Kesepakatan: ...", "Keyakinan rata-rata: ...", "Konflik: ..." — terbaca seperti template, bukan diskusi committee nyata.

## REQUIRED ARCHITECTURE
Supervisor: 1) receives event 2) decides which departments relevant 3) requests evidence 4) collects specialist outputs 5) challenges conflicts 6) asks confirmation only when needed 7) synthesizes one canonical intent.

Department leads: Market Lead, Risk Lead, Review Lead.
Specialists: Structure, Momentum, Volatility, News, Macro.

## DO NOT
Jangan buat setiap agent bicara di setiap event. Contoh: BREAKOUT tidak otomatis butuh News/Macro/Review/Volatility/Momentum/Structure jika evidence tidak relevan.

## NATURAL COMMITTEE FORMAT (human-facing)
Contoh output yang diinginkan:
```
OVERWATCH

Structure sees a bullish break above the recent range, but the breakout is still
close to the previous resistance zone.

Momentum agrees with the direction, although strength is not extreme yet.

Volatility is acceptable for the setup.

News has no immediate high-impact contradiction.

Committee view:
BUY remains valid, but only if price holds above the breakout level.
```
Disagreement:
```
Structure: BUY
Momentum: NEUTRAL
Volatility: elevated

OVERWATCH:
The structure supports continuation, but momentum has not confirmed it.
I am not treating this as a clean entry yet.

Decision: WAIT
Reason: confirmation missing.
```
TANPA fake conversational fluff. Internal machine output tetap structured.

## REQUIRED STRUCTURED DATA (persist setiap committee cycle)
event, agents_called, agents_skipped, agent_outputs, conflicts, evidence, supervisor_reasoning, decision, confidence, signal_id.

## STOP GATE 03
[ ] Relevant specialists only (tidak semua agent dipanggil tiap event)
[ ] Conflicts visible
[ ] Supervisor explains why a specialist was called
[ ] Supervisor explains why a trade was rejected
[ ] Human-facing committee text natural
[ ] Machine structured output tetap deterministic
[ ] No agent independently creates an order

## COMPLETION REPORT (format section 15 plan)
TASK: 03 / STATUS: PASS atau BLOCKED / FILES CHANGED / ROOT CAUSE / FIX / TESTS (command+result) / RUNTIME VERIFICATION / REMAINING ISSUES / NEXT TASK: NOT STARTED
Kalau satu kriteria gagal: STATUS: BLOCKED dan STOP.
