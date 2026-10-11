# Iteration 117 — Phase 39B mobile dashboard widgets
Commit 56864ac19. 7 web widgets ported to `src/components/dashboard/`, mounted in `app/(app)/index.tsx`:
Mass Messaging (below header) → Revenue insights → Action Cards → KPI → Topline → Soshie → Weather → Requested →
BulkOps / Crew / Routing / Warranties → Referral. Role gates mirror web Dashboard.jsx.
Route mapping: Today's Routes → /(app)/dispatch/board; Intelligence alerts → /web-only (no mobile screen);
Soshie moderation → /(app)/soshie-moderation; warranty rows → /customer/[id]; crew Schedule → /(app)/schedule/calendar
(crew param ignored by calendar). Invoice/leads filter params passed but those mobile screens don't read them.
Pre-existing failing suites (not touched): dashboard-active-inactive-tiles (theme mock lacks inputColors),
phase53e-mobile-ebit-tile (EbitTile standalone error-state test).
