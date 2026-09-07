# Phase K79 — Grouped Customer-Facing Estimate Line Items

**Ship date**: Feb-2026
**Scope**: Estimates only (invoices out of scope per user).
**Prereq**: K71 service-category classification on line items.

## Problem

K71 required every line item to carry a `service_category_id` +
`income_category_id`. The customer never benefited from that
classification: they still received the fully-itemized `line_items[]`
table on the emailed link / portal / PDF. Long service estimates
produced walls of text.

K79 rolls those lines up into customer-friendly groups powered by the
same K71 categories, keeps the admin view fully itemized, and stays
backward-compatible for every existing estimate that pre-dates the
change.

## What ships

### 1. Schema — two new fields on `db.quotes`

| Field | Type | Default (new docs) | Default (existing docs) |
|---|---|---|---|
| `customer_group_display` | bool | `true` (on) | `false` — set by migration |
| `customer_group_descriptions` | Dict[service_category_id, str] | `{}` | preserved (typically absent) |

Both fields are plumbed on the quote document (not per-line) — group
descriptions are optional prose that appears under the group label
on customer surfaces. Cap **250 chars** per description enforced on
the frontend editor (server accepts any length; UI clamps input).

### 2. Aggregation helper — pure, unit-tested

`backend/services/quotes/customer_view.py`
- `group_lines_for_customer(quote, service_categories) -> List[group]`
  Rolls `quote.line_items[]` up by `service_category_id`. Lines
  missing a service category bucket into a single **"Other"** group
  at the tail. Group order = **first appearance** in `line_items[]`.
- `build_customer_view_payload(quote, service_categories)` — wraps
  the groups with the doc-level `subtotal`, `tax`, `discount`,
  `total`, `currency`, `amount_paid` so a surface renders "grouped
  rows + standard totals footer" in one call.

Every field in `LineItem` is inspected — **`long_description` is
NEVER read** by the helper, guaranteeing the K71 internal-notes
contract holds at the aggregation layer. The behaviour is locked by
`test_long_description_never_leaks_into_grouped_rows` in the helper
suite.

### 3. Endpoints

| Method + path | Auth | Purpose |
|---|---|---|
| `GET /api/quotes/{qid}/customer-view` | Bearer (admin+ or customer-of-doc) | Grouped payload for the admin preview + the portal-signed-in customer. |
| `GET /api/portal/quotes/via-token/customer-view` | Magic-link JWT (`?token=`) | Public share-link path. Reuses `_load_est_from_token`. |
| `GET /api/estimates/{eid}/full` | (as before) | Now **embeds** a `customer_view` block on the payload so `<EstimateView>` renders grouped rows without a second RTT. |
| `GET /api/estimates/{eid}/pdf` | (as before) | Now forks based on `customer_group_display`. Customer PDF renders grouped rows. Admin fully-itemized "Internal PDF" is reachable via `?internal=1`. |
| `POST /api/quotes` | (as before) | Now accepts + defaults `customer_group_display=true` for new quotes. |
| `PUT /api/quotes/{qid}` | (as before) | Now accepts + persists both fields. |

### 4. Admin editor surface — `<K79CustomerViewSection>`

Renders on `QuoteInvoiceDetail` for **quotes only** (invoices keep the
itemized customer view — grouped rollup on invoices is future scope),
gated to `isStaff`. Contains:

- **Checkbox** — "Show grouped totals to customer".
  Wraps `customer_group_display`. Optimistic UI, rolled back on save
  error. Persists via `PUT /quotes/{id}` on every toggle.
- **Description editor** — one row per unique
  `service_category_id` present in `doc.line_items`. Hidden when
  the toggle is off. 250-char cap with counter. Per-row Save button
  PUTs the FULL `customer_group_descriptions` dict (server merge is
  a straight replace).
- **Preview customer view** button — opens `<K79CustomerViewPreview>`
  which renders the grouped table exactly as the customer will see
  it, using **local pending state** (so admin previews the WIP text
  before hitting Save).

### 5. Customer-facing rendering

- **`<EstimateView>`** — new fork: when `as_customer && customer_view
  && customer_view.customer_group_display`, renders a two-column
  `[Service | Subtotal]` table + optional group description line.
  Admin-role callers keep the fully-itemized 6-column table.
- **PDF** — three modes:
  1. Admin `?internal=1` → 6-column full itemization.
  2. Customer + `customer_group_display=true` → 3-column grouped
     ("Service | Description | Subtotal").
  3. Customer + `customer_group_display=false` → 4-column customer
     itemized fallback (preserves the pre-K79 shape).
- **Portal quote view** reuses `<EstimateView>` and therefore picks
  up the grouped rendering automatically.

### 6. Backward-compat migration

`backend/scripts/k79_customer_group_display_migration.py`

- Idempotent — filter is
  `{$or: [{customer_group_display: {$exists: false}}, {customer_group_display: null}]}`.
- Sets `customer_group_display=false` on every match.
- Writes an audit doc to `db.migration_runs` with
  `{ migration, matched, modified, started_at, finished_at, status }`.
- Re-run reports `status: "noop"` when nothing left to backfill.

**Migration run on preview**: `matched=124, modified=124, status=ok`
before this run; a follow-up run reported `status: noop`. All 148
quotes in the tenant now carry an explicit flag.

## Long-description contract

**Locked in three places** to guarantee the K71 internal-notes rule
holds under every customer surface:

1. `group_lines_for_customer` never reads `long_description`.
2. `test_long_description_never_leaks_into_grouped_rows` in
   `test_k79_group_lines_helper.py` — asserts the secret string is
   absent from every value on every returned group.
