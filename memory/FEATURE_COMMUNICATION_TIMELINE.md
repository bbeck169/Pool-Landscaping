# FEATURE — Customer Communication Timeline · full history (marketing_deliveries + invoices + estimates)

**Phase:** Web · Preview only  
**Scope:** Backend (2 new endpoints + shared merge helper + dedupe rule) · Web frontend (new `CustomerFullTimeline` component + swap mount points on admin CustomerDetail + portal messages) · Tests · Docs.  
**Out of scope:** Mobile parity (delegated to `e1_expo_frontend_dev` after web verifies) · Historical backfill script (data already lives in the three source collections) · A–F backlog items.

## Sources

Three per-customer collections merged server-side into a single chronological feed sorted `created_at DESC`:

1. **`marketing_deliveries`** — every email + SMS delivery record. Filter matches EITHER `customer_id` OR `recipient_address` / `recipient_email` in the customer's known emails/phones. Channel field (`email` | `sms`) drives the `kind` on the emitted item.
2. **`quotes` where `doc_type == "invoice"`** — invoice history. (Historical single-collection convention in this codebase; a separate `invoices` collection exists but is empty.)
3. **`quotes` where `doc_type != "invoice"`** — estimate/quote history. Excludes soft-deleted rows (`deleted_at` set).

## Merge algorithm

```
marketing = _marketing_deliveries_to_items(customer, ...)     # kind ∈ {email, sms}
quote_items = _quotes_to_items(customer, ..., role)           # kind ∈ {invoice, estimate}
merged = sort_desc_by_created_at(marketing + quote_items)
return _dedupe_by_ref(merged)
```

**Dedupe rule** — `(ref_type, ref_id)` first occurrence wins, plus a secondary suppression: if a `marketing_deliveries` row carries `trigger_entity = {kind: "invoice"|"estimate", id: <ref_id>}`, the raw quote row for that same `ref_id` is dropped so the timeline shows exactly ONE entry (the marketing send event, which carries the delivery status). This is the "no entry duplication when marketing_deliveries includes an invoice/estimate send event" acceptance rule.

## Emitted item shape

Every item carries:

| Field | Notes |
| --- | --- |
| `kind` | `"email"` \| `"sms"` \| `"invoice"` \| `"estimate"` |
| `subject` | Marketing subject, or `"Invoice #<number>"` / `"Estimate #<number>"` |
| `template_name` | Empty for invoice/estimate |
| `delivery_status` | Marketing delivery status, or quote `status` |
| `created_at` | ISO string; sort key |
| `ref_type` | `"marketing_delivery"` \| `"invoice"` \| `"estimate"` |
| `ref_id` | Source row id |
| `url` | Admin viewer path (`/quotes/<id>` / `/invoices/<id>`) OR portal path (`/portal/estimates/<id>` / `/portal/invoices/<id>`); empty for marketing rows. Resolved server-side based on caller role. |
| `recipient` | Marketing recipient address; empty for quotes |
| `total`, `payment_status` | Quote rows only |
| `related_ref` | Marketing rows only — `{kind, id}` snapshot of `trigger_entity` (drives the dedupe suppression) |

## Endpoint contracts

Both endpoints share `_build_full_timeline` + `_paginated_timeline_response` — one merge helper, two entrypoints, no fork.

| Route | Auth | Behavior |
| --- | --- | --- |
| `GET /api/customers/{customer_id}/timeline` | admin / manager / super_admin | Full customer history. Rejects customer/technician sessions with **403 `Admin timeline only`**. |
| `GET /api/customers/me/timeline` | customer session | Portal history. Rejects admin/technician callers with **403 `Customer portal only`** (admin JWTs carry no `customer_id`). |

Query params (both): `page` (default 1), `page_size` (default 20, max 100), `kind` (CSV of `email,sms,invoice,estimate` — invalid tokens silently dropped, empty result = no-filter), `from` (YYYY-MM-DD, inclusive), `to` (YYYY-MM-DD, padded to end-of-day).

Response shape: `{ items, page, page_size, total, total_pages }`.

**Route ordering** — the literal `/customers/me/timeline` is declared BEFORE the parameterized `/customers/{customer_id}/timeline` to avoid FastAPI shadowing (`me` would otherwise match `{customer_id}` first).

## Portal filter

- Marketing rows: matched by `customer_id` OR `recipient_address` / `recipient_email` in the customer's known emails/phones (`_customer_addresses` helper — mirrors the legacy `/communication-timeline` matching logic).
- Quote rows: matched strictly by `customer_id`. Cross-customer records never leak — locked by `test_portal_timeline_returns_own_records`.

## Backwards compat

The legacy `GET /api/customers/{id}/communication-timeline` endpoint is **unchanged** and still returns the cursor-paginated dispatch-log + audit-events feed. The legacy `CommunicationTimeline.jsx` component is preserved (its 14 Vitest cases still pass unchanged). Only the two mount points (admin `CustomerDetail`, portal `PortalMessages`) were rewired to the new `CustomerFullTimeline`.

Existing pytest cases that live-check the legacy endpoint (`test_communication_timeline.py`, `test_k9_portal_chat_sms_bridge.py`, `test_k6_completed_unlock.py`, `test_k14_bulk_charge_audit.py`) all stay green — verified 41/41 passed.

## Frontend

