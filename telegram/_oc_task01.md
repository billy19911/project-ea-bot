# TASK 01 — R/R + PERFORMANCE PIPELINE

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. Working tree bersih.
Safety: SEMUA MT5 execution path tetap DISARMED default. Dilarang enable LIVE. Dilarang ubah default arm ke ON.

## ATURAN EKSEKUSI (WAJIB)
1. READ: baca XYNNBOT_MASTER_CRITICAL_FIX_PLAN.md section 3 (TASK 01) + section 0 (operating contract invariant 10-13) + section 15 (protocol).
2. TRACE dulu alur aktual: entry → final order → original SL → ticket/position identity → close detection → closing deal lookup → review → R calc → persistence → /v2/r-performance → Performance page. Jangan asumsi entry_context cukup.
3. PLAN singkat, lalu IMPLEMENT. Audit-first: SKIP file yg sudah benar, PATCH yg rusak, ADD hanya yg hilang. Jangan rewrite file working dari nol.
4. JANGAN kerjakan task lain. Hanya TASK 01.

## IMPLEMENTASI WAJIB
- 3.1 Canonical trade ledger durable (field: trade_id, signal_id, opportunity_id, account_id, terminal_id, symbol, direction, volume, entry_price, initial_stop_loss, initial_take_profit, initial_risk_price_distance, initial_risk_money, target_rr, opened_at, closed_at, exit_price, pnl, r_multiple, close_reason, broker_order_ticket, broker_deal_ticket, broker_position_ticket, status, review_status, created_at, updated_at).
- 3.2 RR eksplisit: risk_distance=abs(entry-initial_SL), reward_distance=abs(initial_TP-entry), planned_rr=reward/risk. Jangan infer dari trailing SL.
- 3.3 R dari ORIGINAL SL: BUY R=(exit-entry)/abs(entry-initial_SL); SELL R=(entry-exit)/abs(entry-initial_SL). Reject/mark unavailable jika entry/exit/initial_SL<=0, direction unknown, risk_distance<=0. Jangan fabricate R.
- 3.4 Close detection pakai MT5 deal/order history (bukan cuma positions_get): posisi hilang → identifikasi ticket → query deal history → closing deal → close price/time/PnL → join ledger → review tepat sekali.
- 3.5 Review persisted, survive restart (jangan cuma ReviewAutoTrigger._history memory).
- 3.6 /v2/r-performance baca dari durable records. Return trade_count, reviews_total, r_available, r_unavailable, overall, period buckets. Bedakan all closed vs valid R.
- 3.7 Performance UI empty state bedakan: No closed trades / Closed tapi R unavailable / API unavailable / Review pipeline belum proses close.

## TESTS WAJIB (semua harus pass)
BUY profit, BUY loss, SELL profit, SELL loss, exact 1R/2R/3R, trailing SL after entry, BEP after entry, missing original SL, restart before close, restart after close, manual broker close, fast SL/TP close, partial close, duplicate close event, same symbol multi-account.

## STOP GATE 01 (verifikasi satu-satu, tulis bukti per item)
[ ] R visible utk newly closed DEMO trade
[ ] RR stored di entry record
[ ] R survive Python restart
[ ] Performance survive restart
[ ] trailing SL tidak ubah initial R
[ ] duplicate close tidak duplikat review
[ ] API bedakan unavailable vs zero
[ ] semua R tests pass

## COMPLETION REPORT (format section 15 plan, tulis di akhir jawaban)
TASK: 01 / STATUS: PASS atau BLOCKED / FILES CHANGED / ROOT CAUSE / FIX / TESTS (command+result) / RUNTIME VERIFICATION / REMAINING ISSUES / NEXT TASK: NOT STARTED
Kalau satu kriteria gagal: STATUS: BLOCKED dan STOP.
