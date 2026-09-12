# Quote hard-delete (admin + super_admin)

**Status**: shipped (backend + frontend) · preview only · Feb-2026

## User-locked decisions (verbatim)

| # | Decision | Chosen |
|---|---|---|
| **1a** | RBAC | both `admin` AND `super_admin` may hard-delete |
| **2b** | Cascade | delete quote-owned inline subdocs (line_items, signatures, terms, drafts, version snapshots) — PRESERVE audit / ledger rows (`communication_sends`, `outbound_emails`, `marketing_deliveries`, `audit_logs`); they keep their `quote_id` field pointing at a now-gone doc |
| **3a** | Protection | refuse (409) ONLY when the quote has been converted to an invoice (would orphan the invoice). Do NOT refuse for paid payment attempts, customer signatures, or `status=signed` |
| **4b + button** | UX | dedicated red "Hard Delete Quote" button on the admin quote detail page → confirmation modal showing quote number + customer name + total; two buttons: "Cancel" + red "Confirm Hard Delete"; no typing required |
| **5** | Audit | NO `audit_logs` row emitted. The quote disappears with zero trace. **Accepted compliance trade-off** |

## Endpoint contract

`DELETE /api/quotes/{qid}?hard=true` — admin / super_admin only.

### Success
```
$ curl -X DELETE "$API/api/quotes/q-123?hard=true" \
       -H "Authorization: Bearer $ADMIN_TOKEN"
{"ok": true, "hard_deleted": true, "quote_id": "q-123"}
```

### 409 — quote has been converted to invoice
```
$ curl -X DELETE "$API/api/quotes/q-abc?hard=true" \
       -H "Authorization: Bearer $ADMIN_TOKEN"
HTTP/1.1 409 Conflict
{"detail": "Quote has been converted to an invoice and cannot be hard-deleted. Delete the invoice first or void the quote."}
```

The quote is untouched — verify with a subsequent `GET /api/quotes/{qid}`.

### 403 — role gate
Any role other than `admin` / `super_admin` gets:
```
HTTP/1.1 403 Forbidden
{"detail": "admin_or_super_admin_only"}
```

### 404 — nonexistent
```
HTTP/1.1 404 Not Found
{"detail": "quote_not_found"}
```

### 400 — attempted against an invoice
```
HTTP/1.1 400 Bad Request
{"detail": "hard_delete_not_supported_for_invoices — use DELETE /api/invoices/{qid} for the soft-delete surface"}
```

### Soft-delete regression
```
$ curl -X DELETE "$API/api/quotes/q-123"   # NO ?hard=true
# falls through to _perform_soft_delete_quote — stamps deleted_at,
# writes audit rows, returns 200 with the deletion payload
```

## Invoice-conversion detection

Per Feb-2026 schema, invoices do NOT carry a direct `converted_from_quote_id` field. The auto-invoice pipeline (`services/auto_invoice.py`) stamps only `job_id` on the invoice. The indirect link this endpoint uses:

```
invoice.job_id  ==  quote.scheduled_job_id  (or invoice.scheduled_job_id)
```