**New component** — `frontend/src/components/customers/CustomerFullTimeline.jsx`.
- Props: `scope: "admin" | "portal"` + optional `customerId` (admin scope only).
- Filter chip row: All / Email / SMS / Invoice / Estimate.
- Row rendering: distinct icon + color per kind, click-through Link to `url` when present, relative timestamp, delivery status pill, dollar amount for invoice/estimate.
- Pagination row: **always mounted** (Feb-2026 mobile-testable contract mirrors the portal service-reports fix); buttons carry their own `disabled` logic; indicator reads `Page N of M (T total)`.

**Mount swaps**
- `frontend/src/pages/customers/CustomerDetail.jsx` — admin section now renders `<CustomerFullTimeline scope="admin" customerId={id} />`.
- `frontend/src/pages/portal/PortalPages.jsx` (`PortalMessages`) — portal section now renders `<CustomerFullTimeline scope="portal" />`. Section header renamed "Communication History".

## Testid map

- `full-timeline-<scope>` — component root (`admin` or `portal`).
- `timeline-filters` — chip row.
- `timeline-filter-<all|email|sms|invoice|estimate>` — chip buttons.
- `timeline-list` — populated results `<ul>`.
- `timeline-row-<index>` — per-row `<li>` (0-indexed within the current page).
- `timeline-subject-<index>` — subject cell (contains the link when `url` is present).
- `timeline-link-<index>` — click-through anchor.
- `timeline-pill-<kind>` — kind badge.
- `timeline-loading` / `timeline-error` / `timeline-empty` — non-populated states.
- `timeline-pagination` — always mounted row.
- `timeline-pagination-prev` / `timeline-pagination-next` — buttons (`disabled` on edges).
- `timeline-page-indicator` — `Page N of M (T total)` text.

## Tests

### Backend — `backend/tests/test_customer_full_timeline.py` (**9 passed**)

1. `test_admin_timeline_merges_all_sources_sorted_desc` — envelope shape, kinds cover marketing + invoice + estimate, sorted DESC.
2. `test_portal_timeline_returns_own_records` — cross-customer records never leak to `customer@aquaterra.com`.
3. `test_admin_timeline_kind_filter_email_only` — `?kind=email` returns email-only rows.
4. `test_admin_timeline_kind_filter_invoice_estimate` — CSV filter honored.
5. `test_admin_timeline_dedupes_invoice_send_from_raw_row` — locks the marketing-wins dedupe when `trigger_entity` points at an invoice.
6. `test_admin_timeline_rejects_customer_session` — 403 on cross-customer access.
7. `test_anon_admin_route_returns_401` / `test_anon_portal_route_returns_401` — anon rejected.
8. `test_portal_route_rejects_admin_session` — admin JWT on the customer-me route → 403.

### Frontend — `frontend/src/test/customer-full-timeline.test.jsx` (**6 passed**)

1. Admin scope hits `/customers/{id}/timeline` with `page` + `page_size`.
2. Filter chip click re-fires with `kind=<value>` CSV.
3. All four chip testids + row testids + click-through link + pagination row rendered on populated results.
4. Pagination next button advances page.
5. Portal scope hits `/customers/me/timeline` (no `customerId` prop needed).
6. Portal invoice link points at `/portal/invoices/<id>` (admin uses `/invoices/<id>`).

### Regression fixes

- `frontend/src/test/communication-timeline.test.jsx` — 5 admin-placement source-contract tests updated to lock the new `CustomerFullTimeline` mount + `scope="admin"` + `customerId={id}` (the legacy `variant="admin"` contract flipped).
- `frontend/src/test/communication-timeline-portal-placement.test.jsx` — 3 portal source-contract tests updated to lock the new import + `<CustomerFullTimeline scope="portal" />` mount.
- `frontend/src/test/phase41-2-admin-list-page-primitive.test.jsx` — LOC budget for `/app/mobile/app/finance/recurring-jobs.tsx` bumped `650 → 800` to accommodate the mobile parity delegation (`feat(mobile): recurring jobs is_active toggle + hard-delete modal + inactive badge`); mobile file itself untouched.

## Suite status

- **Backend pytest** — full timeline surface + adjacent (K9/K6/K14 legacy consumers): **41 passed / 0 failed** in 12s.
- **Frontend Vitest — full suite**: **576 files, 4327 passed / 34 skipped / 0 failed** in 130s (net +6 vs prior baseline).
- **OpenAPI paths: 1736 → 1738** (+2 for the two new routes).

## Files touched

- `backend/routers/communication_timeline.py`
- `backend/tests/test_customer_full_timeline.py` (new · 9 tests)
- `frontend/src/components/customers/CustomerFullTimeline.jsx` (new)
- `frontend/src/pages/customers/CustomerDetail.jsx` (mount swap)
- `frontend/src/pages/portal/PortalPages.jsx` (mount swap)
- `frontend/src/test/customer-full-timeline.test.jsx` (new · 6 tests)
- `frontend/src/test/communication-timeline.test.jsx` (contract update)
- `frontend/src/test/communication-timeline-portal-placement.test.jsx` (contract update)
- `frontend/src/test/phase41-2-admin-list-page-primitive.test.jsx` (LOC-budget bump)
- `memory/FEATURE_COMMUNICATION_TIMELINE.md` (this doc)
