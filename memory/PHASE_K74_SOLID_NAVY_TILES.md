# Phase K74 · Solid Navy Tiles — SHIPPED (Feb 2026, preview only)

## Scope

Replace the K70.a navy → green **gradient** tile surfaces on the Dashboard KpiCard icon chip and the ReportsHub BuiltTile background with a **solid navy** fill (`#1B1F5C`, same hex as `colors.nav.bg`). Per operator feedback the gradients read as busy against the K70.a pastel per-tone tile backgrounds — the solid navy calms the surface while keeping the "navy brand cue" intact.

**Scope guardrails:**
- Dashboard KpiCard: **only** the icon chip is swapped. Pastel per-tone tile background + colored left border (K70.a) are preserved verbatim. Icon glyph stays white.
- ReportsHub BuiltTile: **only** the tile background is swapped. The "Open report" **green CTA button** (`#15803D` fill + 1px white outline + white text) is preserved verbatim per K74 spec.
- ReportsHub **page canvas is NOT painted** — the page background stays as the ambient app surface.
- ReportsHub ComingSoonTile stays muted (dashed border + `surfaceSecondary` bg) — unchanged.
- Shared R0 `<KpiCard/>` at `/reports/suite` stays on the K70.a gradient — **out of K74 scope**.
- Every other `gradients.navyToGreen` consumer (primary Button, RevenueByService progress bars, Recharts strokes, portal hero banner, CustomerChemistry icon plate, etc.) stays on the gradient — **out of K74 scope**.
- Mobile has no equivalent Dashboard KpiCard / ReportsHub BuiltTile surface (mobile `theme.ts` has no `navyToGreen`; the sole `brandGradient` consumer is a UI Chip in `mobile/src/components/ui.tsx`). **No mobile mirror needed.**

## Delivery

- `frontend/src/theme.js` — new `colors.tile.solidNavy = "#1B1F5C"` token block inserted between `nav` and the K52 `gradient` block. Single source of truth for K74 surfaces. Contrast rule documented inline (white glyph/text on `#1B1F5C` = 12.8 : 1, AAA at all sizes).
- `frontend/src/pages/admin/Dashboard.jsx` — `KpiCard` icon chip: `background: gradients.navyToGreen.css` → `backgroundColor: colors.tile.solidNavy`. Data attribute renamed `data-k70a-gradient-chip` → `data-k74-solid-navy-chip`. `gradients` import retained (still consumed by the RevenueByService progress bar, out of K74 scope).
- `frontend/src/pages/reports/ReportsHub.jsx` — `BuiltTile` tile bg: `background: gradients.navyToGreen.css` → `backgroundColor: colors.tile.solidNavy`. Data attribute renamed `data-k70a-gradient-tile` → `data-k74-solid-navy-tile`. `gradients` import dropped from `@/theme` (no longer used — the CTA / ComingSoonTile / hub header don't reach for it).
- Green CTA button, icon plate inside the tile, K70.a subtitle/description white-on-surface text — **untouched**.

## Backend

Zero files changed. No `.env` changes. No dependency additions.

## Tests

- Updated `frontend/src/test/k70a-tile-theming.test.jsx` — the K70.a Dashboard-KpiCard and ReportsHub-BuiltTile describe blocks are now titled `K70.a → K74` and assert the solid-navy shape (`backgroundColor: colors.tile.solidNavy` + `data-k74-solid-navy-*` grep-lock) while retaining a NEGATIVE assertion that the K70.a gradient / attributes are gone from those specific surfaces. The shared R0 KpiCard block (`components/reports/KpiCard.jsx` full-tile gradient) is untouched — that surface stays on the gradient. Green-CTA / ComingSoonTile / K64 nav grep-locks preserved.
- Added `theme.js` assertion that `colors.tile.solidNavy === "#1B1F5C"`.
- Updated `frontend/src/test/feb2026-dashboard-kpi-tint.test.jsx` — the K70.a icon-chip block is now titled `Phase K74` and asserts solid navy + white glyph + `data-k74-solid-navy-chip`. Also added a scoped-negative that the KpiCard slice does not reach for `gradients.navyToGreen.css` (the top-of-file import is preserved because RevenueByService still consumes it below).

**Result — K74-relevant vitest surface: 44 / 44 PASS.**
- `feb2026-dashboard-kpi-tint.test.jsx` — 8 / 8
- `k70a-tile-theming.test.jsx` — 21 / 21
- `k67-navy-green-gradient.test.js` — 13 / 13 (grep-lock preserved: canonical `gradients.navyToGreen` token untouched)
- `reports-hub-r1-tile-flip.test.jsx` — 2 / 2

The full-suite run surfaces 32 pre-existing failure files (unrelated to K74 — verified via `git stash` against the untouched branch). No K74 regression.

## WCAG

- White glyph on `#1B1F5C` = 12.8 : 1 (AAA at all sizes). Up from ~7 : 1 on the K70.a green-stop mid-point.
- White title / subtitle / description on ReportsHub BuiltTile bg = 12.8 : 1 (AAA at all sizes). White-transparency variants (0.82 / 0.75) stay above AA large-text (4.5+ : 1) at 14px semibold.
- Green CTA fill `#15803D` on white text unchanged at 4.9 : 1 (AA body).

## Visual verification (deferred to operator)

Ship report queued for the operator's `e1_tester` UI smoke pass on `/dashboard` and `/reports`. No screenshots captured this phase per user directive ("Vitest direct is fine. No full testing_agent sweep needed for a token swap.").

## Next in queue

1. **K74.1** — lighten Schedule job-tile background on web & mobile (~`#EAF7F0` mint fill target).
2. **R2** — Operations Reporting suite kickoff.
3. **R3 → R7** sequential.
4. **K73.6** — legacy `user_id`-in-`technician_id` normalization (queued behind R7 per user).
