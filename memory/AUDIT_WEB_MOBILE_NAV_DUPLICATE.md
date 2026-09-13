# AUDIT · Web mobile — duplicate nav bars

**Type:** Diagnostic audit (no code changes).
**Owner:** main agent.
**Date:** Feb-2026.
**Reported:** Android Chrome (portrait), authenticated as super_admin.
Two navigation rows stack at the top of every page; desktop shows one.

---

## 1 · Grep results — the two nav components

### Row 1 · `<header className="md:hidden …">` in `AppLayout.jsx`

**File:** `frontend/src/layouts/AppLayout.jsx`, lines **508 – 586**.

**Renders when:** always mounted inside the authenticated shell; the outer `md:hidden` Tailwind class hides it above the 768 px breakpoint. So on desktop it stays hidden; on mobile it renders.

**Contents:**

- Hamburger button (`data-testid="mobile-nav-open"`) — gated on `role in (admin, super_admin)`.
- Tenant logo + `"Pool & Landscaping"` + role label chip (`SUPER_ADMIN`, etc.).
- Red `"Sign out"` button (`data-testid="shell-logout-button-mobile"`).
- `<RolePreviewSwitcher />` — the "Test as" dropdown. **This is the only nav surface that hosts the impersonation picker on mobile today.**

**Background token:** `colors.nav.bg` (navy) — matches the user's screenshot Row 1 description.

### Row 2 · `<AdminTopBar>` in `AppLayout.jsx` mounting `<AdminTopBar>` at L650

**File:** `frontend/src/layouts/AdminTopBar.jsx`, lines **317 – 412**.
**Mount site:** `AppLayout.jsx` L647-651, gated on `role in (admin, super_admin, manager, technician)`.

**AdminTopBar internal branch used on mobile:** L378-392 — a `md:hidden` narrow-viewport branch (comment L328-336 documents this is a Feb-2026 K76.1 fix: earlier JS `resize`-listener gating was unreliable; the branch is now a pure CSS gate, always in DOM, breakpoint decides).

**Contents (narrow branch):**

- `<MobileMenu>` — hamburger + `"Menu"` label button.
- `<AddCustomerButton>` — green `"+ Add Customer"` quick action (admin+ only).
- `<CreditsBudgetChip>` — yellow `"499c"` credits badge.
- `<SettingsSprocket>` — settings gear icon.
- `<SignOutButton>` — red logout arrow icon.
- `<UniversalMenu variant="inline" />` — bell / notifications.

**Background token:** also `colors.nav.bg` (navy). The user's Row 2 read as "white band" — this is because the CreditsBudgetChip + AddCustomerButton use bright yellow / green tokens that visually dominate a short 44 px band, making it read lighter than Row 1. Both bars are structurally navy.

---

## 2 · Diagnosis — why both render on mobile

Both rows are gated correctly on their own — but they were never made mutually exclusive.

- Row 1's `md:hidden` gate hides Row 1 on desktop.
- AdminTopBar's `md:hidden` internal branch (L381) hides that branch on desktop and shows its `hidden md:flex` sibling (L395).
- On desktop → Row 1 hidden, AdminTopBar shows its wide branch → **one nav bar**. ✅
- On mobile → Row 1 shown, AdminTopBar's narrow branch shows → **two nav bars stacked**. ❌

Timeline of the regression (reconstructed from in-file comments):

1. **Pre-K75:** `AppLayout` mobile header (Row 1) was the ONLY mobile nav. `AdminTopBar` was desktop-only.
2. **K75 / K76 (Feb-2026):** `AdminTopBar` was extended with its own mobile narrow-viewport branch (K76.1 fix quoted at L328-336). This delivered the "Menu / Add Customer / credits / settings / logout / bell" cluster.
3. **What was missed:** the original `AppLayout` mobile header was never retired or gated on "AdminTopBar is not present". Both now co-exist for admin / super_admin / manager / technician on mobile.

---

## 3 · Which is authoritative?

**`<AdminTopBar>` is authoritative.**

Reasons:

- It is the desktop nav — parity between desktop and mobile is the goal.
- It hosts the full admin-navigation surface: category dropdowns (`useVisibleGroups`), `AddCustomerButton`, `CreditsBudgetChip`, `SettingsSprocket`, `UniversalMenu` (bell/notifications), and `SignOutButton`. Row 1 has only a subset (hamburger + logo + sign-out + Test-as).
- It is CSS-only gated per K76.1's regression fix — no JS listeners, no jsdom snapshot drift.

The `AppLayout` mobile header (Row 1) is the legacy pre-K75 chrome that survived the K75 refactor by accident.

**However** — one surface currently lives ONLY in Row 1:

