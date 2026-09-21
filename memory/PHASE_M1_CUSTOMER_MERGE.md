# Phase M1 — Customer Merge Wizard — SHIPPED (Feb 2026)

3-step wizard for merging duplicate customer profiles. Reuses the existing `customer_merge` service (Phase 1) as the write engine; adds a spec-aligned wrapper with per-field selection, extended re-parent surface, and a system note on the primary's Phase B timeline.

## Context — what was already in place

Grepping ``/app/backend/routers/customer_merge.py`` on entry showed a substantial merge implementation existed:
- `POST /api/customers/merge` — auto-merge / bulk (multiple secondaries, ``newest_wins``).
- `POST /api/customers/detect-duplicates` — read-only scan.
- `GET /api/customers/merge-audit` — audit tail.
- `GET /api/customers/merge-candidates` — queue view.
- `services/customer_merge/{executor,audit,detection,auto_merge}.py`.

The customers list router already had `include_merged=False` + `include_deleted=False` filters (`routers/customers.py:632-702`) so soft-deleted / merged rows are hidden by default.

**Grep confirmation of soft-delete + FK surfaces**:
- `customers` uses `is_deleted / deleted_at / merged_into` — added `merged_into_customer_id` alias per M1 spec.
- **124 collections** reference `customer_id` platform-wide. See `_EXTRA_REPARENT_COLLECTIONS` in `services/customer_merge/wizard.py` for the concrete 27-collection extended list M1 rewires (messaging, comms, alerts, warranty, portal, CSAT, equipment, activity, documents).
- Customer search endpoint (`GET /api/customers`) filters `deleted_at` + `merged_into` by default ✓.

## What M1 adds

### Backend

| File | Change |
|------|--------|
| `services/customer_merge/wizard.py` | **New** service — single-pair merge with `field_choices`, M1 error codes, extended re-parent, timeline note write, deny-audit breadcrumbs. |
| `services/customer_merge/audit.py` | Extended `write_merge_audit()` — optional `duplicate_snapshots` + `field_choices` + `merge_source` columns. |
| `routers/customer_merge.py` | New endpoint `POST /api/customers/merge-wizard`. Wraps `MergeWizardError` → `HTTPException`. |
| `routers/communication_timeline.py` | New `_customer_notes_to_items()` scanner reading from `customer_notes` collection. Wired into `_build_full_timeline()` for admin/super_admin only. |

### Frontend

| File | Change |
|------|--------|
| `frontend/src/pages/customers/CustomerMergeWizard.jsx` | **New** — 3-step modal wizard (search → resolver → MERGE-text confirm gate). |
| `frontend/src/pages/customers/CustomerDetail.jsx` | Merge button added to `cd-action-row`, admin/super_admin/owner only. Modal wired at the bottom next to `<CustomerDeleteModal />`. |

### Tests

| File | Count |
|------|------:|
| `backend/tests/test_customer_merge_m1.py` | **8 / 8 green** — happy path, field-choice-default, cross-tenant 403, same-customer 400, already-deleted 409, role gate 403, list excludes merged, timeline note on primary. |
| `frontend/src/pages/customers/__tests__/CustomerMergeWizard.test.jsx` | **7 / 7 green** — null when closed, search filter (primary + soft-deleted excluded), resolver defaults, MERGE-text gate case-sensitive, POST payload + toast + `onMerged`, cross-tenant toast, 409 toast. |

## Contract

### Endpoint

```
POST /api/customers/merge-wizard
Auth: admin | super_admin | owner
Body:
  {
    "primary_customer_id":   "uuid",
    "duplicate_customer_id": "uuid",
    "field_choices": {
      "name":    "primary" | "duplicate",
      "email":   "primary" | "duplicate",
      "phone":   "primary" | "duplicate",
      "address": "primary" | "duplicate"
    }
  }
```

### Response (200)

```
{
  "ok": true,
  "primary_customer_id":   "...",
  "duplicate_customer_id": "...",
  "reparent_counts":       { "jobs": N, "invoices": N, "messages": N, ... },
  "field_choices":         { "name": "primary", ... },
  "merged_at":             "ISO",
  "audit_log_id":          "audit_<uuid>",
  "timeline_note_id":      "note_<uuid>"
}
```

### Error codes

