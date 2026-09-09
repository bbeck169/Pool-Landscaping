# PHASE — Editable sent quotes / estimates / invoices with full version history

**Status:** SCOPE AUDIT (no code shipped yet). Queued behind Phase 4 user verification.

**Approved option set (from user):**
- **Q1a** — All three doc types editable after send
- **Q2a** — Every field editable except `doc_number` (immutable server-side)
- **Q3a** — Silent save; no auto-notify, no "Revised" badge, no resend prompt
- **Q4a** — Also editable when accepted/paid, but require an admin confirm dialog
- **Q5a** — Full version history; every edit creates a snapshot; admin can view any previous version

---

## 1. Backend data model

### 1.1 Where sent docs live (confirmed)

| Doc type | Collection | Discriminator | Doc-number field |
|---|---|---|---|
| Quote | `db.quotes` | `doc_type ∈ {"quote", None}` (legacy pre-K48 has no field → treated as quote) | *inferred:* `quote_number` (needs grep confirmation in Phase 1) |
| Invoice | `db.quotes` | `doc_type == "invoice"` (Outcome C — single collection) | `invoice_number` (already server-immutable via `quotes.py:582-583` and `invoice_edit.py:251-271`) |
| Estimate (K48 modern) | `db.estimator_estimates` | n/a (dedicated collection) | *no explicit number today — statuses are `generated / edited / converted / sent`* |
| Estimate (legacy) | `db.estimates` | n/a | *no explicit number* |

**Note (Outcome C reminder):** `db.invoices` is a legacy collection; the source of truth is `db.quotes` with `doc_type="invoice"`. A migration script (`backend/scripts/migrate_invoices_to_quotes.py`) mirrors any strays. Version history writes should key off `db.quotes` (not `db.invoices`) for the invoice case to avoid dual-collection drift.

### 1.2 Where the "locked once sent" gates live today

| File / line | Gate | Current behavior |
|---|---|---|
| `backend/services/quotes/status_gate.py::_ALLOWED` | `_ALLOWED = {"estimate": {"draft","sent"}, "invoice": {"draft"}}` | Hardest gate: **PUT** `/api/quotes/{qid}` allows only `draft` (invoice) or `draft/sent` (quote). All other statuses (`sent invoice`, `accepted`, `paid`, `void`, `cancelled`) → HTTP 409. |
| `backend/routers/quotes.py:575-577` | PUT status gate invoked | Fires 409 with the payload from `denial_payload()` before any body parsing. |
| `backend/routers/invoice_edit.py:187-231` (PATCH `/api/quotes/{invoice_id}`) | Softer gate | Allows `sent` with `body.confirm_edit_sent=True`. Requires typing full `invoice_number` for `paid` edits. Refuses `void`/`cancelled` outright. Auto side-effects: clears Lumino payment link on money-changing edits. |
| `backend/routers/estimator.py:433` (PATCH `/api/estimator/estimates/{eid}`) | No status gate at all | Freely mutable regardless of status. Sets status → `edited` after any change. |
| `backend/routers/estimates.py:314` | Convert-block | Refuses conversion-related mutations on `converted` estimates. Not an edit gate. |
| `backend/routers/quotes.py:869-870` (`/quotes/{qid}/pay-invoice`) | `payment_status=="paid" → 400 "already paid"` | Prevents double-pay, not an edit lock. |

### 1.3 Existing audit trail (partial — do NOT collide)

- **`db.invoice_edit_history`** already exists (`invoice_edit.py:427`, exposed via `GET /api/quotes/{invoice_id}/edit-history` at `invoice_edit.py:440-461`). Stores per-field diffs, `edited_by_user_id`, `edited_at`, `changed_fields`, `auto_effects`, `reason` — but **only for invoice PATCH**. **NO full snapshot**.
- Quotes (via `update_quote` PUT) currently have no audit history.
- Estimator has no audit history.

**Design choice:** ship a new unified `db.document_versions` collection covering all three doc types. Keep `db.invoice_edit_history` for backwards-compat reads (the frontend uses `/edit-history`); the new endpoint returns richer data via `db.document_versions`. Do NOT decommission `invoice_edit_history` in this phase.

### 1.4 New collection: `db.document_versions`