3. `test_customer_view_never_leaks_long_description` in the endpoint
   test — asserts the secret string is absent from the raw JSON
   response body.
4. Frontend Vitest — `k79-customer-view-preview.test.jsx` renders
   with a `long_description` string on a line and asserts the modal
   never surfaces it (in both grouped AND itemized fallback modes).

## Tests

### Backend pytest

| File | Cases | Pass |
|---|---|---|
| `test_k79_group_lines_helper.py` | 12 | ✅ |
| `test_k79_customer_view_endpoint.py` | 9 | ✅ |
| `test_k79_migration.py` | 1 | ✅ |
| K71 regression (`test_k71_line_item_router_api.py`, `test_k71_line_item_edit_categories.py`) | 23 | ✅ |

**K79 total: 22 backend / K71 regression: 23 — all green.**

### Frontend vitest

| File | Cases | Pass |
|---|---|---|
| `test/k79-customer-group-toggle.test.jsx` | 8 | ✅ |
| `test/k79-customer-view-preview.test.jsx` | 8 | ✅ |

**Full frontend suite**: **479 files pass · 1 skipped · 3790 tests
pass · 34 skipped (Hygiene B untouched).**

Delta from K80.a: `3790 − 3774 = +16` — matches K79 additions exactly.

## Discoverability preserved from K80.a

K80.a shipped `Edit invoice (advanced)` gated to non-draft
invoices. K79 additions are on quotes/estimates only — K80.a's
invoice logic is untouched.

## Screenshots

- `/tmp/k79_1_admin_section.png` — customer-view section with toggle
  ON, "Pool" + "Landscaping" description editors, Preview button.
  K80.a "+ Add line" + trash icons visible below on line-items table
  (proves K80.a is preserved).
- `/tmp/k79_1b_desc_typed.png` — same, with
  `Weekly service package with chemistry balance.` typed into Pool
  description (46/250 counter).
- `/tmp/k79_2_preview_modal.png` — preview modal open, showing
  "GROUPED LAYOUT (ON)" mode label, Pool row $220.00 with description
  underneath (WIP text — not yet saved), Landscaping row $200.00,
  totals footer $420.00.

## Files touched

| File | Nature |
|---|---|
| `backend/services/quotes/__init__.py` | NEW — package init. |
| `backend/services/quotes/customer_view.py` | NEW — pure aggregation helper (`group_lines_for_customer`, `build_customer_view_payload`). |
| `backend/scripts/k79_customer_group_display_migration.py` | NEW — idempotent backfill with audit-doc write. |
| `backend/models.py` | +`customer_group_display`, `customer_group_descriptions` on `QuoteIn` + `QuoteUpdate`. |
| `backend/routers/quotes.py` | `create_quote` seeds the two new fields with a `True` default. |
| `backend/routers/estimate_viewer.py` | +`GET /quotes/{qid}/customer-view`, +`GET /portal/quotes/via-token/customer-view`, `_build_payload` embeds `customer_view` block, `estimate_pdf` forks 3 modes on grouped/itemized/internal. |
| `backend/tests/test_k79_group_lines_helper.py` | NEW — 12 cases (grouping, subtotals, "Other" bucket, currency, empty, long_description contract). |
| `backend/tests/test_k79_customer_view_endpoint.py` | NEW — 9 HTTP round-trip cases (defaults, grouping, long_description scrub, flag persistence, 404, auth, `/full` embed, PUT accepts new fields, per-group descriptions). |
| `backend/tests/test_k79_migration.py` | NEW — 1 case: backfill missing+null, leave True alone, idempotent, audit doc. |
| `frontend/src/components/quotes/K79CustomerViewSection.jsx` | NEW — toggle + per-category description editor + preview trigger. |
| `frontend/src/components/quotes/K79CustomerViewPreview.jsx` | NEW — client-side grouped preview modal with WIP state support. |
| `frontend/src/components/EstimateView.jsx` | Grouped-rendering fork on `showGrouped = as_customer && customer_view?.customer_group_display`. |
| `frontend/src/components/EstimateView.css` | +`.ev-group-desc` muted-text style for group description line. |
| `frontend/src/pages/quotes/QuoteInvoiceDetail.jsx` | Injects `<K79CustomerViewSection>` on quotes only + `isStaff`. |
| `frontend/src/test/k79-customer-group-toggle.test.jsx` | NEW — 8 Vitest cases. |
| `frontend/src/test/k79-customer-view-preview.test.jsx` | NEW — 8 Vitest cases. |

## Guardrails held

- Admin view stays fully itemized (`?internal=1` PDF + editor unchanged).
- `long_description` never surfaces on customer surfaces —
  contract-tested at 4 layers.
- Backward compat: 124 existing quotes migrated to `false`, keep
  itemized customer view until admin toggles on.
- No hardcoded hex regressions. Muted description style uses
  `#6B7280` (existing muted-text convention). Modal chrome uses
  slate-900 backdrop matching existing modal patterns.
- No theme regressions. Zero `emoji` characters.
- No changes to I1.5 / I1.7.a / I1.7.b / K80.a code.
- All **34 Hygiene B skips untouched**. Zero new quarantines.
- K80.a `+ Add line` + trash icons still render and function on the
  same page (verified in screenshot 1).

## Next in queue (unchanged)

- **K80.b** — server-side status gate on `PUT /api/quotes/{id}`
  mirroring the PATCH triad (`terminal→block`, `sent→confirm`,
  `paid→typed invoice number`). Product decision needed on whether
  `sent` estimates should stay editable.
- **I1.7.c** — AI BYO providers + Maps + Calendars.
