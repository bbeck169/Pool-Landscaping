# Feature — Warranty Contracts · linked_type/linked_id + Warranties section

**Phase**: Feb-2026  
**Scope**: Backend (schema + endpoints) + Frontend (admin section + portal page).  
**Mobile parity**: **deferred** — delegated to `e1_expo_frontend_dev` after web verifies.

## Summary

Warranty contracts can now optionally reference the *thing being
warrantied* — either an **install-workflow job** (freeform
`service_type` containing "install") or a **customer_equipment**
unit. Both admin and portal customer surfaces render a
denormalized `linked_summary` block per contract so no extra
round-trip is needed to display the linked entity.

## Schema delta

`db.warranty_contracts` documents gain **two fields**:

| Field | Type | Notes |
|-------|------|-------|
| `linked_type` | `Literal["install","equipment","none"]` | Default `"none"` on create when omitted. |
| `linked_id` | `str \| None` | MUST be `null` when `linked_type="none"`. |

`ContractIn` and `ContractPatch` Pydantic models both accept the two
new fields. `_validate_link()` is called on every write path
(`POST /warranties/contracts`, `PATCH /warranties/contracts/{cid}`).

## Link validation rules

Enforced by `_validate_link(linked_type, linked_id, tenant_id)`:

| Case | Result |
|------|--------|
| `linked_type ∈ {None,"","none"}` and `linked_id` is falsy | ✅ pass, stored as `none / null` |
| `linked_type == "none"` with a non-null `linked_id` | ❌ **422** `warranty.link.none_id_forbidden` |
| `linked_type ∉ {install, equipment, none}` | ❌ **422** `warranty.link.invalid_type` |
| `linked_type ∈ {install, equipment}` with missing `linked_id` | ❌ **422** `warranty.link.missing_id` |
| `linked_type == "install"` with an id that does NOT match `{tenant_id + service_type~/install/i}` | ❌ **422** `warranty.link.install_not_found` |
| `linked_type == "equipment"` with an id that is not an active same-tenant `customer_equipment` row | ❌ **422** `warranty.link.equipment_not_found` |

Cross-tenant references collapse to `install_not_found` /
`equipment_not_found` — same error code as "does not exist" so the
frontend does not need to distinguish. **Chosen 422** (not 404)
because the mismatch is a validation failure on a submitted body,
not a missing route.

## `linked_summary` shape (denormalized read)

Attached to every contract row on the customer-scoped list
endpoints and returned from `POST` / `PATCH` for the created / updated
record.

```json
{
  "type": "install" | "equipment",
  "label": "<friendly display line>",
  "details": {
    // install:
    "service_type": "Pool Install",
    "service_date": "2026-01-10"
    // equipment:
    "equipment_type": "Filter Pump",
    "brand": "Pentair",
    "model": "IntelliFlo",
    "serial_number": "SN-42"
  }
}
```

Returns `null` when the contract is `linked_type == "none"` **or** when
the referenced entity has since been hard-deleted (defensive — write
path validates, but ops may hard-delete afterward).

## Install-workflow definition

There is no dedicated install workflow flag on `jobs` — `work_class`
is limited to `{"service","repair"}` (see
`backend/services/work_class.py`). This phase defines an install
job as **any `jobs` row whose `service_type` string contains the
substring `install` (case-insensitive)**:

```python
{"service_type": {"$regex": "install", "$options": "i"}}
```

Examples that qualify: `"Pool Install"`, `"New Install"`,
`"Landscape Install"`, `"install"`. Documented in a comment on
`_install_service_match()` — if a stricter workflow flag lands
later, this helper is the single point to tighten.

## Endpoint contracts

**Existing (extended)**:

- `POST /api/warranties/contracts` — accepts `linked_type` + `linked_id`.
- `PATCH /api/warranties/contracts/{cid}` — supports adding / clearing / re-linking.

**New (this phase, +3 OpenAPI paths → 1747 total)**:

- `GET /api/customers/me/warranties`  
  Portal read-only. Customer role only (admin gets 403 by design —
  the portal endpoint is not an admin fallback).  
  Query: `page`, `page_size`. Envelope:
  `{items[], page, page_size, total, total_pages}`.
- `GET /api/customers/{customer_id}/warranties`  
  Admin. Same envelope. 404 on unknown customer.
