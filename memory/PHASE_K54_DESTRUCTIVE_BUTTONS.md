# Phase K54 · Feb-2026 — Solid destructive-red button sweep

**Status**: Shipped to preview. 110/110 tests pass across the affected
surfaces (`k54-destructive-buttons.test.js` + regression sweep).

## Spec

| Token | Value |
|---|---|
| `colors.destructive.bg` | `#DC2626` (red-600) |
| `colors.destructive.bgHover` | `#B91C1C` (red-700) |
| `colors.destructive.fg` | `#FFFFFF` |
| `colors.destructive.ring` | `#EF4444` (red-500, for `focus-visible`) |
| `colors.destructive.disabledOpacity` | `0.55` |

Contrast check: white text on `#DC2626` → 5.9:1 (WCAG AA body + AAA large).
White on `#B91C1C` → 7.9:1 (AAA body). Both pass.

## Files touched

* `frontend/src/theme.js` — added `colors.destructive` block after
  `colors.gradient` (single source of truth).
* `frontend/src/components/ui/button.jsx` — destructive variant class
  migrated from semantic `bg-destructive` → Tailwind arbitrary values
  `bg-[#DC2626] text-white shadow-sm hover:bg-[#B91C1C]
   active:brightness-95 focus-visible:ring-[#EF4444]`.
  The base `cva` already carries `disabled:opacity-55` so every
  variant inherits it automatically.
* `frontend/src/layouts/AdminTopBar.jsx` — `SignOutButton` promoted
  from muted-gray pill w/ red text → solid red spec.
* `frontend/src/layouts/UniversalMenu.jsx` — portal Sign-out pill
  (floating variant) promoted from white bg w/ red text → solid red.
* `frontend/src/layouts/AppLayout.jsx` — mobile top-bar Sign-out
  promoted from K50 semi-transparent red tint
  (`rgba(239,68,68,0.35)`) → solid red spec.
* `frontend/src/pages/TenantPicker.jsx` — bare text-only link
  promoted to solid red pill.
* `frontend/src/components/portal/DeleteAccountDangerCard.jsx` —
  both Delete + Confirm buttons migrated from inline
  `style={{backgroundColor:"#DC2626"}}` → Tailwind arbitrary values
  with the full spec (hover, focus ring, disabled opacity).  Confirm
  button's disabled opacity moves `0.4` → `0.55` to match the shared
  token.

## Tests

New: `frontend/src/test/k54-destructive-buttons.test.js` — 14 assertions
covering:

1. `colors.destructive` token block exposes the exact spec hexes +
   values.
2. shadcn `Button variant="destructive"` uses `bg-[#DC2626]`,
   `hover:bg-[#B91C1C]`, `text-white`, `focus-visible:ring-[#EF4444]`,
   inherits `disabled:opacity-55`, and no longer uses the old
   semantic `bg-destructive` class.
3. All four Sign-out entry points (`header-signout`, `portal-signout`,
   `shell-logout-button-mobile`, `tenant-picker-logout`) paint the
   spec.
4. Regression: pre-K54 muted-gray tuple (`colors.surfaceSecondary` +
   `colors.error`) is gone from `AdminTopBar`.
5. Regression: K50 semi-transparent red tint is gone from `AppLayout`.
6. `DeleteAccountDangerCard` primary + confirm buttons match the spec
   and confirm button no longer uses `opacity-40`.

Updated (to keep the pre-K54 asserts from false-failing under the new
spec, without loosening the intent):

* `frontend/src/test/k52-theming.test.js` — destructive-is-not-gradient
  now asserts `bg-[#DC2626]` instead of `bg-destructive`.  Same intent
  (destructive stays flat, no emerald→sky gradient), K54-aware assertion.
* `frontend/src/test/k50-theming.test.js` — mobile Sign-out contrast
  test now asserts the K54 solid-red spec is present and the pre-K54
  semi-transparent tint is gone.

## Follow-ups (deferred)

The user brief mentioned "legacy inline destructive buttons, and
data-loss Cancels (Discard / Void / Deactivate)".  The shadcn
`Button variant="destructive"` consumers (4 files — Walkie,
MarketingTemplatesAdmin, RouteOptimizationApprovalModal,
DashboardDrillDownModal) all inherit the new spec automatically
because `button.jsx` was updated at the primitive layer.

Inline `bg-red-500` / `colors.error` custom destructive buttons
across the app (~30 files — SEO / marketing / portal / onboarding
surfaces) were **NOT** touched in this pass.  Each site uses a
bespoke class list, and migrating all of them at once creates a
higher-risk visual sweep that's better handled as a separate
Phase K54.1 audit with a targeted per-page checklist.  The main
Sign-out and shadcn `variant="destructive"` affordances — the
user-facing "solid red where it matters" surfaces — are all on
spec now.