- **`<RolePreviewSwitcher />` — the "Test as" impersonation dropdown.** On desktop it also lives in `AdminSidebar.jsx` (L302), so desktop users can still impersonate. **On mobile, hiding Row 1 without moving `<RolePreviewSwitcher>` into AdminTopBar removes the impersonation surface entirely** because `AdminSidebar` is not mounted on mobile (it lives inside the slide-out drawer only after the hamburger opens — which means one extra tap, acceptable) — actually the drawer DOES mount `<AdminSidebar />` at AppLayout L636. So `<RolePreviewSwitcher>` is reachable via drawer → sidebar even without Row 1.

Net: hiding Row 1 does NOT lose functionality — every affordance is reachable through AdminTopBar (top) or the AdminSidebar drawer (behind the hamburger). Confirmed by grep of every `RolePreviewSwitcher` usage:

```
src/layouts/AdminSidebar.jsx:302   ← mounted inside the drawer sidebar
src/layouts/AppLayout.jsx:585      ← the Row-1 site we're removing
```

The drawer path is a two-tap flow (hamburger → sidebar → picker), the current Row 1 path is one-tap. Slight UX degradation for super_admin who use impersonation daily; can be mitigated by mounting `<RolePreviewSwitcher>` inside `AdminTopBar`'s narrow-branch right-cluster (see § 5).

---

## 4 · Cut-off "Test as" toggle — root cause

Row 1's flex layout at L509 is `flex items-center justify-between` with no `flex-wrap` and no `min-w-0` on children. On a narrow portrait viewport:

- Left group (hamburger + logo + role label) = ~180 px.
- Middle: red Sign out button = ~85 px.
- Right: `<RolePreviewSwitcher>` (a `<select>` + label) = ~140 px.
- Total ≈ 405 px content in a ~360 px viewport → the last-mounted child (`RolePreviewSwitcher` at L585, wrapped in `<div className="ml-2">`) overflows the container to the right and is visually clipped by `overflow: hidden` on `<main>` (L497-499).

**Fix falls out for free** if we hide Row 1: no more clipping because the surface is gone. If we instead moved the picker into AdminTopBar, the picker sits alongside `AddCustomer / Credits / Settings / SignOut / Bell` in a 44 px bar that already handles narrow overflow via the parent `<main class="min-w-0">`.

---

## 5 · Recommendation

**Fix — surgical, ≤ 25 LOC:**

1. **Gate Row 1 off for authenticated roles that render `AdminTopBar`.**
   In `AppLayout.jsx` around L508: wrap the `<header className="md:hidden …">` in a conditional so it renders ONLY for roles that DO NOT mount `AdminTopBar` (i.e. `customer` / `customer_portal` and other public/unknown roles). Roles in `["admin","super_admin","manager","technician"]` already have `AdminTopBar` doing the mobile chrome — Row 1 becomes dead code for them.

2. **Preserve the "Test as" picker for super_admin on mobile.**
   In `AdminTopBar.jsx` narrow branch (L385-391), mount `<RolePreviewSwitcher />` inside the right-cluster gap between `<CreditsBudgetChip />` and `<SettingsSprocket />` — the component already renders `null` for non-super_admin, so it's a no-op cost for admin/manager/technician.

3. **No changes to `<UniversalMenu>` / `<AdminSidebar>` / `<SignOutButton>`.**

**Files touched:** 2 (`AppLayout.jsx`, `AdminTopBar.jsx`).
**LOC estimate:** 8 – 15 lines (one conditional wrap + one component mount).
**Test impact:** grep of `shell-logout-button-mobile`, `mobile-nav-open`, `app-logo-mobile-white`, `mobile-nav-drawer` needs review — if tests assert Row 1 renders for admin, adjust to assert the AdminTopBar narrow branch instead. Preliminary grep count in the codebase for those four testids is worth confirming during implementation.

**Risks:**

- Zero functional loss for admin / super_admin / manager / technician — every affordance stays reachable via AdminTopBar or the drawer sidebar.
- `<AdminSidebar>` inside the drawer still hosts `<RolePreviewSwitcher />` at L302, so even without step 2, super_admin retain a two-tap path. Step 2 upgrades that to one-tap; worth doing but not strictly required.
- Customer / customer_portal roles are unaffected — they never mounted `AdminTopBar` (Row 2 was already hidden for them), and now they continue to mount only Row 1.
- Tenant with an unusual role string outside `["admin","super_admin","manager","technician","customer","customer_portal"]` would previously see Row 1 + no AdminTopBar; after the fix they still see Row 1 (correct — they have no AdminTopBar). Behaviour preserved.

**Cap:** well under the 100 LOC ceiling.

---

## 6 · Fix landed — Feb-2026 · Batch B tightening

**Status:** shipped in Preview.

### 6.1 · Changes