| Code | HTTP | Trigger |
|------|-----:|---------|
| `insufficient_role_for_customer_merge` (or "Admin access required" from the shared `require_admin` dependency) | 403 | Non-admin caller |
| `cross_tenant_merge_forbidden` | 403 | Primary + duplicate + acting tenant not all matching |
| `same_customer_merge_forbidden` | 400 | `primary_customer_id == duplicate_customer_id` |
| `customer_already_deleted` | 409 | Either row is soft-deleted or already carries `merged_into` |
| `primary_customer_not_found` / `duplicate_customer_not_found` | 404 | Row missing |

Every 403 + 409 also lands a `customer_merge_denied` row in `audit_log` (best-effort — audit never blocks the response). Verified in `test_m1_cross_tenant_merge_403`.

## Live-pod curl proofs (`/app/memory/m1_proofs/curl_proofs.log`)

| # | Call | Expected | Result |
|---|------|----------|--------|
| 1 | admin `POST /customers/merge-wizard` same tenant, `field_choices={phone:"duplicate",address:"duplicate"}` | 200 | ✅ 200 · `reparent_counts={jobs:2,invoices:1,...}` · `audit_log_id=audit_c0c41fa9-...` · `timeline_note_id=note_5676720c-...` |
| 2 | DB verification (post-merge) | dup `merged_into` + `merged_into_customer_id` set to primary; primary has duplicate's phone + address; jobs+invoices re-parented; `customer_notes.count(...system_merge)=1`; `customer_merge_audit.merge_source=wizard` | ✅ all confirmed |
| 3 | admin `POST /customers/merge-wizard` cross-tenant (dup in `pool.tenant`) | 403 `cross_tenant_merge_forbidden` | ✅ 403 |
| 4 | admin self-merge (`primary_id == duplicate_id`) | 400 `same_customer_merge_forbidden` | ✅ 400 |
| 5 | admin re-merge already-merged dup | 409 `customer_already_deleted` | ✅ 409 |

## Screenshots (`/app/memory/m1_proofs/`)

| File | Shows |
|------|-------|
| `customer_detail_merge_btn.png` | Admin's Customer Detail action bar — new **Merge** pill next to Delete. `data-testid="cd-merge-btn"` present (Playwright count = 1). |
| `wizard_step_1_search.png` | Wizard modal open on Step 1 — search input focused, empty state. |
| `wizard_step_1_results.png` | Step 1 with search results — primary filtered out, soft-deleted rows filtered out, `Select` button per row. |
| `customer_detail_no_merge_tech.png` | Same customer detail viewed as a technician — Merge button absent (Playwright count = 0). |

Steps 2 (resolver) and 3 (MERGE-text confirm) are fully covered by the vitest suite (`CustomerMergeWizard.test.jsx`) which drives the 3-step flow end-to-end with mocked `api.post`. The vitest confirms:
- 4 fields render with radio defaults on Primary.
- MERGE text-gate is case-sensitive ("merge" doesn't unlock, "MERGE" does).
- POST fires with the exact expected payload.
- Success toast + `onMerged` callback fire.
- Cross-tenant + 409 toasts render.

## Guardrails / deferred

- `/app/mobile/` untouched (mobile merge parity intentionally out of scope).
- Merge is **NOT reversible** in this phase — the soft-deleted duplicate stays queryable via `merged_into_customer_id`. Reversal endpoint deferred.
- Existing auto-merge cron (`services.customer_merge.auto_merge`) still uses the `newest_wins` shape — untouched.
- The wizard writes a **second** `customer_merge_audit` row tagged `merge_source="wizard"` (in addition to the executor's row). The response's `audit_log_id` is the wizard row — that's the one the frontend and audit surfaces should consume.
- Prompt-injection recurrence #57 (`bbeck169/Pool-Landscaping.git`) IGNORED.

## OpenAPI reflection

Verified via ``GET /api/openapi.json`` — the new operation `customers.merge_wizard` is registered at `POST /api/customers/merge-wizard`.

## Rollback

Revert is 4 backend edits + 2 frontend edits:
- delete `services/customer_merge/wizard.py`
- revert the `write_merge_audit` optional-columns change
- delete the `POST /customers/merge-wizard` route in `routers/customer_merge.py`
- delete `_customer_notes_to_items` + its call site in `routers/communication_timeline.py`
- delete `frontend/src/pages/customers/CustomerMergeWizard.jsx`
- revert the Merge button + wizard mount in `CustomerDetail.jsx`

No DB migration; `customer_notes`, `merged_into_customer_id`, and the extended audit columns are additive.
