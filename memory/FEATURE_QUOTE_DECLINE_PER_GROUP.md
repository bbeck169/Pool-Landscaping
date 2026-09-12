# Feature — Customer Decline-per-Group on Quotes (Feb-2026)

Ships four PATCH routes + customer_view payload extensions so a
customer (magic-link) or admin (JWT) can toggle the decline state on
every line item belonging to a service-category group in one call.
Groups themselves remain **ephemeral** — the decline state persists
on the underlying line items and is aggregated by group at read
time.

## Storage strategy — chosen: (a) ephemeral, aggregated on line items

Groups are computed at read time by
`services/quotes/customer_view.py::group_lines_for_customer` — they
have no persistent representation on `db.quotes`. That means group
decline state must live on the LINE ITEMS. The existing per-line
decline mechanism (`customer_status`, `customer_declined_at`,
`customer_decline_reason` — shipped by Phase A) is reused. One new
field is added:

- `line_item.customer_declined_by` — actor id string. Mirrors
  `customer_declined_at`. Populated with the same actor identifier
  the audit row uses:
  - magic-link: `f"token:{ctx['cid']}"`
  - admin: `user["id"]`

A group is considered **fully declined** when every line item with
that `service_category_id` has `customer_status == "declined"`.

## Endpoint contract

Four PATCH routes (OpenAPI count: 1722 → **1726**).

### Magic-link (customer surface)

```
PATCH /api/portal/quotes/via-token/{token}/groups/{group_key}/decline
      Body: { "reason": "<=200 chars" }   (optional)
      → 200: fresh customer-view payload
      → 404: no line items belong to group_key
      → 409: quote is not in {sent, viewed} OR decision ∈ {accepted, declined}
      → 429: 11th hit within 5 min on the "group" rate bucket
```

```
PATCH /api/portal/quotes/via-token/{token}/groups/{group_key}/undecline
      Body: empty
      → 200: fresh customer-view payload
      → 404 / 409 / 429: same as decline
```

### Admin (JWT — admin/super_admin only, technician 403)

```
PATCH /api/quotes/{qid}/groups/{group_key}/decline
      Body: { "reason": "<=200 chars" }   (optional)
      → 200: fresh customer-view payload (as_customer=False)
      → 403: technician role
      → 404: quote not found OR no line items match group_key
      → 409: quote is not actionable
```

```
PATCH /api/quotes/{qid}/groups/{group_key}/undecline
      Body: empty
      → 200 / 403 / 404 / 409
```

### `group_key` stability

- `service_category_id` (uuid) for real categories.
- `"__other__"` sentinel for line items with no `service_category_id`.

### Sample curl

```
# Magic-link decline
curl -X PATCH \
  "$API/api/portal/quotes/via-token/$TOK/groups/cat-hardscape/decline" \
  -H "Content-Type: application/json" \
  -d '{"reason":"Descoping"}'
```

## customer_view payload additions

Each `groups[i]` now includes:

- `group_key: str` — stable URL-safe id (`category_id` or `"__other__"`).
- `declined: bool` — all lines in group are `customer_status=declined`.
- `declined_at: str | null` — max `customer_declined_at` in the group
  when fully declined, else `null`.
- `declined_by: str | null` — actor id from the most-recent decline
  stamp when fully declined, else `null`.
- `active_subtotal: number` — sum of `quantity × unit_price` for
  the non-declined lines in the group. Equals `subtotal` when
  nothing is declined and `0` when everything is declined.

Top-level payload additions:

- `grouped_active_subtotal: number` — sum of `active_subtotal`
  across groups.
- `has_declined_groups: bool` — any group fully declined.

None of the existing fields were removed — additive only.

## Total-recalc source of truth — SERVER

- Backend `services/quotes/totals.py::recompute_customer_adjusted_totals`
  runs on every mutation (already shipped in Phase A).
- Frontend refreshes state from the returned payload rather than
  recomputing locally. This keeps admin/customer totals identical.
- Admin dual-total (`QuoteInvoiceDetail.jsx`) renders only when
  `totals.has_declined_lines === true`:
  - `Subtotal (incl. declined): $<original_total>`
  - `Effective (excl. declined): $<adjusted_total>`

## PDF strike rendering — ReportLab `<strike>` tag

Both PDF handlers were updated in the **grouped** branch:

- `routers/quotes.py::quote_or_invoice_pdf` — grouped rows for
  declined groups render every cell wrapped in a `Paragraph` with
  `<strike>…</strike>`. Total row uses `adjusted_total` when
  `has_declined_lines` is true.
- `routers/estimate_viewer.py::estimate_pdf` — same treatment on the
  Service / Description / Subtotal columns for declined groups; the
  customer PDF totals switch to `adjusted_subtotal / adjusted_tax /
  adjusted_total` when the quote has declined lines. Admin
  `?internal=1` PDF is unchanged (grouped_mode is customer-only).

The `/estimates/{qid}/pdf` deprecated alias inherits the same
behaviour — same function body, kept per the Dispatch A Item-2
STOP-report decision.

## Rate limit bucket

New bucket key in `estimate_viewer._PHASE_A_RATE_LIMITS`:

```python
"group": (10, 300.0)   # 10 hits / 5 min per token hash
```

Applied only to the two magic-link routes. Admin routes are
JWT-gated and share no bucket. The bucket is process-local — same
constraint as the existing `line` / `decision` limiters.

## Audit event contract

Every decline / restore writes one row to `db.audit_logs`:

```json
{
  "id": "<uuid>",
  "event": "quote.group_declined" | "quote.group_restored",
  "quote_id": "<qid>",
  "tenant_id": "<tid>",
  "group_key": "<service_category_id | __other__>",
  "actor_id": "<user_id or token:{cid}>",
  "source": "portal_token" | "admin_ui",
  "at": "<ISO>",
  "line_count": <int>,
  "reason": "<string or null>"
}
```

Best-effort write — a Mongo hiccup logs a warning and lets the PATCH
succeed. Matches the shape used by `_mark_declined` audit rows.

## Frontend integration points

### Customer surface — `frontend/src/components/EstimateView.jsx`

- New handlers `declineGroup(groupKey)` / `restoreGroup(groupKey)`
  wired to `api.patch(...)`.
- Grouped table gained an action column (rendered when `actionable
  && !locked` OR when an admin is viewing without printable mode).
- Each group row now shows:
  - Decline button (data-testid `estimate-grouped-decline-btn-{cat}`),
    or Restore button (`estimate-grouped-restore-btn-{cat}`) when
    the group is declined.
  - Strike + muted styling on struck rows via inline style.
  - Small "Declined <ts>" label when declined.

### Admin — `frontend/src/pages/quotes/QuoteInvoiceDetail.jsx`

- Totals block gained a conditional dual-total renderer keyed off
  `doc.has_declined_lines`. Rendered only when at least one line is
  declined; otherwise the previous single-total footprint is
  preserved.

## Test coverage

### Backend — `tests/test_quote_group_decline.py`

1. `test_customer_group_decline_via_token` — decline drops adjusted
   total, `customer_view.groups[cat_a].declined === true`,
   `active_subtotal === 0`, audit row present.
2. `test_customer_group_undecline_via_token` — round-trip restores
   `adjusted_total` to `original_total`, group no longer declined.
3. `test_admin_group_decline_on_behalf` — admin JWT works, group
   flips server-side.
4. `test_technician_forbidden_on_admin_route` — 403 for technician.
5. `test_group_rate_limit_returns_429` — 10 hits pass, 11th 429.
6. `test_group_decline_on_accepted_returns_409` — actionability guard.

### Frontend — `src/test/estimate-view-decline-per-group.test.jsx`

1. Actionable group renders Decline button.
2. Click Decline → PATCH fires → strike + Restore rendered.
3. Restore round-trip via the undecline PATCH.
4. Non-actionable (accepted) quote hides both Decline and Restore.
5. Admin dual-total renders only when `has_declined_lines === true`.

## Non-goals (explicitly not shipped)

- No new schema on the group object (groups remain ephemeral).
- No changes to the existing per-line decline endpoints.
- No changes to the grouped-layout LOCK-ON behaviour.
- No optimistic UI — server response is the source of truth.

## Follow-ups

- `estimate_viewer.py::estimate_pdf` full-function removal is still
  deferred (see Cleanup Dispatch A · Item 2 STOP report).
- Add a `magic_link:<token_hash>` variant of `actor_id` if we ever
  want a hashed customer identity in audit rows.
