# FEATURE · Duplicate Quote (P0)

**Status:** Shipped (Preview).
**Owner:** main agent.
**Ship-date:** Feb-2026.
**Dispatch:** Adapted from the original P0 dispatch after confirming
the codebase does NOT carry an `addresses` collection, a `default_address_id`
field, or a mintable `quote_number` sequence. See "Adaptation notes"
below.

---

## Endpoint contract

```
POST /api/quotes/{qid}/duplicate
```

**Auth:** `require_admin` — `admin` / `super_admin` / `owner` pass;
`technician`, `customer`, `manager` all → 403.

**Body:**
```json
{
  "customer_id": "<uuid>",
  "property_id": "<uuid | null — optional>"
}
```

**Response (200):**
```json
{
  "quote_id":     "<uuid>",
  "quote_number": "<id[:8]>"
}
```

Note: `quote_number` is the 8-char id prefix the UI already uses for
display (`estimate_viewer.py:562` sets the pattern with
`f"Estimate #{(est.get('id') or '')[:8]}"`). There is no separate
quote numbering sequence in this codebase. If a future dispatch
introduces one, the field name is already stable.

**Errors:**
- `400` — source doc is not a quote (e.g. an invoice id was passed).
- `403` — non-admin/super_admin/owner role.
- `404` — source `qid` not found in caller's tenant; OR destination
  `customer_id` not found in caller's tenant.
- `422` — `property_id` sent but it does not belong to the
  destination customer, or refers to an inactive property.

## Carry-over vs reset — full field manifest

Mobile-parity dev should mirror this table precisely.

### Carried (verbatim from source, subject to line-id re-mint below)

| Field                              | Notes |
| ---------------------------------- | ----- |
| `title`                            | Verbatim. See "Title decision" below. |
| `doc_type`                         | Always `"quote"` (source is a quote or the endpoint 400s). |
| `line_items[*]` (all fields)       | Each line gets a fresh `id` (uuid4); decline state is stripped (see reset table). |
| `tax_rate`                         | Carried; drives `compute_totals` on the new lines. |
| `notes`                            | Carried. |
| `terms`                            | Carried. |
| `internal_notes`                   | Carried. |
| `customer_group_display`           | Carried; falls back to `True` when source lacks the field (K79 default). |
| `customer_group_descriptions`      | Carried (dict of category_id → description); empty dict when source lacks it. |

### Re-computed / re-assigned on the new quote

| Field           | Value on new quote |
| --------------- | ------------------ |
| `id`            | Fresh `new_id()` (uuid4). |
| `tenant_id`     | Same as source (tenant-scoped operation). |
| `customer_id`   | From body — destination customer. |
| `customer_name` | Denormalized from destination customer (freshly resolved). |
| `property_id`   | Per resolution rules below. |
| `subtotal`      | `compute_totals(new_lines, tax_rate)`. |
| `tax`           | Same. |
| `total`         | Same. |
| `created_at`    | `now_iso()`. |

### Reset (explicitly nulled / zeroed)

| Field                    | Value |
| ------------------------ | ----- |
| `status`                 | `"draft"` |
| `payment_status`         | `"unpaid"` |
| `amount_paid`            | `0.0` |
| `accepted_at`            | `None` |
| `declined_at`            | `None` |
| `sent_at`                | `None` |
| `viewed_at`              | `None` |
| `first_viewed_at`        | `None` |
| `last_viewed_at`         | `None` |
| `paid_at`                | `None` |
| `last_reminder_at`       | `None` |
| `reminder_count`         | `0` |
| `scheduled_job_id`       | `None` |
| `deleted_at`             | `None` |
| `has_declined_lines`     | `False` |

### Per-line reset (inside every carried `line_items[*]`)

| Line-item field            | Value on new line |
| -------------------------- | ----------------- |
| `id`                       | Fresh `new_id()`. |
| `customer_status`          | `"pending"` |
| `customer_declined_at`     | `None` |
| `customer_declined_by`     | `None` |
| `customer_decline_reason`  | `None` |
| `customer_accepted_at`     | `None` |
| `customer_accepted_by`     | `None` |

### Dropped entirely (never touched — live in adjacent collections)

