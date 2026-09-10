# Mobile Parity Gaps

## PB2 — Line-Item Cost/Category Overrides (Admin Editor)

**Date**: 2026-04-16
**Status**: DOCUMENTED GAP — NOT IMPLEMENTED

### Web Behavior
The web app provides an admin-only line-item editor (`K71LineItemsEditor`) on estimates/invoices with:
- `wholesale_cost_override` input per line
- `labor_cost_override` input per line
- `income_category_id_override` select per line
- `service_category_id_override` select per line
- Live margin recompute (`override ?? snapshot` semantics)
- Per-field reset buttons

### Mobile State
The mobile app has **NO admin line-item editor** for estimates or invoices. The mobile estimate view (`/app/mobile/app/estimate-view/[id].tsx`) is a **read-only viewer** with approve/decline actions. The mobile invoice view (`/app/mobile/app/invoice/[id].tsx`) is also read-only.

Line-item editing on mobile exists only for **jobs** (`/app/mobile/src/api/lineItems.ts`) — adding/updating/deleting pricebook-sourced items on an individual job. This does NOT include the PB2 override panel (wholesale/labor cost overrides, category overrides, live margin display).

### Required Test IDs (Not Implemented)
- `line-item-{wholesale,labor}-override-${i}`
- `line-item-{service,income}-category-select-${i}`
- `line-item-reset-{wholesale,labor,service-category,income-category}-${i}`
- `line-item-margin-display-${i}`

### Customer-Facing Mobile Views
Customer-facing mobile views do NOT surface any of the 4 override fields. The existing viewer endpoints (used by the mobile estimate-view and invoice detail screens) already strip override fields server-side, so no changes were needed.

### Recommendation
Adding PB2 overrides to mobile would require building a new admin estimate/invoice line-item editor component from scratch. This is a significant effort and should be scoped as a standalone feature pass.

---

## PB1 — Categories Admin Route

**Status**: SKIPPED per mission spec — "Not a mobile screen; mobile admin flows already limited."

The categories admin screen (`/pricebook/categories` on web) is intentionally not implemented on mobile. The mobile invoice viewer already resolves category display names via the shared `internal-margin-section` that computes margin from snapshot values on each line item.
