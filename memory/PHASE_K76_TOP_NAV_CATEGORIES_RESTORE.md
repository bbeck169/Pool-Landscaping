# Phase K76 · Web Nav Revert — Restore Original Category Dropdowns on Top Nav

**Date:** Feb-2026
**Scope:** Walk back the K75 7-fixed-items + "More" dropdown layout on the
top nav for admin / super_admin / manager. Restore the pre-K75
`ADMIN_NAV_V2` category dropdowns rendered directly (no truncation).

## Changes

### `frontend/src/nav/topNavRegistry.js`

- **Removed** `showMoreDropdownForRole` export (K75 gate no longer needed).
- **Rewrote** `topNavForRole(role)` — returns `TECH_TOP_NAV` for technician,
  `[]` for every other role (including admin/manager/super_admin — those
  render category dropdowns via `useVisibleGroups()` instead of a fixed
  strip).
- **Retained** `TECH_TOP_NAV` (6-item fixed strip: Schedule / D2D /
  Time Clock / Tools / Training / Profile) — unchanged from K75.
- **Retained** `ADMIN_TOP_NAV` (7 shortcuts: Dashboard / Schedule /
  Customers / Estimates / Invoices / Reports / Settings) — annotated
  as **legacy, only consumed by `pinRegistry.js`** (K75 Step B pin picker
  surfaces these as the "Primary" bundle at the top of the Add-Pin modal).
  The K76 top bar no longer imports it.

### `frontend/src/layouts/AdminTopBar.jsx`

Complete rewrite of the admin surface:

- **Removed** `MoreDropdown` component (killed the K75 "More" dropdown).
- **Removed** admin-side `TopNavChip` iteration over `fixedItems` (killed
  the K75 7-fixed-items strip for admin/manager/super_admin).
- **Added** `CategoryDropdown` component — one per visible
  `ADMIN_NAV_V2` group. Emits the pre-K75 testid pattern
  `data-testid={``admin-topbar-${group.key}``}` on the trigger and
  `data-testid={``admin-topbar-${group.key}-menu``}` on the panel.
  Panel carries the K52 canonical `data-k52-navy-popover="true"` marker.
- **Preserved** `TopNavChip` (technician branch still renders it for
  the 6 fixed items).
- **Active + hover state** on the category trigger = solid
  `colors.nav.bgActiveNavy` (K64 canonical, `#2A2F7A`). Uses the
  `data-[state=open]` Radix selector via a CSS variable pass-through so
  the open-state lock doesn't race a JS handler. **NO** `brandGradient`
  and **NO** green-tinted pill anywhere on the top nav surfaces.
- **Preserved** K74 solid `#1B1F5C` bar background
  (`colors.nav.bg` unchanged).
- **Preserved** right cluster verbatim: AddCustomerButton ·
  CreditsBudgetChip · SettingsSprocket · SignOutButton · UniversalMenu
  (variant='inline'). Sign-out sits LEFT of the bell + hamburger.
- **Preserved** three-DOM-branch shell contract (`admin-topbar-tech-wrap`,
  `admin-topbar-narrow-wrap`, `admin-topbar-wide-wrap`) — every existing
  header-cleanup + bell-cluster regression test still passes.
- **Mobile <768px** — `MobileMenu` now branches on which nav shape is
  active. For admin: renders category dropdowns only (no "Primary"
  section). For technician: renders the fixed-strip primary section
  only. One-tap reach to every page preserved.

### `frontend/src/test/k75-top-nav.test.jsx`

Rewrote the K75 contract as the **K76 category-restore contract**:

- Locks `TECH_TOP_NAV` order + `topNavForRole` role-scoping (unchanged
  from K75).
- Locks `topNavForRole('admin'|'manager'|'super_admin')` → `[]`
  (K76 walk-back).
- Grep-locks the retirement of the K75 7-fixed-items strip AND the
  "More" dropdown from the top-bar source.
- Grep-locks the restoration of the `admin-topbar-{group.key}` +
  `admin-topbar-{group.key}-menu` testid pattern.
- Grep-locks the K52 canonical `data-k52-navy-popover` marker on the
  category panels.
- Grep-locks that `colors.nav.bgActiveNavy` is present AND the only
  remaining `gradients.navyToGreen.css` reference sits inside
  `AddCustomerButton` (out of K76 scope per the brief).
- 26 tests, all passing.

### `frontend/src/nav/pinRegistry.js`

Untouched. Still consumes `ADMIN_TOP_NAV` from `topNavRegistry.js` for
the Add-Pin modal's "Primary" group (K75 Step B contract preserved).
`k75-quick-pin-rail.test.jsx` still passes 12/12.

## Preserved (no touch)

- K74 solid navy `#1B1F5C` bar background (`colors.nav.bg`).
- K74 solid navy tiles on Dashboard + ReportsHub.
- Left Quick Access rail (K75 Step B) — untouched, still user-editable.
- Tech top nav (6 fixed chips) — untouched.
- Customer / customer_portal top nav (empty right-cluster branch) —
  untouched.
