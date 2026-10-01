TASK COMPLETE — COMPLETION REPORT below.

---

## TASK: 10 — UI / HEADER / RESPONSIVE PROFESSIONAL PASS
## STATUS: PASS

### FILES CHANGED
- `apps/web/components/AppShell.module.css`
- `apps/web/components/AppShell.tsx`

### ROOT CAUSE
- `.topbar` used `display: flex; justify-content: space-between` with `.actions { flex-shrink: 0 }`. Non-shrinking actions pushed the title out of the viewport at intermediate widths (1100/1024/920), producing pressure/overflow instead of a robust two-column layout. Plan required an explicit `grid-template-columns: minmax(0, 1fr) auto`.
- `.actions` had no `flex-wrap`, so page controls could not wrap — they forced the row wider.
- `.eyebrow` / `.topbar h1` had no truncation, so long titles could overflow their track.
- Page-supplied `actions` were wrapped in `.hideOnMobile`, which was `display:none !important` at ≤920px — this **hid critical status** (RiskBadge on Overview/Risk, SourceBadge on AI Control, env badges on Control Plane), violating invariant 23 and the plan directive "page actions: move/wrap at defined breakpoint" (wrap, not hide).

### FIX
1. `.topbar` → `display: grid; grid-template-columns: minmax(0, 1fr) auto;` with `column-gap/row-gap` (replacing fland space-between).
2. `.topbarText` → kept `min-width: 0` (WAJIB) + explicit `grid-column: 1`.
3. `.eyebrow` and `.topbar h1` → added `min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap` so long text shrinks instead of overflowing.
4. `.actions` → `grid-column: 2`, `min-width: 0`, `flex-wrap: wrap`, `justify-content: flex-end`, `align-items: center`. Removed `flex-shrink: 0`.
5. Added `.pageActions` (replacing `.hideOnMobile`) as a wrapping flex container so multi-fragment page actions stay in-row and wrap with the toggle/badge.
6. **≤920px defined breakpoint:** `.topbar` → `grid-template-columns: auto minmax(0, 1fr)`; `menuBtn` col1/row1, `topbarText` col2/row1, `.actions` `grid-column: 1 / -1; grid-row: 2; justify-content: flex-start; flex-wrap: wrap`. Page actions now **wrap to a full-width row instead of being hidden** — critical status stays visible (invariant 23).
7. `AppShell.tsx`: replaced `className={styles.hideOnMobile}` with `className={styles.pageActions}`; comment documents invariant 23.

### TESTS
- `npx tsc --noEmit` (workdir `apps/web`) → **clean, no output**.
- `npm run lint` (`eslint app/ components/ lib/`) → **clean, no output**.
- Static CSS assertions (grep on diff): confirmed `grid-template-columns: minmax(0, 1fr) auto`, `grid-template-columns: auto minmax(0, 1fr)`, `topbarText min-width: 0`, `.actions flex-wrap: wrap`, `.actions grid-column: 1 / -1` at breakpoint, `.pageActions flex-wrap: wrap`. No `hideOnMobile` references remain.

### RUNTIME VERIFICATION (CSS reasoning at required widths, no browser)
- `.shell` main column is `1fr` but `.main` has `min-width: 0` → the content column can shrink; `.topbar` border-bottom spans exactly the `.main` content width (observable: topbar is a direct child of `.main`, full width of the padded content box).
- **1920/1600/1440/1280/1100/1024 (desktop):** `.topbar` 2-col grid. Title col shrinks+ellipsizes; actions col floored at min-content and additionally wraps internally → actions never force horizontal scroll; title never pushed out. menuBtn `display:none` → not placed in grid. No horizontal scrollbar.
- **920/768/480/390 (tablet/mobile):** single content column; `.topbar` = `auto minmax(0,1fr)` with actions on a dedicated full-width second row that wraps. `menuBtn` occupies col1. Title ellipsizes in col2. No overflow; critical badges remain visible.
- Theme toggle (fixed 36×36 inline-flex) and EnvironmentBadge (inline-flex, intrinsic min-content) sit in a wrapping flex container → they wrap to a new line rather than shrink/clip. **Badge and toggle never clip.**
- Layout boundary: collapsed-rail rules are `min-width:921px`, mobile rules `max-width:920px` → no gap/overlap; collapsed sidebar keeps exact content alignment (grid columns shrink to `--rail-collapsed`, `.main` alignment unchanged).
- Sticky: `.topbar { position: sticky; top: 0; z-index: 20 }` with `OpsAlertBanner` (itself wrap-safe) rendered above inside `.main` — unchanged behavior, sticky header overlays following content (not the banner); does not overlap content at rest.
- Banner (`bannerText`) already `flex-wrap: wrap; min-width: 0` → no overflow contribution.

### REMAINING ISSUES
- Visual screenshots (desktop/tablet/mobile) to be captured by the ORCHESTRATOR with the browser tool — not performed here per instructions (no playwright/puppeteer, no server start/stop). CSS reasoning above covers all listed widths; tsc + lint pass.
- No horizontal-overflow / sticky behavior was verified in a live browser by this agent by design.

### NEXT TASK
NOT STARTED

All MT5 execution remains DISARMED by default — no arm default, env, or execution code was touched. Web dev server on :3000 was not started/stopped; no server commands were run.