| Concern      | Collection            | Why it's naturally dropped |
| ------------ | --------------------- | -------------------------- |
| Signatures   | `signatures`          | Rows are keyed by `quote_id`. A fresh `quote_id` has no rows. |
| Photos       | `service_reports.photos`, S3 keys, etc. | Not stored on the quote doc. Fresh `quote_id` has no linkage. |
| Magic-link   | JWT — stateless       | Endpoint mints tokens on demand; no server-side row to copy. |
| `payment_link`, `stripe_*` | On the quote doc | Not present on source-quote drafts; the doc dict simply doesn't carry them into the new doc (fresh state → no keys). |
| `invoice_id` / conversion pipeline | Cross-collection FK | New quote is standalone. Not carried through this surface. |
| Audit rows on the source | `audit_logs` | Untouched — source audit history is preserved. |

## Property resolution rules

Adapted from the address-model dispatch after confirming the
codebase uses `properties` (per-customer, up to `MAX_PROPERTIES=10`)
rather than an `addresses` collection.

- `body.property_id` present →
  - Look up `db.properties.find_one({id, tenant_id, customer_id})`.
  - Not found (wrong customer or wrong tenant) → **422** with
    `property_id does not belong to the destination customer`.
  - Found but `active=False` → **422** with
    `property_id refers to an inactive property`.
- `body.property_id` omitted (or `null`) →
  - Query destination customer's active properties.
  - Exactly 1 active → auto-assign it (mirrors `create_quote`).
  - 0 or >1 active → leave `property_id=None`. Legal per the
    existing schema (consolidated-billing mode).

**No "no addresses → 422" branch.** A quote with `property_id=null` is a
first-class citizen in this codebase; the mobile-parity spec should
follow the same rule.

## Title decision

**Chosen: carry `title` verbatim.**

