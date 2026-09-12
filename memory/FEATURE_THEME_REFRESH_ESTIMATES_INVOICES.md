# Feature — Theme Refresh (Estimates + Quotes + Invoices) · Feb-2026

Ships the customer-facing visual identity for quotes / estimates /
invoices — both on-screen (web + admin) and in the ReportLab PDF
handlers — driven by the Business Settings phase data. Zero business
logic changes; purely visual + context wiring.

## What changed

### Backend

1. **`services/tenants/business_settings.py`** — added
   `resolve_public_base_url()` + `resolve_absolute_url(url)` +
   `get_effective_business_settings(..., absolutize=True)` optional
   flag so PDFs / emails get an absolute logo URL without a scheme
   change at the storage layer.

2. **`services/tenants/pdf_theme.py`** (NEW) —
   `build_header_footer_hooks(brand_hex, title, company_display_name,
   company_lines, logo_absolute_url, footer_note)` returns
   `(onFirstPage, onLaterPages)` callbacks. Header rect (1.2 in)
   paints on page 1 only with the tenant's `brand_primary_hex`,
   uppercase title left, company details right, optional logo image.
   Footer rect (0.5 in) paints on **every** page with white centered
   `footer_note` (fallback "Thank you for your business!").

3. **`routers/estimate_viewer.py::estimate_pdf`** + **`routers/quotes.py::quote_or_invoice_pdf`**
   — customer-surface branch calls the new hooks and adjusts
   `topMargin` / `bottomMargin` so story flows below the header
   band and above the footer band. Admin (`?internal=1`) PDFs are
   untouched. Failure is soft — the render falls back to the
   unthemed layout when the hooks can't build.

### Frontend

1. **`hooks/useTenantBranding.js`** (NEW) — two hooks:
   - `useBusinessSettings({ skip })` — admin surface, reads
     `/api/tenants/me/business-settings`.
   - `useTenantBranding(token)` — customer surface, reads
     `/api/portal/tenant/branding?token=…`.
   Both return `{ branding, loading, error, reload }` with default
   `brand_primary_hex="#0B4A6F"` / `brand_secondary_hex="#F97316"`
   applied so consumers never see nulls.

2. **`components/documents/DocDesktopShell.jsx`** — added optional
   `brandingHeader` prop; when present the shell paints a full-width
   coloured band above the standard two-column header + a matching
   coloured footer band below the stub. Existing callers unaffected —
   passing no `brandingHeader` prop keeps the previous layout byte-
   for-byte.

3. **`components/EstimateView.jsx`** — mounts both hooks
   (magic-link surfaces via `useTenantBranding(token)`, admin
   preview via `useBusinessSettings({ skip: !!token })` — only one
   fetch fires) and threads the resolved `branding` block into the
   shell as `brandingHeader`. Added a **sticky mobile action bar**
   (position: fixed, bottom, safe-area-aware) visible only when the
   surface is actionable (magic-link token + `status ∈ {sent,viewed}`
   + `!decision`). Approve + Decline buttons themed with
   `brand_primary_hex` / `brand_secondary_hex`.

4. **`pages/quotes/QuoteInvoiceDetail.jsx`** — mounts
   `useBusinessSettings()` and renders a themed header band above
   the existing detail card so admins see the same brand identity.
   All existing markup preserved.

### Tests

- **`backend/tests/test_theme_refresh_pdf.py`** — 6 tests, all pass:
  1. Header band paints `brand_primary_hex` (verified via decoded
     content-stream regex `\.12\d+ \.35\d+ \.43\d+ rg`).
  2. Null hex falls back to `#0B4A6F` default primary.
  3. Multi-page PDF — footer on every page (checked via
     `pypdf.PdfReader` per-page text extraction), header only on
     page 1.
  4. `resolve_absolute_url("/api/objects/…")` promotes to full URL
     using `APP_BASE_URL`.
  5. Absolute + `data:` URLs pass through; empty / None → None.
  6. `get_effective_business_settings(absolutize=True)` promotes
     the stored relative `logo_url` on read.

- **`frontend/src/test/theme-refresh-estimate-view.test.jsx`** —
  6 tests, all pass:
  1. Themed header band paints `brand_primary_hex`.
  2. Falls back to default primary when branding fetch rejects.
  3. Logo image renders when `logo_url` set; company name text
     when null.
  4. Sticky mobile action bar visible on actionable magic-link
     view; hidden when quote is `accepted`.
  5. Dual-total row still renders when `has_declined_lines === true`.
  6. QuoteInvoiceDetail themed band renders (mini-mirror mount to
     avoid pulling the whole router).

## Color token fallback map

