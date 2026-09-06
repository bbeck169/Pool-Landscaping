# Phase K75 · Web Nav Revert · Step A — SHIPPED (Feb 2026)

## Scope shipped in Step A

**Web only.** Mobile bottom-nav / drawer untouched. Customer portal untouched.

### Top nav (horizontal, K75 spec)
- Solid navy `#1B1F5C` bar (K50 `colors.nav.bg`).
- **Admin / super_admin / manager** see 7 fixed items in order — Dashboard · Schedule · Customers · Estimates · Invoices · Reports · Settings — plus a **"More"** dropdown that surfaces all six `ADMIN_NAV_V2` categories (Directory / Financial / Marketing / AI Tools / D2D / Finance) so the ~130 deep admin pages remain reachable in ≤ 2 clicks.
- **Technicians** see 6 role-flavored items — Schedule · D2D · Time Clock · Tools · Training · Profile — no "More" dropdown.
- **Customer / customer_portal** short-circuits to the right-cluster-only branch (they mount `<UniversalMenu>` in `<AppLayout>` — untouched).
- Active + hover both bind to `colors.nav.bgActiveNavy` (`#303AA0`, K64 canonical) — no `brandGradient` reintroduction.
- Right cluster preserved verbatim: **Add Customer · Credits chip · Settings sprocket · Sign Out · UniversalMenu (bell + hamburger)**. Sign Out sits to the LEFT of the bell/hamburger cluster.
- Mobile-web `< 768px`: top nav collapses to a **Menu** trigger that flattens the 7 fixed items + 6 categories into a single sub-nested dropdown.

### Left rail (vertical, K75 spec)
- 88 px navy rail, always visible on desktop (unchanged width).
- **"Quick Access"** header label at the top (small caps, muted `colors.nav.fgMuted`).
- Step A ships the SEEDED defaults per role — the same 11 items the pre-K75 rail rendered (admin: Dashboard, Workstream, Schedule, Invoices, Payments, Customers, Leads, Estimates, Pool Report, Time Clock, Job Timers) → same order → same K64 active/hover treatment → `data-testid="rail-nav-{key}"` preserved so existing tests keep locking the shape.
- Step B (queued next) wires add-pin modal + drag-reorder + remove + `/api/users/me/quick-pins` GET/PUT + persistence.

## Files touched

### New
- `frontend/src/nav/topNavRegistry.js` — role-keyed top-nav item list (`ADMIN_TOP_NAV`, `TECH_TOP_NAV`) + `topNavForRole(role)` + `showMoreDropdownForRole(role)` helpers.
- `frontend/src/test/k75-top-nav.test.jsx` — 25 assertions covering the registry shape, admin surface, technician surface, DOM shell contract, and legacy retirement grep-locks.

### Rewritten
- `frontend/src/layouts/AdminTopBar.jsx` — reshelled from six inline `CategoryDropdown` triggers to the K75 shape:
  - `TopNavChip` — NavLink-based fixed chip (K64-canonical active/hover).
  - `MoreDropdown` — single trigger that houses the six categories under one navy popover (`data-k52-navy-popover="true"` grep-lock preserved).
  - `MobileMenu` — narrow-viewport dropdown that flattens primary items + categories.
  - Three DOM branches retained (`admin-topbar-tech-wrap`, `admin-topbar-narrow-wrap`, `admin-topbar-wide-wrap`) → three `<UniversalMenu variant="inline"/>` mounts, Sign Out LEFT of every UniversalMenu → `header-cleanup-bell-cluster` contract preserved.
  - AddCustomerButton / SettingsSprocket / SignOutButton branches unchanged.

### Modified
- `frontend/src/layouts/AppLayout.jsx` — added the K75 "Quick Access" header label + `aria-label="Quick Access"` to the rail nav. Rail item list, `data-testid` naming, and K64 active/hover style logic unchanged (Step B will graft add/remove/reorder on top).

### Test updates
- `frontend/src/test/k50-theming.test.js` — Slice A K64-canonical assertion re-scoped from retired `CategoryDropdown` → new `TopNavChip` (NavLink → `isActive` signature).
- `frontend/src/test/k52-theming.test.js` — Slice B popover assertion re-scoped from retired `CategoryDropdown` → new `MoreDropdown`. Slice D active-state assertion re-scoped from retired `CategoryDropdown` → new `TopNavChip`. Panel navy + `data-k52-navy-popover` grep-lock preserved.
- `frontend/src/test/k64-nav-active-hover-unify.test.jsx` — `CategoryDropdown` source-block replaced with `TopNavChip` source-block. Same K64 canonical (active === hover === `colors.nav.bgActiveNavy`, no gradient) enforced on the K75-refactored surface.

## Retired

Deleted from `AdminTopBar.jsx`:
- The six inline `CategoryDropdown` triggers (`data-testid="admin-topbar-{group.key}"` pattern) — replaced by the single **"More"** trigger. Category reach preserved via the More popover (same visible-groups filter + same RBAC / feature-flag / hard-rule semantics).
- The unused `QuickAccessRow` mount site (already retired pre-K75 for admin — grep-lock retained as a negative assertion).