- `GET /api/customers/{customer_id}/warranties/link-options?type=install|equipment`  
  Admin only. Autopopulates the dependent dropdown in the Add /
  Edit modal.
  - `type=install` → returns `{id, title, service_date, service_type}[]`.
  - `type=equipment` → returns `{id, equipment_type, brand, model, serial_number}[]`.

Route ordering: `/customers/me/warranties` is declared **before**
`/customers/{customer_id}/warranties` so FastAPI matches `me`
literally and never treats it as a customer id.

## Frontend testid map

### Admin (`CustomerWarrantiesLibrary`)

| Element | testid |
|--------|--------|
| Section root | `customer-warranties-section` |
| Empty / loading / error states | `warranty-empty` / `warranty-loading` / `warranty-error` |
| List container | `warranty-list` |
| Card | `warranty-card-<i>` |
| Card name | `warranty-card-name-<i>` |
| Card coverage window | `warranty-card-window-<i>` |
| Card link summary chip | `warranty-card-link-<i>` |
| Card notes | `warranty-card-notes-<i>` |
| Card Edit / Cancel | `warranty-card-edit-<i>` / `warranty-card-delete-<i>` |
| Add button | `warranty-add-btn` |
| Add/Edit modal | `warranty-form-modal` |
| Modal close / cancel / submit | `warranty-form-close` / `warranty-form-cancel` / `warranty-form-submit` |
| Modal error | `warranty-form-error` |
| Plan (contract name) dropdown | `warranty-contract-name-input` |
| Provider — currently sourced from plan snapshot; no separate input |  |
| Coverage start / end | `warranty-coverage-start-input` / `warranty-coverage-end-input` |
| Linked type dropdown | `warranty-linked-type-select` |
| Linked id dependent dropdown | `warranty-linked-id-select` |
| Notes textarea | `warranty-notes-input` |

### Portal (`PortalWarranties`)

| Element | testid |
|--------|--------|
| Page root | `portal-warranties-section` |
| Empty / loading / error | `portal-warranty-empty` / `portal-warranty-loading` / `portal-warranty-error` |
| List container | `portal-warranty-list` |
| Card | `portal-warranty-card-<i>` |
| Card fields | `portal-warranty-card-name-<i>` / `portal-warranty-card-window-<i>` / `portal-warranty-card-link-<i>` / `portal-warranty-card-notes-<i>` |

## Test coverage

Backend (`backend/tests/test_warranty_contracts_linked.py`) — **20 tests passing**:

- Link validation × 7: install / equipment / none happy paths + 4 error paths (nonexistent install id, nonexistent equipment id, `none` with id, install id referencing a non-install job).
- Cross-tenant leak guard × 1.
- Admin customer-scoped list × 3 (envelope, unknown customer 404, customer role 403).
- Portal `/customers/me/warranties` × 2 (customer OK, admin 403).
- Link-options endpoint × 4 (install + equipment + role guard + invalid type).
- PATCH re-link × 3 (add link, clear link, reject bad link).

Frontend Vitest — **+8 new tests**:

- `customer-warranties-library.test.jsx` × 5 (empty, role-gated Add button, card render including `linked_summary`, POST body assertion via install autopopulate flow, `linked_type='none'` sends `linked_id: null`).
- `portal-warranties.test.jsx` × 3 (empty, hydrated linked_summary, hits `/customers/me/warranties`).

Existing suites — no regression. OpenAPI paths: **1744 → 1747 (+3)**.

## Mobile parity handoff notes

- Mobile client (`/app/mobile/`) currently has no warranties surface. When parity is delegated, the Expo dev agent should:
  1. Read the new admin endpoint `GET /api/customers/{customer_id}/warranties` for tech-role users viewing a customer profile.
  2. Read the portal endpoint `GET /api/customers/me/warranties` for customer-role users.
  3. Consume the same `linked_summary` shape — the display label is already server-side and ready.
  4. Skip the Add / Edit modal path for v1 mobile (admin edits stay on web).
- **Guardrail**: main agent MUST not modify `/app/mobile/` — mobile parity is the Expo agent's job.

## Out of scope

- Any A–F backlog items.
- Warranty PDF ingestion / attachment (follow-up if the user asks).
- Auto-populate of warranty contracts from install jobs (v1 is manual entry per phase spec).
- Adding a `provider` field distinct from `plan_name_snapshot` — the existing plan snapshot doubles as contract name and provider identity.