- Add Customer button green-to-navy gradient CTA (predates K64, out of
  K76 scope).
- K52 navy popover styling on category panels.

## Verification

- **Vitest** `k75-top-nav.test.jsx` — **26/26 pass** ✅
- **Vitest** `k75-quick-pin-rail.test.jsx` — **12/12 pass** ✅
- **Vitest** `header-cleanup-bell-cluster.test.jsx` — **5/5 pass** ✅
- **ESLint** frontend — 0 errors ✅
- **ImportValidator** frontend + mobile — 0 findings ✅
- **Live preview** at `super@aquaterra.com`:
  - Top nav shows: `Finance` · `AI Employees` · `Marketing` ·
    `Operations` · `Customers` · `Reports` — 6 category dropdowns
    (Communications + Reviews are `hard_rule: "admin_only"` and
    filtered out for `super_admin`, which is the correct pre-existing
    RBAC behavior).
  - K74 solid `#1B1F5C` bar background verified.
  - Left Quick Access rail visible with seeded pins (Dashboard /
    Workstream / Schedule / Invoices / Payments / Customers / Leads /
    Estimates / PoolReport / Time Clock / Job Timers / + Add pin).
  - Right cluster verified: `+ Add Customer` · `3228c` credit chip ·
    sprocket · `Sign out` · bell+hamburger.
  - No "More" dropdown. No 7-fixed-items strip. No green-gradient pill
    on category triggers.
  - Screenshot saved: `/tmp/k76_dashboard_after.png`.

## Backward compatibility

- Existing K75 Step B pin picker keeps working (still surfaces the
  `ADMIN_TOP_NAV` 7 shortcuts as the "Primary" group).
- Existing K75 Step B `quickPins` schema (`preferences.quickPins`) is
  untouched.
- Existing K74 Solid Navy Tiles (Dashboard + ReportsHub) untouched.
- Tech routes unchanged.

## K76.1 — Mobile-Web Breakpoint Collapse Regression Fix

**Date:** Feb-2026 (same session as K76)
**Trigger:** `e1_tester` reported Test 7 failure — the mobile-web
breakpoint (<768px) did not collapse the top nav into a Menu trigger
(verified on tech nav @ `mike@aquaterra.com`, admin nav same component
family, same bug).

**Root cause:** the K76 rewrite used a JS `window.innerWidth` state
tracked via a `resize` listener. Mobile Safari fires `resize` only on
orientation change; embedded WebViews sometimes never fire it at all.
So the desktop wide-wrap stayed rendered below 768px in real mobile
browsers even though the initial `useState(() => window.innerWidth)`
seed picked up the correct value on some hardware.

**Fix:** swap the JS-driven gate for pure CSS via Tailwind's `md:`
breakpoint (768px).  Both branches are now always in the DOM; CSS
decides which one is visible via `display`:

- `admin-topbar-narrow-wrap` — className `md:hidden` (visible <768px only).
- `admin-topbar-wide-wrap` — className `hidden md:flex` (visible >=768px only).

A `useSyncExternalStore` mirror on `matchMedia("(max-width: 767.98px)")`
is retained so vitest snapshots can still assert branch selection
deterministically and the root `<div>` carries a `data-narrow` attribute
that flips in real time when the browser's media-query state changes.

**Files touched (K76.1 only):** `frontend/src/layouts/AdminTopBar.jsx` —
rewrote the responsive gate + wrapped narrow/wide branches in a
fragment so both render simultaneously. Test file
`frontend/src/test/k75-top-nav.test.jsx` — added a `K76.1 · mobile-web
breakpoint collapse` describe block (7 tests) covering: (a) both
branches in DOM simultaneously, (b) className asserts (`md:hidden` on
narrow, `hidden md:flex` on wide), (c) mobile-trigger inside narrow-wrap
for admin AND tech surfaces, (d) `data-narrow` reflects matchMedia
state (default 0, flips to 1 when `matchMedia` reports narrow via a
mock). Also scoped the "right cluster order" and "Add Customer +
Sprocket + SignOut" tests to the wide-wrap via `querySelector` so the
now-duplicated testids don't ambiguate them.

**Verification (K76.1):**
- **Vitest** `k75-top-nav.test.jsx` — **33/33 pass** ✅
- **ESLint** frontend — 0 errors ✅
- **ImportValidator** frontend + mobile — 0 findings ✅
- **Live preview** at `super@aquaterra.com`, viewport `400 × 800`:
  - `innerWidth=400` · `matchMedia(<768) = True`
  - `admin-topbar-wide-wrap` computed `display: none` ✅
  - `admin-topbar-narrow-wrap` computed `display: flex` ✅
  - `admin-topbar-mobile-trigger` computed `display: flex` ✅
  - Screenshot at `/tmp/k76_1_narrow_after.png` — hamburger "Menu"
    trigger visible on left, right cluster (+Add Customer / 3228c /
    sprocket / Sign out) on right, K74 navy bar preserved.
- **Live preview** at `super@aquaterra.com`, viewport `1280 × 800`:
  - Previous K76 behaviour unchanged — 6 category dropdowns inline.

