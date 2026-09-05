# Phase K50 — Theming (Navy chrome + Schedule card status shading)

**Ship date:** Feb 2026
**Slices:** A — Web navy sidebar + top main menu (web only) · B — Schedule
job-card status background shading (web + mobile parity)
**Status:** 🟢 SHIPPED — 71/71 web vitest + 6/6 mobile jest green; live
preview confirms navy chrome renders correctly on `/schedule`.

---

## Slice A — Navy sidebar + top main menu (WEB ONLY)

### Single-token source of truth
`frontend/src/theme.js` — new `colors.nav` block replaces the pre-K50
sky-tinted wash on the two desktop chrome surfaces the K50 brief called
out.  Every navy hex in the codebase now resolves through
`colors.nav.*` — no hex hardcoding elsewhere (regression-guarded in
`k50-theming.test.js`).

```js
nav: {
  bg:       "#1B1F5C",   // Pipedrive brand navy
  bgHover:  "#2A2F7A",   // one shade lighter for hover
  bgActive: "#FFFFFF",   // white pill (active nav item)
  fg:       "#FFFFFF",
  fgActive: "#1B1F5C",   // navy text on white pill
  fgMuted:  "rgba(255, 255, 255, 0.65)",
  border:   "rgba(255, 255, 255, 0.10)",
}
```

Contrast (WCAG AA / AAA):
* `nav.fg` on `nav.bg` → **12.8 : 1** (AAA at all sizes).
* `nav.fgActive` on `nav.bgActive` → **12.8 : 1** (AAA at all sizes).

### Files touched (Slice A)
| File | Change |
|---|---|
| `frontend/src/theme.js` | Added the `nav` token block. |
| `frontend/src/layouts/AppLayout.jsx` | Desktop `<aside>` bg → `colors.nav.bg`. `QuickNavRail` idle state renders white icon+label on transparent (parent navy shows through), active state renders a white pill with navy text. Removed all `hover:bg-sky-50/70` / `group-hover:text-sky-600` classes. |
| `frontend/src/layouts/AdminTopBar.jsx` | Wrapper bg → `colors.nav.bg`. `CategoryDropdown` triggers render white on navy with white-pill active state (matches the rail). Narrow-viewport "Menu" trigger switched to white-outlined-transparent pill so it reads on navy. |
| `frontend/src/test/rail-nav.test.jsx` | Rewrote the active-color assertion to expect the new white-pill / navy-text combo. |
| `frontend/src/test/nav-hover-polish.test.jsx` | Rewrote the topbar-tint assertion to expect `colors.nav.bg`. |

### Out-of-scope (unchanged per brief)
* Mobile sidebar / drawer chrome — light palette retained.
* Customer portal shell — untouched.
* `AdminSidebar` group content (only rendered inside the mobile drawer)
  — untouched; the drawer wrapper stays on the light palette so the
  group content reads correctly.

### Preview verification (live)
```
[k50] side-nav       bg = rgb(27, 31, 92)   → #1B1F5C ✓
[k50] admin-topbar   bg = rgb(27, 31, 92)   → #1B1F5C ✓
```
Screenshot: white "Operations" (category dropdown active) pill and
white "Grid" pill sit cleanly on the navy chrome; right-side buttons
(Add Customer / Sign out / notification bell / etc.) all read at
sufficient contrast.

---

## Slice B — Schedule job-card status background shading (WEB + MOBILE)

### Single-helper source of truth
* Web: `frontend/src/lib/jobStatus.js` — exports `jobStatusColor()` +
  frozen `K50_JOB_STATUS_BG` map.
* Mobile: `mobile/src/lib/jobStatus.ts` — byte-for-byte parity mirror
  (parity gate in the mobile jest suite).

```
open        → #D6F5EE   light teal green
scheduled   → #D6F5EE   (alias for open on the Schedule surface)
in_progress → #FEF3C7   Tailwind yellow-100
completed   → #FDECEC   soft pink
cancelled   → #FECACA   Tailwind red-200 (deliberately redder than completed)
skipped     → #FED7AA   Tailwind orange-200
```

Alias table (both surfaces):
```
active     → in_progress
inprogress → in_progress
closed     → completed
done       → completed
canceled   → cancelled   (US → canonical UK spelling)
```

Any status outside the map returns `null` so callers fall back to
their previous default (`colors.surface` / white).  This is
deliberate — statuses like `on_hold` / `requested` / `reopened`
already carry pill treatments and must NOT be silently painted the
generic "in_progress" yellow.