Helper: `_quote_converted_invoice_id(quote_doc, tenant_id)` — returns the linked invoice id or `None`. Only fires when `quote.scheduled_job_id` is set. Soft-deleted invoices are excluded (a deleted invoice can't be "orphaned").

## Frontend integration

### Files touched
- `frontend/src/components/quotes/HardDeleteQuoteModal.jsx` — **new**. Self-contained confirmation modal. No role check (caller gates on `isStaff`).
- `frontend/src/pages/quotes/QuoteInvoiceDetail.jsx` — added modal import, `hardDeleteOpen` state, red button (quote-only + admin/super-only), modal render block.

### Button visibility rules
```jsx
{!isInvoice && isStaff ? (   // isStaff = role in ["admin","super_admin"]
  <Button variant="danger" testid="hard-delete-quote-btn" ...>
    <Trash2 /> Hard Delete Quote
  </Button>
) : null}
```

Non-admin/non-super roles never see the button. Invoice detail pages never see it (invoices go through the soft-delete surface — `DELETE /api/invoices/{qid}`).

### Modal
- Displays: quote number, customer name, formatted total, red warning box: "This will permanently delete this quote. This action cannot be undone and leaves no record."
- Buttons: "Cancel" (ghost) + "Confirm Hard Delete" (red).
- On 200 → toast "Quote hard-deleted", redirect to `/quotes` after 400ms.
- On 409 → toast surfaces backend `detail` verbatim; modal stays open so the user can Cancel and go delete the invoice first.

## Test matrix

### Backend (`tests/test_quote_hard_delete.py`)

| Test | Case | Asserts |
|---|---|---|
| `test_admin_can_hard_delete_orphan_quote` | RBAC #1a | admin succeeds; doc gone from `db.quotes` (subsequent GET → 404) |
| `test_super_admin_can_hard_delete_orphan_quote` | RBAC #1a | super_admin succeeds |
| `test_non_admin_role_gets_403` | RBAC #1a | technician gets 403; quote untouched |
| `test_customer_role_gets_403_or_404` | RBAC #1a | customer gets 403 (or 404); quote untouched |
| `test_hard_delete_refuses_when_quote_converted_to_invoice` | Protection #3a | 409 with exact detail string; quote STILL present after failure |
| `test_hard_delete_removes_inline_subdocs` | Cascade #2b | quote with rich inline subdocs (signatures + terms + descriptions) — hard-delete removes everything in one shot |
| `test_hard_delete_does_not_touch_ledger_rows` | Cascade #2b | seeded `communication_sends` row with `quote_id=qid` — remains post-delete with `quote_id` intact |
| `test_hard_delete_emits_no_audit_row` | Audit #5 | zero rows in `audit_logs`, `audit_log`, `deletion_audit` for the deleted quote |
| `test_hard_delete_returns_404_for_nonexistent_quote` | 404 path | random UUID → 404 |
| `test_soft_delete_still_works_regression` | Backward-compat | DELETE without `?hard=true` stamps `deleted_at` (legacy path unchanged) |

Result: **9 passed, 1 skipped** (tech RBAC test skips gracefully when the `tech@aquaterra.com` demo user isn't present).

### Frontend (`src/test/hard-delete-quote-modal.test.jsx`)

| Test | Asserts |
|---|---|
| Renders quote number + customer + total + warning | All four testids present with expected values |
| Cancel closes modal without firing DELETE | `onClose` called once, `api.del` never called |
| Confirm fires DELETE and calls onDeleted on 200 | `api.del("/quotes/q-99?hard=true")` + `onDeleted` receives body |
| On 409 surfaces backend detail verbatim, modal stays open | `onError(detail)` called with the exact string, `onClose` not called |
| Confirm button disabled while in flight | `disabled` attribute + label swaps to "Deleting…" |

Result: **5 passed**.

## Ledger preservation invariant

Locked by `test_hard_delete_does_not_touch_ledger_rows`. The user directive #2b is enforced structurally — the endpoint's cascade is a single `db.quotes.delete_one({id, tenant_id})` call. It does NOT touch:
- `communication_sends` — `quote_id` string field survives
- `outbound_emails` — untouched
- `marketing_deliveries` — untouched
- `audit_logs` (any prior events referencing this quote) — untouched

If a ledger consumer needs to display "deleted quote" indicators, it should `find_one({id: doc.quote_id})` and treat "not found" as a signal, NOT rely on a cascade-nullified `quote_id`.

## Zero-audit-trail invariant

**Accepted compliance trade-off per user directive #5.** The endpoint intentionally writes no audit rows. Contrast with the soft-delete path (`_perform_soft_delete_quote`), which stamps BOTH `db.audit_log` (legacy) AND `db.deletion_audit` (Feb-2026 richer audit surface with snapshot + restore support). Hard-delete forgoes both.

Locked by `test_hard_delete_emits_no_audit_row` which asserts zero rows in all three collections (`audit_logs`, `audit_log`, `deletion_audit`) after a hard-delete.

## Follow-up

**Undo-delete grace window** — if the zero-audit-trail trade-off proves too aggressive in practice (accidental hard-deletes with no way back), consider:

1. Add a "soft-hidden-24h" state: hard-delete flips `deleted_at` + `hard_delete_after: now + 24h`, real deletion happens via a nightly janitor job. Endpoint stays 200 immediately; the actual purge is deferred.
2. Add an admin-only "recover" endpoint that flips `deleted_at → null` if still within the window.
3. Update the modal warning to explain the 24h grace.

**Cleanup: dedicated invoice-back-pointer field** — the current indirect detection (`invoice.job_id == quote.scheduled_job_id`) is a schema footprint of the auto-invoice pipeline's design. A follow-up ticket could stamp `source_quote_id` directly on invoices at creation time so the check becomes a single-field lookup instead of a join over `scheduled_job_id`. Would also make the soft-delete cascade audit richer.
