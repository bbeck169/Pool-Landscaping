# Feature — Warranty Contracts (Mobile Parity)

**Phase**: Sep-2026 mobile parity of the web warranty contracts feature
**Scope**: Mobile only (`/app/mobile/`). Read-only v1 — no add/edit modals.

## Summary

Read-only warranty contracts list on two mobile surfaces:
1. **Customer portal** (`/portal/warranties`) — customer views their own warranties via `GET /api/customers/me/warranties`
2. **Admin/tech customer detail** — inline section on `app/customer/[id].tsx` via `GET /api/customers/{customer_id}/warranties`

Cards display contract_name, provider, coverage window, linked entity summary chip, and notes. Expired contracts show a red "EXPIRED" badge.

## Screens / Routes

| Screen | Route | API Endpoint |
|--------|-------|-------------|
| Portal Warranties | `app/portal/warranties.tsx` | `GET /api/customers/me/warranties` |
| Customer Detail Section | (inline in `app/customer/[id].tsx`) | `GET /api/customers/{customer_id}/warranties` |

## Files Created

| File | Purpose |
|------|---------|
| `src/components/warranties/WarrantyCard.tsx` | Shared read-only card component |
| `src/components/warranties/CustomerWarrantiesSection.tsx` | Inline section for customer detail |
| `app/portal/warranties.tsx` | Full portal screen for customer warranties |
| `__tests__/warranty-contracts-mobile.test.tsx` | 5 Jest test cases |

## Files Modified

| File | Change |
|------|--------|
| `app/portal/home.tsx` | Added "Warranties" entry to QA_SECTIONS navigation |
| `app/customer/[id].tsx` | Imported + mounted `CustomerWarrantiesSection` with `isAdminOrTech` gating |

## TestID Map

### Portal screen
| TestID | Element |
|--------|---------|
| `portal-warranties-screen` | Screen root |
| `portal-warranty-loading` | Loading spinner |
| `portal-warranty-error` | Error message |
| `portal-warranty-list` | FlatList |
| `portal-warranty-empty` | Empty state |
| `portal-warranty-card-<i>` | Each warranty card |
| `portal-warranty-card-name-<i>` | Contract name text |
| `portal-warranty-card-window-<i>` | Coverage date range |
| `portal-warranty-card-link-<i>` | Linked entity chip |
| `portal-warranty-card-notes-<i>` | Notes text |

### Customer detail section
| TestID | Element |
|--------|---------|
| `customer-warranties-section` | Section root |
| `warranty-loading` | Loading spinner |
| `warranty-error` | Error message |
| `warranty-empty` | Empty state text |
| `warranty-list` | Card list wrapper |
| `warranty-card-<i>` | Each warranty card |
| `warranty-card-name-<i>` | Contract name text |
| `warranty-card-window-<i>` | Coverage date range |
| `warranty-card-link-<i>` | Linked entity chip |
| `warranty-card-notes-<i>` | Notes text |

## Read-only Rationale (v1 Scope)

Per the web feature memo, add/edit modals involve complex linked-entity picker UX (linking warranties to equipment or installs). Mobile v1 ships as read-only; add/edit modals are deferred to v1.5.

## Backend Contract Coupling

- Response envelope: `{ items: WarrantyContract[] }` (paginated)
- Each item: `id`, `contract_name`, `provider`, `coverage_start`, `coverage_end`, `linked_type`, `linked_id`, `linked_summary: { type, label, details? }`
- See `/app/memory/FEATURE_WARRANTY_CONTRACTS.md` for full schema

## Auth

- Portal screen: customer session only (`/customers/me/warranties` returns 403 for non-customer users)
- Customer detail section: admin/super_admin/technician (gated by `isAdminOrTech`)

## Test Results

5/5 tests passing:
- WarrantyCard renders contract name, coverage window, and linked summary
- WarrantyCard renders EXPIRED badge for past-end contracts
- CustomerWarrantiesSection renders empty state
- CustomerWarrantiesSection renders warranty cards from API
- CustomerWarrantiesSection renders error state on API failure

## Dependencies
None new — uses existing theme, api, and widget imports.