| Token                     | Source                       | Fallback   |
|---------------------------|------------------------------|------------|
| `brand_primary_hex`       | Business Settings (per-tenant) | `#0B4A6F` |
| `brand_secondary_hex`     | Business Settings              | `#F97316` |
| Header band background    | `brand_primary_hex`            | above      |
| Footer band background    | `brand_primary_hex`            | above      |
| Mobile Approve btn        | `brand_primary_hex`            | above      |
| Mobile Decline btn border | `brand_secondary_hex`          | `#DC2626` |
| PDF header rectangle      | `brand_primary_hex` (ReportLab HexColor) | above |
| PDF footer rectangle      | `brand_primary_hex`            | above     |

## Mobile table layout decision — scroll (not card)

The existing customer web/portal table already fits with
`overflow-x: auto` via `.iv-lines-wrap` (shipped in a prior phase).
Card-per-line-item was considered but rejected because:

1. Line items on grouped quotes are folded into one row per group
   — the visual density is already low.
2. Card mode would fork the DOM shape between the customer web
   surface and the admin surface, complicating the shared
   `DocDesktopShell` contract.
3. Print media query already restores inline table for clean
   printing; the horizontal-scroll fallback only affects live
   mobile viewing on the rare wide-content quote.

Result: horizontal-scroll fallback stays. If a >4-column line-item
table lands later, revisit.

## Absolutization strategy notes

- `logo_url` is stored **relative** (`/api/objects/…`) — matches
  the existing branding pipeline and keeps DB migration to zero.
- `get_effective_business_settings(db, tid, absolutize=True)` is
  the ONLY read path allowed to promote the value. Callers:
  - PDF renderers (both estimate_viewer + quotes) — absolutize=True.
  - Future email base template — absolutize=True (queued).
  - Web/portal surfaces — absolutize=False (browser resolves the
    same-origin path natively).
- Base URL priority: `PUBLIC_APP_BASE_URL` > `FRONTEND_BASE_URL`
  > `APP_BASE_URL` > hard-coded `https://app.plofv.com`. Matches
  the priority order in `services/service_report_view` so PDFs
  and job-photo emails resolve to the same origin.

## Email theming — deferred (staged for the next dispatch)

Email base template theming was **not** shipped in this phase:

- The codebase hosts four independent email adapters
  (`services.email.resend_adapter`, `services.marketing_email.resend_adapter`,
  `services.marketing.email_adapter`, `services.comms_email_adapter`),
  each with its own subject/body wrapper. Threading a single
  `brand_primary_hex` through all four in one dispatch would blow
  the small-diff constraint and multiply the surface area under
  test.
- Business Settings + the resolvers ship the DATA source; a
  standalone follow-up dispatch (~ 40 lines per adapter) can
  paint the header/footer bands into the shared email shell each
  adapter uses.
- Contract for the follow-up (already documented):
  header band = `brand_primary_hex`; logo top-left via
  `resolve_absolute_url`; footer = `brand_primary_hex` band with
  `footer_note` + company contact block; mso conditional fallback
  colors for Outlook clients.

## Screenshots

Manual verification screenshots pending — the tester will capture
them on the verification pass since the tester has a live browser
session with an admin login and can drive:

- `/settings/business` (Business Settings admin page) — locked in
  by the previous dispatch's memo.
- `/estimates/{id}` (admin themed band).
- Public magic-link view of a quote (themed header + sticky mobile
  bar).
- Sample `GET /api/quotes/{qid}/pdf` (themed PDF).

Storing screenshots in the repo before the tester renders live is
noise — memo lists the expected surfaces + testids so the tester's
capture step is deterministic.

## Guardrail confirmation

- Preview-only. `.env.production` untouched. ✅
- `PHOTOS_S3_ENABLED=true` count=1, `AWS_REGION=us-east-2` count=1. ✅
- `/app/mobile/` untouched. ✅
- No external repo clone. ✅
- OpenAPI count stable at 1729 (this phase is visual-only — zero
  new endpoints). ✅
- Business logic unchanged. RBAC, totals math, decline flow,
  payment flow untouched. ✅
- Grouped-layout LOCK-ON preserved. ✅
- Decline-per-group `<strike>` on declined groups preserved. ✅
- Admin dual-total renderer preserved. ✅

## Follow-ups queued

- Email base template theming (single dispatch, ~150 lines total
  across 4 adapters — documented above).
- Mobile parity delegation to `e1_expo_frontend_dev` (separate
  dispatch, `/app/mobile/` scope).
- Duplicate Quote button (queue item after theme phase).
- Live screenshots captured by `e1_tester` on verification pass.