```
{
  id:                    uuid,
  doc_type:              "quote" | "invoice" | "estimator_estimate" | "estimate",
  doc_id:                str,                # id of the source doc
  tenant_id:             str,                # scope guard
  version:               int,                # 1-indexed monotonic per (doc_type, doc_id)
  is_baseline:           bool,                # True for the retroactive baseline snapshot
  snapshot:              dict,                # FULL document body at save time (pre-edit)
  saved_by_user_id:      str,
  saved_by_user_email:   str,
  saved_by_role:         str,
  saved_at:              datetime,
  status_at_edit:        str,                # doc.status at the moment of edit
  reason:                str | None,          # optional operator note
  changed_fields:        [ str ],             # convenience list (also computable from snapshot diff)
  lock_bypass_ack:       bool,                # True if Q4a confirm-dialog was used
  restore_of_version:    int | None           # points at the version this row restored, if any
}
```

**Indexes:** `(tenant_id, doc_type, doc_id, version DESC)` compound; unique on `(doc_type, doc_id, version)`.

**Retroactive baseline:** on the FIRST edit of any doc that has no `document_versions` rows yet, insert version `1` with `is_baseline=True` capturing the current pre-edit state, THEN write version `2` for the incoming edit. Guarantees the pre-edit state is always recoverable from history-start.

---

## 2. Backend endpoints (planned)

### 2.1 Loosen existing edit gates

| Endpoint | Change |
|---|---|
| `PATCH /api/quotes/{invoice_id}` (`invoice_edit.py`) | Add `paid | accepted` allowlist. Replace `confirm_edit_paid_invoice_number` (heavyweight) with new `acknowledged_lock_bypass: bool` body flag for the confirm-dialog. Keep the old `confirm_edit_sent` path for backwards compat. |
| `PUT /api/quotes/{qid}` (`quotes.py::update_quote`) | Extend `_ALLOWED` map to permit `sent | accepted | paid` when `body.acknowledged_lock_bypass=True`. Keep `void | cancelled` locked forever. |
| `PATCH /api/estimator/estimates/{eid}` (`estimator.py`) | Add explicit status gate that mirrors the pattern (draft OK; sent OK with ack; converted requires ack). |

### 2.2 New endpoints (all admin-only)

| Method + path | Purpose |
|---|---|
| `GET /api/documents/{doc_type}/{doc_id}/versions` | Paginated list of version metadata (no `snapshot` body); tenant-scoped. Testid `documents-versions-list`. |
| `GET /api/documents/{doc_type}/{doc_id}/versions/{version_id}` | Full snapshot for one version. Testid `documents-version-detail`. |
| `POST /api/documents/{doc_type}/{doc_id}/versions/{version_id}/restore` | Snapshot current-state (new version), then apply restored snapshot as the new live doc. Appends a version with `restore_of_version=N`. |

`doc_type` values on the URL: `quote | invoice | estimator_estimate | estimate` (kebab-case in URL is fine — normalize to underscores server-side).

### 2.3 Immutable-field enforcement

- Server-side, PATCH/PUT reject any body that includes `invoice_number`, `quote_number`, or the estimator estimate's numbered field (if we decide to add one — currently estimator has no visible number, so N/A for this phase).
- Existing guards in `quotes.py:582` and `invoice_edit.py:251` already handle `invoice_number`. Extend to reject `quote_number` if the field exists (Phase 1 will confirm with a grep).
- Frontend disables the number input.

### 2.4 Version-write ordering (append-only invariant)

```
PATCH /api/quotes/{id}  (or estimator PATCH, or quote PUT)
  1. Load current doc (existing behavior)
  2. If NO document_versions row exists for this doc → insert baseline (v1)
  3. Insert new version row snapshotting CURRENT state (v2 or v(N+1))
  4. Apply the update to the doc
  5. Existing side-effects: totals recompute, Lumino refresh, audit log
```

If step 4 fails, step 3 has already committed → the history reflects the last known good state. Rollback of step 3 is not attempted (an orphan version row is preferable to a lost pre-edit snapshot).

### 2.5 Restore endpoint mechanics

