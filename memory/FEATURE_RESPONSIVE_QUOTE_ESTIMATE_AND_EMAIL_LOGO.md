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


---

## Feb-2026 · Follow-up (K71 admin surface + route map)

### Gap 1 — Admin `/quotes/:id` responsive fix (SHIPPED)

Prior ship only touched the customer-facing `EstimateView.jsx`.
Admin `/quotes/:id` and `/invoices/:id` route through
`QuoteInvoiceDetail.jsx` → `K71LineItemsEditor.jsx`, which still
rendered a 5-column table with intrinsic minimum widths >
375 px. Tester saw `scrollWidth = 415` at 375 × 812.

Follow-up changes:

| File | Change | LOC delta |
| ---- | ------ | --------- |
| `frontend/src/components/quotes/K71LineItemsEditor.jsx` | Added `MobileCard` (read-mode stacked card, distinct `-mobile-` testids); gated `<table>` with `hidden sm:table` in read mode; parameterized `LegacyBadge` testid to disambiguate desktop/mobile duplicates. When ANY row is in edit mode (`editIndex !== null`) the table renders unconditionally + the mobile list unmounts, so the `<tr>`-based `EditableRow` remains the sole editing surface across viewports (existing edit UX preserved verbatim). | +100 |
| `frontend/src/pages/quotes/QuoteInvoiceDetail.jsx` | Wrapped the two secondary admin tables (`internal-margin-table`, `admin-declined-lines-table`) in `overflow-x-auto` scroll containers with a `minWidth` on the `<table>` — page-level scroll stays at 375 px; the wide dense-numeric tables scroll internally only. | +4 / −0 |
| `frontend/src/test/k71-line-items-responsive-cards.test.jsx` (NEW) | 5 Vitest tests — table gate + card list + edit flow round-trip + legacy-badge testid disambiguation + delete/undo. | +139 |

Runtime metrics captured against
`/quotes/ba9fde33-5717-4c0f-b7a5-a1c17a58700f` (invoice-shaped
doc — same component tree):

| Viewport | `scrollWidth` | `clientWidth` | K71 `<table>` | K71 cards |
| -------- | ------------- | ------------- | ------------- | --------- |
| 375 × 812 | **375** | 375 | `display: none` | 3 cards rendered |
| 1280 × 800 | **1280** | 1280 | `display: table` | `display: none` |

No horizontal scroll at 375 px. Desktop layout unchanged.

`QuoteInvoiceDetail.jsx` outer wrapper is
`<div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6">` —
no fixed pixel widths / hardcoded `overflow-x: auto` on the main
container. `min-w-0` in the header-left flex column is a
flex-shrink override (correct) and was left in place.

### Gap 2 — Route map & magic-link recipe

Which surfaces render which components:

| Route | Component | Auth | Notes |
| ----- | --------- | ---- | ----- |
| `/quotes/:id` | `pages/quotes/QuoteInvoiceDetail` → `components/quotes/K71LineItemsEditor` | staff (admin / super_admin) | `docType="quote"`; K71 now stacked-card < sm. |
| `/invoices/:id` | Same as above with `docType="invoice"` | staff | Shares K71 responsive treatment. |
| `/portal/quotes/via-token?token=…` | `components/EstimateView` (mounted by public route in `App.js:650+`) | **public magic-link (no auth)** | Stacked-card < sm shipped in the prior slice. |
| `/portal/estimates/via-token?token=…` | Same as above (deprecated alias). | public magic-link | Same responsive treatment. |
| `/e/estimate?token=…` | `EstimateView` (customer email CTA landing) | public magic-link | Same responsive treatment. |
| `/portal/*` (customer login) | `pages/PortalPages.jsx` → `EstimateView` | customer session | Same responsive treatment. |

Magic-link mint recipe (for `e1_tester` to reach EstimateView
directly without touching the admin UI):

```bash
API=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d '=' -f2)

# 1. Log in as super admin.
TOK=$(curl -s -X POST "$API/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"super@aquaterra.com","password":"password123"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# 2. Pick a quote id (any recent one — response shape varies by
#    build, so parse defensively).
QID=$(curl -s -H "Authorization: Bearer $TOK" "$API/api/quotes?limit=5" \
  | python3 -c 'import sys,json
d=json.load(sys.stdin)
items = d if isinstance(d, list) else d.get("items") or d.get("quotes") or []
print(items[0]["id"] if items else "")')

# 3. Mint the magic-link URL (backend router:
#    ``estimate_viewer.py`` → GET /api/quotes/{qid}/magic-link).
curl -s -H "Authorization: Bearer $TOK" \
  "$API/api/quotes/$QID/magic-link" \
  | python3 -m json.tool
# → response includes:
#   { "url": "…/portal/quotes/via-token?token=<jwt>", "expires_at": "…" }
```

Load that `url` at viewport 375 × 812 to hit `EstimateView` in
its customer-facing mode. No auth headers required — the JWT in
the query string is the sole credential.

For admin-side responsive verification, load
`/quotes/<qid>` or `/invoices/<qid>` directly with a
super-admin session (seed the token via
`window.localStorage.setItem('token', …)` and
`localStorage.setItem('user', JSON.stringify(user))` — see
`frontend/src/auth.jsx` for the storage keys).

### Test-suite status after follow-up

* Vitest: **569 files passed | 1 skipped · 4300 tests passed |
  34 skipped · exit 0** (+5 from `k71-line-items-responsive-cards.test.jsx`).
* K71 legacy suite unchanged: `k71-line-items-editor.test.jsx`
  (18 tests) + `pb2-line-item-overrides.test.jsx` (5 tests) all
  still green.
* Pytest (email) unchanged from prior slice.
* Runtime check: `curl /` → 200, `curl /api/openapi.json` → 200,
  **paths = 1734** unchanged.
