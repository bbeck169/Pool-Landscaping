# Feb-2026 · Responsive Quote/Estimate Pages + Email Logo Aspect Ratio Fix

## Touched files

| File | Change | LOC delta |
| ---- | ------ | --------- |
| `frontend/src/components/EstimateView.jsx` | Gated existing tables with `hidden sm:table`; added parallel stacked-card lists (`sm:hidden`) for both grouped + itemized paths | +120 (net) |
| `frontend/src/components/EstimateView.css` | New `.ev-lines-cards` / `.ev-line-card*` block + `<sm` overflow reset | +80 |
| `backend/services/email/theming.py` | Logo img aspect-ratio + centering fix; header td → `align="center"` + inline `text-align:center` | +5, −4 |
| `frontend/src/test/estimate-view-responsive-cards.test.jsx` (NEW) | Vitest — 5 tests | +204 |
| `backend/tests/test_email_theming_logo_aspect.py` (NEW) | Pytest — 5 tests | +122 |

No fixed-pixel widths existed on any staff-facing wrapper of
`pages/quotes/QuoteInvoiceDetail.jsx` or in `K71LineItemsEditor.jsx`,
so no outer-container prune was required. `min-w-0` is a flex-shrink
override (correct) and was left in place.

## Task A — Responsive Quote & Estimate (web)

### Approach
Kept both existing customer-facing tables in `EstimateView.jsx`:
* `estimate-grouped-lines-table` (per-group rollup, Service / Subtotal / Decline)
* `estimate-line-items-table` (itemized fallback, admin/preview view)

Added Tailwind gates:
* Tables now carry `className="iv-lines hidden sm:table"` — desktop
  ≥ 640 px keeps the current visual verbatim, `< 640 px` hides them.
* A sibling `<ul className="ev-lines-cards sm:hidden">` renders the
  same data as stacked cards below 640 px. Each card exposes:
  1. Group / line description (with existing declined chip when
     applicable).
  2. `Subtotal` label + value (tabular numerals).
  3. Full-width Decline (or Restore / Undo Decline) button — 44 px
     min-height tap target, distinct testids with a `-mobile` suffix
     so pre-existing suites that lookup the non-mobile testid stay
     green.

Testids introduced (mobile block):
* `estimate-grouped-lines-cards` (container)
* `estimate-grouped-card-<cat>` (per-group card)
* `estimate-grouped-decline-btn-mobile-<cat>`
* `estimate-grouped-restore-btn-mobile-<cat>`
* `estimate-line-items-cards` (container)
* `estimate-line-item-card-<i>`
* `estimate-line-item-decline-mobile-<i>`
* `estimate-line-item-undecline-mobile-<i>`
* `estimate-line-item-declined-chip-mobile-<i>`

Original testids (`estimate-grouped-decline-btn-<cat>`, etc.) are
untouched on the table version — the 4290-strong Vitest suite
continues to pass without any assertion flip.

### Horizontal-scroll fix at 375 px
`EstimateView.css` previously enforced
`min-width: 700px` on the `<table>` inside `.ev-lines-wrap` and
`overflow-x: auto` on the wrap. Below `sm` we now:
* Emit the table with `display:none` via Tailwind `hidden` (no
  intrinsic sizing).
* Defensive-ly reset `.ev-lines-wrap { overflow-x: visible; }`
  and `.ev-lines-wrap table { min-width: 0; }` in a
  `@media (max-width: 639.98px)` block.

Result: at 375 px viewport the container never widens past the
viewport; only the stacked cards render.

### Totals block
The `<table class="ev-totals">` is a simple 2-column key/value
structure. `components/documents/docMobile.css` already resets it
to `width:100%` + `display:block` + dashed divider on `<md` — no
further changes needed. Testids (`estimate-totals-subtotal`,
`estimate-totals-cost`, `estimate-totals-taxes`, etc.) resolve
unchanged.

### Preserved functionality
* `declineGroup` / `restoreGroup` PATCH endpoints are shared —
  clicking the mobile Decline button issues the same
  `/portal/quotes/via-token/{token}/groups/{gk}/decline` (or admin
  variant) as the desktop button. Verified in test #3 of the new
  Vitest file.
* Duplicate quote / Mark sent / Send-to-customer / accept-decline
  toolbar buttons live outside the line-items block; no changes
  to those surfaces.