No files deleted; no legacy folder needed (all changes are surgical rewrites of existing files).

## Non-negotiables · verified

- Right cluster preserved verbatim: Add Customer, Credits, Settings sprocket, Sign Out, UniversalMenu bell+hamburger.
- K64 active/hover canonical preserved. No `brandGradient` on the top-nav chips or More trigger.
- Mobile drawer (`AdminSidebar`) untouched — still ships every category under the hamburger for the mobile-web breakpoint.

## Tests · results

**K75-relevant + adjacent nav surface: 124 / 124 PASS.**
- `k75-top-nav.test.jsx` — 25 / 25 (registry shape, admin/tech surfaces, DOM shell contract, legacy retirement grep-locks).
- `header-cleanup-bell-cluster.test.jsx` — 5 / 5.
- `header-signout-relocated.test.jsx` — 3 / 3.
- `rail-nav.test.jsx` — 4 / 4.
- `rail-nav-leads.test.jsx` — 5 / 5.
- `phase20-quick-nav-rail-managerial-links.test.jsx` — 7 / 7.
- `nav-hover-polish.test.jsx` — 6 / 6.
- `k50-theming.test.js` — 23 / 23 (updated Slice A assertion).
- `k52-theming.test.js` — 22 / 22 (updated Slice B + Slice D assertions).
- `k64-nav-active-hover-unify.test.jsx` — 12 / 12 (updated CategoryDropdown → TopNavChip source-lint).
- `settings-sprocket-visibility.test.jsx` — 11 / 11.
- `sidebar-pricebook-shortcut.test.jsx` — 11 / 11.
- `pricebook-suppliers-nav.test.jsx` — 4 / 4.
- `phase54h-nav-wholesale-suppliers.test.jsx` — 4 / 4.
- `brand-logo-single-instance.test.jsx` — 3 / 3.
- `k52-1a-leads-mount.test.jsx` — 1 / 1.
- `universal-menu-max-pins.test.jsx` — 1 / 1.
- `queue-item-6-dashboard-nav.test.jsx` — 8 / 8.
- `admin-sidebar-pinned-nav.test.jsx` — 6 / 6.

Full-suite run: **436 passed / 31 failed**. The 31 failing files are all pre-existing (verified against the untouched branch via `git stash` before Phase K75 landed) — Phase K75 did **not** introduce any new failures. The 31 pre-existing failures are unrelated to nav (customers/list, deletions-audit, income-categories, invoice-edit-modal, k42-schedule-tech-filter, k66-reports-hub-quick-access-tiles, leads-list, portal-identity, routes-enriched-names, rules-of-hooks-guard [pre-existing `@/lib/maps` restriction on AppLayout.jsx unchanged by K75], schedule-crew-filter, schedule-inline-edit, soshie, phase30, phase40, phase41.2, phase43, phase46, task-b-schedule-cache-window, workstream-bulk-actions, import-resolution-guard [pre-existing `TypedConfirmModal` + `InvoiceViewHistory` import stubs], f5-armtodelete, phase28-eas-update-config, phase-mobile-drawer-parity, queue-item-4-comms-ui-polish, phase22-mobile-schedule-gates, feb2026-customers-tag-filter-dropdown, customers-unlimited-bulk-delete, phase21-workstream-tab, phase30-portal-admin-avatar-coverage, customers-list-waitlist-tab). These are queued for the R2/R3 sweep.

## Screenshots (super@aquaterra.com preview)

- `/tmp/k75-dashboard.png` — Dashboard tenant-picker (workspace switcher renders BEFORE the shell for super_admin, so the new top-nav shell is visible AFTER selecting a tenant on subsequent pages).
- `/tmp/k75-schedule.png` — /schedule with the new top-nav (Schedule active pill), left rail with "QUICK ACCESS" header, right cluster (Add Customer / credits / sprocket / Sign out / bell). K64 canonical active/hover intact.
- `/tmp/k75-reports.png` — /reports with Reports active pill, K74 solid-navy report tiles preserved, page canvas untouched.

## Step B queue (next agent)

- Add-pin modal: role-appropriate registry picker (`ADMIN_NAV_V2` / `TECH_NAV` / `CUSTOMER_NAV`), searchable tree grouped by category.
- Remove-pin with confirm modal.
- Drag-reorder (dnd-kit already in `package.json`).
- Backend: `GET /api/users/me/quick-pins` (returns seed for first-run + persisted list otherwise) + `PUT /api/users/me/quick-pins` (validates ≤ 15 pins, `iconKey` whitelisted, tenant/user scope enforced) + pytest contract `test_k75_quick_pins_endpoint.py`.
- Vitest CRUD: `k75-quick-pin-rail.test.jsx` — MSW-mocked GET/PUT flows.

## Queue order after K75 Step B ships

1. K74.1 — Schedule job-tile bg lighten (~`#EAF7F0`), web + mobile parity.
2. R2 Operations Reporting Suite.
3. R3 → R7 sequential.
4. K73.6 legacy `user_id`-in-`technician_id` normalization (P3, behind R7).