```
POST /api/documents/{doc_type}/{doc_id}/versions/{version_id}/restore
  1. Load target version by (doc_id, version_id, tenant_id)
  2. Load current doc
  3. Insert new version snapshotting the CURRENT doc (call this v(N+1))
  4. Insert new version cloning target's snapshot with restore_of_version=target.version
       - The clone becomes v(N+2)
  5. Apply target snapshot as the new live doc (respecting doc_number immutability!)
       - If target snapshot contains a different doc_number than current, DROP the diff and keep current's doc_number
  6. Return the updated doc + the two new version IDs
```

---

## 3. Frontend plan

### 3.1 Doc-detail pages currently gating edits

| Page | Current gate | Change |
|---|---|---|
| `pages/quotes/QuoteInvoiceDetail.jsx` | Renders read-only historical panel when `status != "draft"` (comment at line 43). "Edit" button hidden. | Reveal Edit button on all statuses. Gate the modal open with the confirm-dialog when status ∈ `accepted | paid | sent-invoice`. |
| `pages/estimator/Estimator.jsx` + `EstimatorPages.jsx` | Estimator already fully mutable — no UX gate to change. | Just add the version-history drawer. |
| `pages/estimates/AIEstimatorPage.jsx` | Legacy estimates path — check for edit UI in Phase 1. | Same treatment as estimator. |
| `pages/invoices/MasterInvoice.jsx` | Read-only master roll-up; check for edit path. | Confirm no dedicated edit surface — invoice edits happen via `QuoteInvoiceDetail` since both live in `db.quotes`. |

### 3.2 New UI components

- `components/documents/EditLockConfirmDialog.jsx` — modal with the accepted/paid warning text; user must click Continue to proceed. Sets `acknowledged_lock_bypass: true` in the PATCH body.
- `components/documents/VersionHistoryDrawer.jsx` — right-side drawer opened from a "History" button on the detail page. Renders a list of version rows: `v{N} · {timestamp} · {editor} · {status_at_edit}` + a Restore button per row.
- `components/documents/VersionSnapshotView.jsx` — reads `GET /versions/{version_id}` and shows a read-only render of that historical version. Diff view (side-by-side vs current) is a **Phase 2 nice-to-have**, out of scope for Phase 1.

### 3.3 Testids to add

- `edit-doc-btn` (already present on the detail page — verify)
- `edit-lock-confirm-dialog`, `edit-lock-confirm-continue`, `edit-lock-confirm-cancel`
- `version-history-btn`, `version-history-drawer`
- `documents-versions-list`, `documents-version-detail`
- `version-restore-btn-{version_id}`, `version-restore-confirm-dialog`

---

## 4. Guardrails

1. **`doc_number` immutable** — server rejects PATCH/PUT/restore that would change it. Restore endpoint drops the diff silently (does NOT 400).
2. **Version write BEFORE mutation** — guaranteed by ordering in §2.4. Baseline snapshot on first edit is always retroactively captured.
3. **Restore is append-only** — never overwrites a version row; always inserts new ones.
4. **Admin-only for versions endpoints** — `require_admin` dep. Edit endpoints keep existing role gates (`require_admin` on quotes.py PUT; `_require_staff` on invoice_edit; `require_admin_or_tech` on estimator).
5. **No `db.customers` writes.** Customer-snapshot refresh in `invoice_edit.py:281-289` stays exactly as-is.
6. **No Outcome C route-alias touches.**
7. **All existing testids preserved.** New testids are additive.
8. **No touches to:** comms diagnostics, offline mode, Stripe/Resend/RC, chemistry, service records, notifications, filters, Phase 4 files, Chunk 3 files.
9. **No external repo cloning.**

---

## 5. Risks + edge cases

### 5.1 Paid invoices tied to real Stripe charges — **HIGH RISK**

- `db.quotes` invoice rows carry `payment_intent_id`, `charge_id`, `payment_status="paid"`, `amount_paid`, `paid_at`.
- Editing the total on a paid invoice DOES NOT trigger a refund or a new Stripe charge. The tenant is on the hook to reconcile manually.
- **Confirm-dialog copy must state this explicitly**, e.g.:
  > "This invoice has already been paid. Editing will not adjust the customer's payment. You are responsible for issuing a refund or additional charge manually via Stripe."