* Grouped-layout LOCK-ON contract preserved (customer surface
  auto-groups when `customer_group_display=true`).

## Task B — Email header logo aspect ratio

### Symptom
Old `<img>` style:
```
width="180"
style="max-width:180px;max-height:56px;display:block;
       border:0;outline:none;text-decoration:none;
       height:auto;line-height:100%;-ms-interpolation-mode:bicubic;"
```
`max-height:56px` combined with `width="180"` squished tall logos
vertically because the client honoured the height cap before
resolving `height:auto`. Header `<td>` was `align="left"` so the
squished logo hugged the left edge of the dark brand band.

### Fix — inside `wrap_html_in_shell(...)`
1. `<td align="left"` → `<td align="center" style="…text-align:center"`
   inside the header row. Centers both the `<img>` path and the
   text-fallback path.
2. Logo `<img>` rewrites:
   * `max-height:56px` removed entirely (no vertical squish).
   * `max-width:180px` → `max-width:200px`.
   * Added `width:auto` (CSS) so modern clients scale naturally
     while `width="200"` HTML attribute stays for MSO / Outlook.
   * Added `margin:0 auto;display:block` for aspect-safe centering.
   * `height:auto` retained.
3. `width="180"` HTML attribute → `width="200"` (kept aligned with
   the CSS cap so Outlook doesn't up-scale).

### Reach
The shell is the single wrap point for every themed email:
`quote_sent`, `invoice_reminder`, `password_reset`, `portal_invite`,
`send_to_customer`, receipts, estimate emails, etc. One fix
propagates to every downstream sender that goes through
`services.email.theming.wrap_html_in_shell`.

### Runtime verification
`GET /api/tenants/me/email-preview?template=quote_sent` (super
admin login) now returns HTML with:
* Header `<td align="center">` (verified via curl).
* Inline `text-align:center` on the header `<td>`.
* Text-header fallback path when `logo_url` is empty (current demo
  tenant has no logo configured); when a `logo_url` IS present the
  new img styles fire — locked by `test_email_theming_logo_aspect.py`.

## Tests

### New — frontend (Vitest)
`frontend/src/test/estimate-view-responsive-cards.test.jsx` — 5 tests:
1. Grouped table has `hidden sm:table`; mobile list has `sm:hidden`.
2. Each grouped card exposes a distinct-testid mobile Decline button
   AND the original desktop testid still resolves (backwards compat).
3. Clicking the mobile Decline button PATCHes the same
   `/groups/{gk}/decline` endpoint as the desktop button.
4. Itemized fallback: desktop table + mobile card list both in DOM
   with correct gates; each line renders as its own card.
5. Totals block subtotal + total-estimated-cost testids resolve
   unchanged.

### New — backend (Pytest)
`backend/tests/test_email_theming_logo_aspect.py` — 5 tests:
1. Logo `<img>` uses `height:auto` + `max-width:200px` +
   `width:auto` + `margin:0 auto` + `display:block`; `max-height:`
   is NOT present.
2. HTML `width="200"` MSO fallback is emitted.
3. Header `<td align="center">` + inline `text-align:center`.
4. Header/footer brand background + MSO VML fallback intact
   (regression guard).
5. Text-header fallback path stays intact when `logo_url` is
   `None` and stays centred by the same `<td>`.

### Full suites
* Vitest: **568 files passed | 1 skipped · 4295 passed | 34
  skipped · exit 0** (up from 4290 baseline; net +5 from new file).
* Pytest (email-related): `test_email_theming.py`,
  `test_email_theming_logo_aspect.py`, `test_email_preview.py`
  → **28 passed** in 5.74 s.
* One pre-existing failure in
  `test_business_settings.py::test_public_branding_endpoint_filters_admin_fields`
  reproduces on `main` before this dispatch and is **NOT** caused
  by this work (verified via `git stash` toggle).

## Runtime health
* `curl /` → `200`
* `curl /api/openapi.json` → `200`, **paths = 1734** (unchanged)
* Frontend hot-reload picked up JSX + CSS changes; no supervisor
  restart required.

## Out of scope (per dispatch)
* `/app/mobile/` Expo parity — delegated separately.
* Any other tables/pages beyond Quote detail + Estimate viewer.
* Any other email content changes beyond the logo styling.