### Files touched (Slice B)
| File | Change |
|---|---|
| `frontend/src/lib/jobStatus.js` (new) | Helper + frozen map. |
| `frontend/src/pages/schedule/CalendarSchedule.jsx` | Imported `k50JobStatusColor`; card body `background` now resolves through the helper (falls back to `colors.surface`). Emits `data-k50-bg` for regression scans. Existing status-derived left-accent stripe and border preserved. |
| `frontend/src/pages/schedule/TodaySchedule.jsx` | Same wiring on the Today-view schedule card rows. |
| `mobile/src/lib/jobStatus.ts` (new) | Mobile mirror. |
| `mobile/app/(app)/schedule/calendar.tsx` | Imported `k50JobStatusColor`; `JobRow` Pressable style layers `{ backgroundColor: k50CardBg }` on top of `gStyles.card`. Existing `borderLeftColor` status accent preserved. |
| `frontend/src/test/k50-theming.test.js` (new) | 13 checks — helper contract (5 statuses + aliases + case-insensitivity + null fallback + frozen map), plus source-body assertions that both Schedule pages wire the helper (never inline hexes). |
| `mobile/__tests__/k50-job-status-color.test.ts` (new) | 6 checks — same helper contract + parity gate (`toEqual` against the web map to catch future drift). |

### Preserved behaviours (unchanged per brief)
* Existing status-derived **left-accent border stripe** on job cards
  — kept (K50 only touches the card body background fill).
* Status **pill/badge** colors (`STATUS_PILL`, `STATUS_COLORS`,
  `cardStatusTone`) — untouched.
* Status **filter chips** at the top of the Schedule — untouched.
* Calendar-event **dot colors** (`STATUS_COLORS`) — untouched.
* Reports / dashboards / autopilot status→color mappings — untouched.

### Text legibility on the new tints
All K50 shades are pastel (L ≥ 90).  The existing schedule-card
subheading gray (`colors.onSurfaceSecondary` = `#6b7280`) passes
WCAG AA against each of the five tints; no sub-text darkening was
needed.  Primary titles use `colors.onSurface` (`#111827`) which
passes AAA against all five.

### Legend
No pre-K50 legend existed on the Schedule pages — per brief we did
NOT add one.

---

## Test evidence

### Web (vitest)
```
✓ src/test/k50-theming.test.js               13/13
✓ src/test/rail-nav.test.jsx                  4/4
✓ src/test/nav-hover-polish.test.jsx          6/6
✓ src/test/k41-dashboard-drilldown-modal.test.jsx  20/20
✓ src/test/k48-drilldown-business-unit.test.jsx    16/16
✓ src/test/k49-customers-filter-defaults.test.jsx  12/12
================================================================
Total (K41 + K48 + K49 + K50 + neighbours):  71/71 green
```

### Mobile (jest)
```
✓ __tests__/k50-job-status-color.test.ts     6/6
```

### Pre-existing / unrelated failures (reproduce on `git stash`, not touched)
* `schedule-inline-edit.test.jsx > work_class segmented picker` —
  pre-existing, unrelated to K50 (asserts a `schedule-job-edit-work…`
  testid on the `ScheduleJobEditModal` that never existed on this
  branch).
* `test_customers_pagination_p35.py` — pre-existing (documented in
  K49b ship report).
* `test_invoice_edit.py` — pre-existing (documented in K48 ship
  report — uses `manager@aquaterra.com` which
  `_require_staff(admin/super_admin)` has always rejected).

---

## Revert safety
Each slice touches disjoint files:
* Slice A revert: `theme.js` (nav block), `AppLayout.jsx`,
  `AdminTopBar.jsx`, `rail-nav.test.jsx`, `nav-hover-polish.test.jsx`.
* Slice B revert: `frontend/src/lib/jobStatus.js` (new — delete),
  `frontend/src/pages/schedule/CalendarSchedule.jsx` (revert two
  hunks), `frontend/src/pages/schedule/TodaySchedule.jsx` (revert one
  hunk), `mobile/src/lib/jobStatus.ts` (new — delete),
  `mobile/app/(app)/schedule/calendar.tsx` (revert `JobRow` +
  Pressable style hunks), `k50-theming.test.js` (revert Slice-B
  describe block), `mobile/__tests__/k50-job-status-color.test.ts`
  (new — delete).
Either slice can be reverted without disturbing the other.

---

## Follow-ups (not shipped)
* Mobile chrome navy parity (deferred per brief — user explicitly
  scoped Slice A to web only).
* AdminSidebar drawer content palette rework (would only matter if
  the mobile drawer background is ever navy-ified).
* Optional: expose `colors.nav` as CSS variables (`--color-nav-bg`,
  etc.) on the `<html>` element so ad-hoc Tailwind arbitrary values
  can reference the token — currently every consumer imports
  `colors` from `theme.js`, which is sufficient for the two shipped
  surfaces.
