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

## 6 · Standing by for GO

Audit only — no code changes made. Awaiting confirmation to ship the two-file surgical fix.
