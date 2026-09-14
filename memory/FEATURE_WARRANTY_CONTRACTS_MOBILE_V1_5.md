# Feature — Warranty Contracts Mobile v1.5 (CRUD Upgrade)

**Phase**: Sep-2026 · v1.5 upgrade from read-only to full CRUD
**Scope**: Mobile only (`/app/mobile/`). Backend unchanged.

## Summary

Upgrades the admin/tech customer-detail warranties section from read-only (v1)
to full CRUD. Portal warranties stays read-only per v1.5 scope — customer-side
editing deferred to v2.

## Screens / Routes

| Screen | Route | CRUD Level |
|--------|-------|-----------|
| Admin/tech customer detail | `app/customer/[id].tsx` (inline section) | Full CRUD |
| Customer portal | `app/portal/warranties.tsx` | Read-only (v1 posture) |

## CRUD Implementation

### Add Warranty
- "Add Warranty" button at the top of the section (`warranty-add-btn`)
- Modal form with: Contract Name, Provider, Coverage Start/End, Linked Entity Type (none/install/equipment), Linked Entity ID (dependent dropdown), Notes
- Submits to `POST /api/warranties/contracts`

### Edit Warranty
- Edit icon button per card (`warranty-edit-btn-<i>`)
- Reuses same modal, prefilled with existing data
- Submits to `PATCH /api/warranties/contracts/{cid}`

### Delete Warranty
- Delete icon button per card (`warranty-delete-btn-<i>`)
- Confirmation modal before firing
- Calls `DELETE /api/warranties/contracts/{cid}`

### Linked Entity Picker
- Type dropdown: None / Install Job / Equipment
- Dependent dropdown populated from `GET /api/customers/{customer_id}/warranties/link-options?type=install|equipment`
- Hidden when linked_type is "none"

## Portal Read-Only Decision (v1.5)

The portal warranties screen intentionally stays read-only. Rationale:
1. No tenant setting flag exists to control customer-side warranty management
2. Warranty CRUD on customer-facing portal requires additional UX review (confirmation flows, edge cases)
3. Admin/tech screen is the primary CRUD surface per the web implementation
4. Customer-side edit deferred to v2

## API Endpoints Used

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/customers/{cid}/warranties` | List |
| POST | `/warranties/contracts` | Create |
| PATCH | `/warranties/contracts/{cid}` | Update |
| DELETE | `/warranties/contracts/{cid}` | Soft-delete |
| GET | `/customers/{cid}/warranties/link-options?type=...` | Dependent dropdown |

## TestID Map

| TestID | Element |
|--------|---------|
| `warranty-add-btn` | Add Warranty button |
| `warranty-edit-btn-<i>` | Edit button per card |
| `warranty-delete-btn-<i>` | Delete button per card |
| `warranty-modal` | Add/Edit modal |
| `warranty-contract-name-input` | Contract name text input |
| `warranty-provider-input` | Provider text input |
| `warranty-coverage-start-input` | Coverage start date input |
| `warranty-coverage-end-input` | Coverage end date input |
| `warranty-linked-type-select` | Linked type picker |
| `warranty-linked-id-select` | Linked ID dependent picker |
| `warranty-notes-input` | Notes multiline input |
| `warranty-modal-save-btn` | Save button |
| `warranty-modal-cancel-btn` | Cancel / close button |
| `warranty-form-error` | Form error message |
| `warranty-delete-confirm-modal` | Delete confirmation modal |
| `warranty-delete-confirm-btn` | Confirm delete button |
| `warranty-delete-cancel-btn` | Cancel delete button |

## Files Modified

| File | Change |
|------|--------|
| `src/components/warranties/WarrantyCard.tsx` | Added optional `onEdit`/`onDelete` props for action buttons |
| `src/components/warranties/CustomerWarrantiesSection.tsx` | Full CRUD rewrite: add/edit modal, delete confirmation, linked entity picker |
| `__tests__/warranty-contracts-mobile.test.tsx` | Added 4 new CRUD tests (total 9) |

## Test Coverage — 9 tests

Existing (v1):
1. Card renders contract name, coverage window, linked summary
2. Card renders EXPIRED badge
3. Section empty state
4. Section renders cards from API
5. Section error state

New (v1.5):
6. Add Warranty button opens form modal with all fields
7. Form submit POSTs correct payload to `/warranties/contracts`
8. Edit/Delete buttons render per card
9. Delete confirmation flow calls `DELETE /warranties/contracts/{id}`

## Dependencies
None new.