- Add a check: if `remaining_balance` after edit becomes negative (over-paid), flag `overpaid` on the doc so dashboards can surface it. **Do NOT auto-refund.**
- Existing Lumino side-effect (`invoice_edit.py:346-382`) already clears the payment link on money-changing edits — that behavior should stay.

### 5.2 Signed docs — **MEDIUM RISK**

- `db.signatures` collection stores signature SVG + `signed_at` + `signature_token` per quote (`routers/signatures.py`).
- On the doc, `signature_status` gets synced.
- Editing a doc that has been signed **invalidates the signature** (customer signed a different version of the terms).
- **Behavior:** on edit, if `doc.signature_status == "signed"`, mark the signature row as `superseded_at=now`, clear `signature_status` on the doc back to `null`, and log this on the version row. Include the invalidation warning in the confirm-dialog.

### 5.3 Line-item deletion on partially paid — **MEDIUM RISK**

- If `amount_paid > 0` and a line item is removed, `remaining_balance` recomputes but the paid dollars now correspond to fewer items than the customer sees.
- **Behavior:** allow the delete but require the confirm-dialog acknowledgement AND surface a warning field on the doc (`ledger_drift=true`) that clears on the next paid-in-full event or manual clear. Do NOT reject.

### 5.4 Estimate → quote auto-conversion (Outcome C) — **DECISION NEEDED**

- `estimator.py::convert_to_quote` sets estimator estimate `status="converted"` and stores `quote_id` reference (`estimator.py:724-725`).
- **Question for user (blocking Phase 1 kickoff):** when an already-converted estimate is edited, do we:
  - **Option (a)** — leave the derived quote alone (estimate edit is now cosmetic / history-only)?
  - **Option (b)** — also re-propagate changes to the derived quote (risky — the quote may have been separately edited)?
  - **Option (c)** — refuse to edit converted estimates and require the operator to edit the quote directly?

**Recommendation:** Option (a) — silently allow the estimate edit, do NOT touch the derived quote. Rationale: minimizes cascade risk; the quote is the source of truth once converted. Confirm before Phase 1.

### 5.5 Version storage size — **LOW RISK**

- A full doc snapshot is ~5-15 KB compressed. Even 100 edits per doc across 10k docs = ~15 GB → fine for Mongo.
- Add a **retention policy** entry to Phase 3: cap at 100 versions per doc, prune oldest non-baseline when exceeded. **Not blocking Phase 1.**

---

## 6. Phased build plan (post-verification)

| Phase | Scope | Backend | Frontend | Tests |
|---|---|---|---|---|
| **Phase 1** | Baseline unblock — loosen gates + write `document_versions` + read endpoint | `_ALLOWED` map extension w/ ack flag, `document_versions` collection, version-write helper, `GET /versions` list | Enable Edit button on all statuses; wire confirm-dialog for accepted/paid; **no** history UI yet | Backend: 12+ pytest, incl. paid-invoice edit path, ack flag enforcement, baseline snapshot on first edit; Frontend: RTL for confirm dialog + edit-enabled |
| **Phase 2** | Version history UI | `GET /versions/{id}` detail | `VersionHistoryDrawer`, `VersionSnapshotView` | RTL: drawer renders, snapshot loads |
| **Phase 3** | Restore + polish | `POST /versions/{id}/restore` | Restore button + confirm | RTL: restore flow; retention policy (P3.b) |
| **Phase 4** | Signature invalidation + ledger-drift flags | signature supersedes on edit; `ledger_drift` flag | Warning banners on affected docs | Full E2E |

**STOP after each phase for user verification** per the standing order pattern.

---

## 7. Blockers before Phase 1

1. Confirm §5.4 handling (estimate → quote conversion edits): recommend **Option (a)** silent, quote untouched.
2. Confirm the confirm-dialog copy for paid invoices (§5.1). Ping user for approval of the exact wording.
3. Confirm signature-invalidation behavior (§5.2) — the "invalidate on edit + user acknowledges" pattern.
4. **Phase 4 user verification still owed.** This feature does NOT begin until Phase 4 is verified.

---

**Author:** main agent
**Date:** Feb 2026
**Status:** AWAITING USER APPROVAL to begin Phase 1
