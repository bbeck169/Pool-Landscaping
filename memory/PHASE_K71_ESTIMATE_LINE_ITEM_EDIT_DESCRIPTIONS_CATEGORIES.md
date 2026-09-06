# Phase K71 · Feb-2026 — Estimate Line Item Edit + Description + Service/Income Categories

## Scope Recap
1. Column rename: "Description" → "Item" on `/quotes/{quote_id}`; bold item name + secondary muted description line.
2. Inline pencil edit on each draft line item with Item / Qty / Unit Price / Description (500-char) / Service Category / Income Category + Save/Cancel + Esc/Enter shortcuts.
3. New optional `long_description` field (multi-line, ≤500 chars). Legacy lines without it hide the secondary line. Hidden on PDF/portal.
4. Service + Income categories are required dropdowns on NEW/edited line items. Legacy lines (neither field present) are grandfathered.
5. Save/Send gating: block send/approve/convert when a K71-touched line is missing categories.
6. Convert-to-invoice parity: quote line items now carry through to `job.line_items[]` and thence to the auto-invoice.
7. Reporting: additional K71 fields feed R0.1 Revenue-by-Service-Type report.

## Backend Changes
- `models.py` — `LineItem` now carries `long_description: Optional[str]` and `service_category_id: Optional[str]` (income already existed).
- `routers/service_categories.py` — `_DEFAULTS` extended with K71 seed names (Equipment Install, Chemical Treatment, Inspection, Landscape, Hardscape, Lighting, Other). Additive-merge behaviour unchanged.
- `routers/income_categories.py`:
  * `_DEFAULTS` extended with K71 seed names (Service Revenue, Product Sales, Recurring Maintenance, One-time Project, Warranty Work, Labor Income, Materials, Other Income).
  * `ensure_defaults_for_tenant` switched from "only if count == 0" to case-insensitive additive merge (mirrors service_categories).
  * NEW `validate_line_item_k71_categories(tenant_id, line_items)` — two-taxonomy validation for K71-touched lines; legacy items grandfathered.
  * NEW `check_line_items_k71_gaps(line_items)` — read-side helper returning indices of K71-touched lines missing either category.
- `routers/quotes.py`:
  * POST `/quotes` — invokes K71 validator on every line.
  * PUT `/quotes/{qid}` — invokes K71 validator on every touched line.
  * PUT `/quotes/{qid}/status` — blocks transitions into sent/accepted/approved when K71 gaps exist.
  * POST `/quotes/{qid}/decision` — blocks customer approval when K71 gaps exist.
- `routers/invoice_edit.py`:
  * `_validate_line_items` accepts + validates 500-char cap on `long_description`; K71 fields carried through untouched.
  * PATCH `/quotes/{invoice_id}` runs K71 validator alongside existing legacy income validator.
- `routers/billing.py`:
  * `POST /quotes/{qid}/convert-to-job` gate blocks conversion when K71 gaps exist and copies quote line items (including K71 fields) into `job.line_items[]`.
- `services/auto_invoice.py`:
  * `_build_line_items` now preserves `long_description`, `service_category_id`, `income_category_id` when the auto-invoice fires from a job's line items.

## Frontend Changes
- NEW `components/quotes/K71LineItemsEditor.jsx` — the line-items table:
  * Column header renamed to "Item".
  * Bold description + secondary muted `long_description` line.
  * `Uncategorized` badge on legacy items (neither K71 field present).
  * Pencil icon on each row (draft docs only, admin/super only) → inline form with Item / Qty / Unit / Description textarea / Service picker / Income picker + Save/Cancel.
  * Esc = Cancel, Enter = Save (Shift+Enter allowed inside textarea).
  * Top red banner listing gap count when any K71-touched line is missing a category.
- `pages/quotes/QuoteInvoiceDetail.jsx` — replaced the static line-items table with the new component; `PUT /quotes/{id}` is called on save.

## Settings UI
Both `/settings/service-categories` and `/settings/income-categories` already exist and are wired into `App.js`. Admin CRUD works with the existing backend routers plus the K71 seed additions.

## PDF / Customer Portal
`long_description`, `service_category_id`, `income_category_id` are internal-only — they are never rendered by the PDF generator (`quote_or_invoice_pdf`) or the customer-portal viewer. No changes required to those surfaces.

## Tests
- Backend: `backend/tests/test_k71_line_item_edit_categories.py` — 12 pytest cases: additive seed (both taxonomies), K71 validator (legacy pass, missing service, missing income, invalid ids, valid pair), gap detection, LineItem model default grandfathering, invoice_edit 500-char cap.
- Frontend: `frontend/src/test/k71-line-items-editor.test.jsx` — 8 vitest cases: column rename, badge, secondary description line, gap banner, pencil gate, inline form contents, missing-category save block, cancel flow.

## Backlog Notes
- Bulk recategorize UI for legacy line items — deferred to K71 P2 follow-up per user directive.
- R0.1 Revenue-by-Service-Type report — will read directly from the new `line_items[].service_category_id` field once populated.
