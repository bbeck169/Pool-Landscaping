# Phase K64 · Feb-2026 — Active / Hover Nav Color Unification

## Scope

Retire the K52 mint-green gradient (``colors.gradient.css``) on the
two **main-nav** surfaces and replace it with a lighter-navy solid
that renders identically for both hover AND active. All other
gradient consumers (badges, filter pills, sub-nav) are
intentionally untouched.

Surfaces changed:

1. **Left admin sidebar rail** — ``frontend/src/layouts/AppLayout.jsx``
   :: ``QuickNavRail``
2. **Top-nav category dropdowns** — ``frontend/src/layouts/AdminTopBar.jsx``
   :: ``CategoryDropdown``

## Token map

| Old (K52)                       | New (K64)                   |
|---------------------------------|-----------------------------|
| ``colors.gradient.css``         | ``colors.nav.bgActiveNavy`` |
| ``colors.gradient.cssHover``    | ``colors.nav.bgActiveNavy`` (hover ≡ active) |
| ``colors.gradient.fg``          | ``colors.nav.fg`` (unchanged white) |
| ``colors.gradient.textShadow``  | *(removed on main nav — solid needs no lift)* |

New token in ``frontend/src/theme.js``:

```js
nav: {
  bg:            "#1B1F5C",   // unchanged
  bgHover:       "#2A2F7A",   // unchanged (legacy)
  bgActive:      "#FFFFFF",   // unchanged (portal preview legacy)
  bgActiveNavy:  "#303AA0",   // ← K64
  fg:            "#FFFFFF",
  fgActive:      "#1B1F5C",
  fgMuted:       "rgba(255, 255, 255, 0.72)",
  border:        "rgba(255, 255, 255, 0.10)",
},
```

* ``#303AA0`` is HSL ``(235°, 54%, 41%)``, i.e. ``nav.bg`` lightened
  ~18% in HSL space. Distinct from ``bgHover: #2A2F7A`` so both
  states are visibly distinguishable from the base rail.
* Contrast: white on ``#303AA0`` → ~7.4 : 1 (WCAG AAA at all sizes).
* Focus ring (``focus-visible:ring-white/40``) still visible on
  the new background — the K50/K52 ring token was untouched.

## Behaviour

Both surfaces bind BOTH hover AND active to
``colors.nav.bgActiveNavy``:

* Active route: inline ``style.background = colors.nav.bgActiveNavy``.
* Hover on ANY item (idle or active): ``onMouseEnter`` forces
  ``e.currentTarget.style.background = colors.nav.bgActiveNavy``.
* ``onMouseLeave`` restores either ``bgActiveNavy`` (if the item
  is still the active route) or the idle fallback (``transparent``
  for the rail, empty string for the dropdown trigger).

The K52 ``hover:bg-white/10`` overlay was dropped from the two
rail/dropdown ``className`` branches — it fought the new solid.
Other unrelated ``hover:bg-white/10`` usages in ``AppLayout.jsx``
(the mobile bottom bar, etc.) are untouched.

## Files changed

| File | Change |
|------|--------|
| ``frontend/src/theme.js`` | Added ``colors.nav.bgActiveNavy`` |
| ``frontend/src/layouts/AppLayout.jsx`` | Rail NavLink active + hover → new token |
| ``frontend/src/layouts/AdminTopBar.jsx`` | ``CategoryDropdown`` trigger active + hover → new token |
| ``frontend/src/test/rail-nav.test.jsx`` | Updated the active-rail-item test to expect the new solid |
| ``frontend/src/test/k52-theming.test.js`` | Updated Slice D tests for the two main-nav surfaces (kept BusinessOS sub-nav on the gradient) |
| ``frontend/src/test/k64-nav-active-hover-unify.test.jsx`` | **New** — 12 cases covering token, both surfaces, hover=active parity, non-nav callers untouched |

## Grep — non-nav callers of the mint gradient (retained)

After the change, ``grep colors.gradient.css`` still finds these
callers (all out of K64 scope, intentionally unchanged):

| File | Purpose |
|------|---------|
| ``pages/invoices/InvoicesList.jsx`` | Late-fee badge + a list-view chip |
| ``pages/os/BusinessOS.jsx`` | Sub-nav pill inside the Business OS page |
| ``pages/schedule/CalendarSchedule.jsx`` | Preset chip inside the calendar filter strip |
| ``pages/customers/CustomersList.jsx`` | Scope filter pill inside the Customers page |

No file under ``src/layouts/`` references ``colors.gradient.*``
anymore. Locked by ``k64-nav-active-hover-unify.test.jsx`` last
describe block.

## Screenshot verification (preview)

Logged in as ``super@aquaterra.com`` and navigated to
``/schedule`` (which puts the rail "Schedule" item + the top-nav
"Operations" dropdown into the active state):

* Left rail "Schedule" (active): inline
  ``style="background: rgb(48, 58, 160); color: rgb(255, 255, 255);"``.
* Top-nav "Operations" (active): inline
  ``style="color: rgb(255, 255, 255); background: rgb(48, 58, 160);"``.
* Hovered "Dashboard" rail item (idle route): same
  ``rgb(48, 58, 160)``. **Hover ≡ active.**
* Hovered "Finance" top-nav (idle route): same
  ``rgb(48, 58, 160)``. **Hover ≡ active.**
* No mint green anywhere in main-nav DOM.

## Test counts

| Suite | Cases | Green |
|-------|-------|-------|
| ``k64-nav-active-hover-unify.test.jsx`` | 12 | ✅ |
| ``k52-theming.test.js`` (updated) | 22 | ✅ |
| ``rail-nav.test.jsx`` (updated) | 4 | ✅ |
| ``k63-lead-alerts-settings.test.jsx`` | 10 | ✅ (no regression) |
| ``k63-polish-dispatch-log.test.jsx`` | 10 | ✅ |

## Bonus flag (Schedule 404) — not fixed here

The user's screenshot showed a "Request failed (404)" banner on
the Schedule page. Reproducing on preview with
``super@aquaterra.com`` I saw **zero /api 404s** across the
Schedule mount cycle (I hooked into every ``page.on("response")``
Playwright event). The 404 was likely produced by a specific
interaction not covered by my probe (e.g. widget snapshot fetch,
a specific date-range calendar sync, or a customer-portal-scoped
call that requires the customer role). Queuing this as
**K65-candidate** for a follow-up diagnosis phase.