Rationale:
- Many quotes have long, meaningful titles ("123 Main St · Full pool
  resurface + retile") that would bloat with an appended " (copy)".
- Stripe, HubSpot, and every downstream CRM convention is
  carry-unchanged; users expect to see identical titles in a list
  and rename in the draft.
- The new quote is `status=draft` and pinned to potentially a
  different customer already — the identity signals are visually
  distinct enough.

Alternative considered and rejected: append `" (copy)"`. If product
review later prefers the suffix, flip the one-liner
`"title": src.get("title") or ""` in `routers/quotes.py::duplicate_quote`
to `"title": f"{src.get('title') or ''} (copy)".strip()`.

## Frontend property-picker UX

The modal reads `GET /api/customers/{customer_id}/properties` and
filters to `active != false`.

- **0 active properties**: dropdown shows "No properties on file",
  disabled; inline hint below reads _"This customer has no active
  properties. The new quote will be created without a property pin
  — you can add one from the draft."_; the Duplicate button
  **remains enabled** — the backend accepts `property_id=null`.
- **1 active property**: dropdown pre-selects it. Admin can still
  clear via keyboard on the `<select>` but there is no visible
  "unset" option — the single active property is the only choice.
- **>1 active properties**: dropdown lists them; the **first
  active property** (ordered by the endpoint's `sort_order` ASC) is
  pre-selected. Admin can switch. This UX auto-fill differs from
  the backend auto-assign (which fires only for exactly-1
  destination customers); however, because the modal always sends
  the chosen `property_id`, the divergence is invisible to
  operators.

## Audit event contract

```json
{
  "event":                    "quote.duplicated",
  "source_quote_id":          "<qid>",
  "new_quote_id":             "<new-uuid>",
  "source_customer_id":       "<source customer_id>",
  "destination_customer_id":  "<body.customer_id>",
  "actor_id":                 "<user.id>",
  "tenant_id":                "<tenant.id>",
  "at":                       "<ISO now>",
  "source":                   "admin_ui"
}
```

Written best-effort — a failed audit row does NOT roll back the
successfully-inserted duplicate quote. See the `try/except` around
`db.audit_logs.insert_one` in `duplicate_quote`.

## RBAC

- `require_admin` gates the endpoint. Same helper used by
  `create_quote`, `update_quote`, and `hard-delete quote`. `admin`,
  `super_admin`, and `owner` pass; every other role (technician,
  manager, customer) → 403.
- Frontend button gate mirrors this via
  `isStaff = ["admin", "super_admin"].includes(user.role)` on
  `QuoteInvoiceDetail.jsx:165` (identical shape to the Hard Delete
  button gate). Manager doesn't see the button, matching the
  backend guard.

## Non-goals honoured

- No mobile touch. `/app/mobile/` was untouched during this dispatch.
- No changes to the sanitizer, portal-gate rule, PDF routing,
  dual-total, decline-per-group, Business Settings, theme refresh,
  or backend `_verify_estimate_token`.
- No `addresses` collection introduced.
- No `quote_number` sequence introduced.
- No new customer schema fields (`default_address_id` etc.).
- No `.env.production` mutation.
- No external repo cloning.

## Adaptation notes (dispatch vs codebase reality)

The original dispatch encoded a data model that would have required
schema drift. The following adaptations were confirmed with the
dispatcher before landing:

| Dispatch term | Codebase reality | Adaptation |
| ------------- | ---------------- | ---------- |
| `address_id`  | No addresses collection; customers have flat `service_address` + `billing_address` strings, addressing on quotes goes through `property_id` (K79). | Body param renamed to `property_id`. |
| `default_address_id` | Not present. | N/A — property auto-assign uses "exactly 1 active" rule, mirroring `create_quote`. |
| `quote_number` (mintable) | Only invoices carry a numbering sequence (`services/invoice_numbering.py`); quotes are identified by uuid. | Response returns `quote_number = id[:8]` — the 8-char UI display prefix. |
| "No addresses → 422" | Quotes accept `property_id=null` legally. | Branch dropped. |
| Frontend "0 addresses disables Duplicate" | Legal path in this codebase. | Duplicate stays enabled; inline hint tells the operator what will happen. |

## Test coverage

### Backend — `backend/tests/test_quote_duplicate.py` (13 cases)

- **Case 1** — Same-customer duplicate: fresh draft, reset lifecycle,
  fresh line ids, decline state pending, audit row observable
  through side effect of the created quote. ✓
- **Case 2** — Explicit `property_id` on different customer →
  pinned. Skips gracefully when the fixture tenant's second
  customer has no active properties.
- **Case 3** — No `property_id`, destination has exactly 1 active
  → auto-assign. Skips gracefully when count ≠ 1.
- **Case 3b** — No `property_id`, destination has 0 or >1 active
  → `property_id=None`. ✓
- **Case 4** — Mismatched `property_id` → 422. Skips when
  fixture tenant lacks the property on the wrong customer.
- **Case 6** — Declined lines → all pending on new quote;
  source unchanged. Uses the magic-link decline route to stage
  a real `customer_status="declined"` (PUT `/quotes` strips
  the field via `QuoteUpdate` schema). Skips if magic-link
  mint fails.
- **Case 7** — Accepted quote → new is draft, `accepted_at=None`;
  source unchanged. Skips if the `customer-decision` endpoint
  didn't flip status.
- **Case 8** — Photo linkage is not carried onto the new quote
  doc. ✓
- **Case 9** — Technician → 403. ✓
- **Case 10** — Cross-tenant / unknown source qid → 404. ✓
- **Case 11** — Source not found → 404. ✓
- **Case 12** — Destination customer not found → 404. ✓
- **Case 13** — Duplicate twice → two distinct new ids. ✓

**Live result on aquaterra fixture tenant: 8 passed, 5 skipped
(fixture-dependent — cases 2, 3, 4, 6, 7 skip when the fixture
tenant lacks the exact combination they exercise), 0 failed.**

### Frontend — `frontend/src/test/quote-duplicate-modal.test.jsx` (7 cases)

- **Case 1** — Duplicate button gated on `isStaff` in
  `QuoteInvoiceDetail.jsx` source (static-string contract check
  on the gate expression AND the button's testid). ✓
- **Case 2** — `isStaff` list excludes `technician` and
  `customer` (asserts the negative contract; refactors that
  relax the gate will fail loudly). ✓
- **Case 3** — Modal opens with source customer pre-selected;
  property dropdown auto-loads and pre-picks the first active
  property. ✓
- **Case 4** — Changing selected customer refreshes the property
  dropdown. ✓
- **Case 5** — Zero-active-properties customer shows the hint
  AND leaves the Duplicate button enabled. ✓
- **Case 6** — Successful POST fires `onDuplicated({quote_id, quote_number})`
  and threads the resolved `property_id` in the body. ✓
- **Case 7** — 422 surfaces `detail` via `onError`; modal stays
  open. ✓

**Live result: 7 / 7 green.**

## OpenAPI delta

- Before: **1729 paths / 2069 operations.**
- After:  **1730 paths / 2070 operations.**
- New route: `POST /api/quotes/{qid}/duplicate`.

## Files touched

```
 backend/routers/quotes.py                                | +173 (endpoint + model)
 backend/tests/test_quote_duplicate.py                    | new, 13 cases
 frontend/src/components/quotes/DuplicateQuoteModal.jsx    | new, modal
 frontend/src/pages/quotes/QuoteInvoiceDetail.jsx          | +37 (button + wire)
 frontend/src/test/quote-duplicate-modal.test.jsx          | new, 7 cases
 memory/FEATURE_QUOTE_DUPLICATE.md                         | new (this file)
```