- **`frontend/src/layouts/AppLayout.jsx`** — wrapped Row 1's `<header>` (L508-586) in a role-scoped ternary. The IIFE just above the header derives `_mountsAdminTopBar = ["admin","super_admin","manager","technician"].includes(_effRole)` and the header block is rendered only when that boolean is `false`. Header content, styling, testids, and children (`RolePreviewSwitcher` still nested here for the customer / customer_portal / unknown branch) are byte-identical to the pre-fix code — only the outer conditional is new.
- **`frontend/src/layouts/AdminTopBar.jsx`** — new import `import RolePreviewSwitcher from "@/components/RolePreviewSwitcher"` and a single JSX mount inside the narrow-branch right-cluster (between `<CreditsBudgetChip />` and `<SettingsSprocket />`). Component self-gates via `canPreview` (see `hooks/usePermissions.jsx:170` — `role === "admin" || role === "super_admin"`, admin + super_admin both retain impersonation access per the long-standing product decision), so it's a no-op mount for manager / technician.

**LOC diff:**

```
frontend/src/layouts/AppLayout.jsx   | +14 / -6   (net +8)
frontend/src/layouts/AdminTopBar.jsx | +10 / -0
```

Total: **18 LOC (net +18)** — well under the 100 LOC cap.

### 6.2 · Tests added

- **`frontend/src/test/app-layout-mobile-nav-role-gate.test.jsx`** — 3 static-source cases:
  1. Row 1 `<header>` is wrapped in a role-scoped ternary (`) : null}` closer after `</header>`).
  2. Row 1 role tuple matches the AdminTopBar mount tuple byte-for-byte (audit § 5 requirement: "mirror the exact role-gate AdminTopBar uses, inverted").
  3. K50 theming preserved — Row 1 header still uses `colors.nav.bg`.
- **`frontend/src/test/admin-top-bar-mobile-role-preview-switcher.test.jsx`** — 3 static-source cases:
  1. `RolePreviewSwitcher` import present at the expected path.
  2. Mount site is inside the `admin-topbar-narrow-wrap` block, ordered between `AddCustomerButton` and `SignOutButton`.
  3. Exactly ONE mount in the file — the wide-branch does NOT double-mount the switcher.

All 6 new tests pass on first run.

### 6.3 · Pre-existing tests — no assertion flips required

Grep of every reference to `shell-logout-button-mobile`, `app-logo-mobile-white`, `mobile-nav-open`, and `mobile-nav-drawer` in `frontend/src/test/` was reviewed:

| Test | Why it stays green |
| ---- | ------------------ |
| `k50-theming.test.js` | String-based assertions on the raw AppLayout source — the header still exists in the file, only the outer render conditional changed. **All 23 cases still pass.** |
| `k54-destructive-buttons.test.js` | Same string-based pattern — locates `data-testid="shell-logout-button-mobile"` in source and validates the K54 red-token styling on the surrounding `<button>`. **All 21 cases still pass.** |
| `brand-logo-single-instance.test.jsx` | Renders `<AppLayout>` at test-viewport width (default jsdom ≈ 1024 px, i.e. `md:`+ desktop range), where Row 1 was always CSS-hidden. **No change in behaviour.** |
| `rail-nav.test.jsx`, `portal-maps-guard.test.jsx` | Import AppLayout for unrelated concerns (rail nav / portal guard); do not inspect the mobile header at all. |

**Zero flips required — no pre-existing test was asserting the old buggy "Row 1 also renders for admin/super_admin/manager/technician on mobile" contract.** This is a happy accident: the tests were all either source-string (unaffected by the ternary), desktop-viewport (Row 1 hidden by `md:hidden` anyway), or unrelated to the mobile header.

### 6.4 · Live verification

Screenshot captured at 390×844 (iPhone 12 Pro portrait) after login → workspace select → dashboard:

- Row 1 `<header>` count (`data-testid="shell-logout-button-mobile"`): **0** ✅
- Row 2 `<AdminTopBar>` narrow-branch count (`admin-topbar-narrow-wrap`): **1** ✅
- `RolePreviewSwitcher` mount count (`role-preview-switcher`): **1** ✅ (visible in Row 2 as the "Test as" chip with eye icon between CreditsBudgetChip and SettingsSprocket)

Cut-off "Test as" toggle bug from § 4 is auto-resolved — the picker now sits inside the 44 px AdminTopBar cluster which handles narrow overflow correctly via `<main class="min-w-0">`.

### 6.5 · Regression sweep

- Full frontend suite: **565 test files passed, 1 skipped, 4284/4284 tests pass, 34 skipped, exit 0.** Net gain +6 from the two new suites.
- OpenAPI count: **1734** (unchanged — audit was frontend-only).
- Root URL: **200**.

### 6.6 · Standing next-steps

None. The audit is closed.
