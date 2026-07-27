# Phase 34 · Tasks BB + CC — Bulk-select + Leads status enum (Mobile)

> Mobile Expo delegation brief. **Do not touch web/backend code**;
> the web + backend agent has already shipped these changes.

## Web + backend changes shipped (for context)

### Task BB — Bulk-select + mass delete on admin lists
Applied to **four** admin surfaces: Invoices, Estimates, Payments, Leads.
All read/write is admin-only (`require_admin` gate — admin/super_admin/
owner) and every soft-delete writes an `audit_log` row.

Backend endpoints:
* `POST /api/invoices/bulk-delete` — soft-deletes quote docs where
  `doc_type=invoice`. Sets `deleted_at` + `deleted_by_user_id`.
* `POST /api/estimates/bulk-delete` — soft-deletes `db.estimates` rows.
* `POST /api/payments/bulk-delete` — reverts the paid invoice back to
  `payment_status="unpaid"`, zeroes `amount_paid`, stamps
  `payment_deleted_at`. **Locks**: rows with `payment_intent_id` set
  (cleared to Stripe payout) OR method in {Card, Stripe} with
  `payment_status=paid` return in `failed[]` with a clear reason.
* `POST /api/leads/bulk-delete` — soft-deletes leads. **Locks**:
  `closed_won` leads with linked jobs/customers, and any lead with
  `open_task_ids` still populated.

Every endpoint accepts `{"ids": [...]}` (max 100) and returns
`{deleted_count, deleted[], failed: [{id, reason, status_code}]}`.

Frontend UX (uniform pattern across all four lists):
* Leftmost checkbox column with `data-testid="bulk-select-row-{id}"`.
* Header checkbox `data-testid="bulk-select-all"` with indeterminate
  state when some-but-not-all visible rows are selected.
* Sticky floating action bar (`data-testid="bulk-action-bar"`)
  appears at bottom-center on ≥1 selection with:
  * count "N selected" (`bulk-action-bar-count`)
  * red destructive "Delete selected" button (`bulk-delete-button`)
  * "Clear selection" link (`bulk-clear-selection`)
* Confirmation modal ("Delete N invoices? This can be restored from
  the archive.") — `bulk-delete-confirm`, submit `bulk-delete-confirm-btn`.
* Selection scope: currently-visible-page only (post filter). No
  "select all N matching" per the spec skip-if-complicates note.

### Task CC — Leads status enum standardization
The canonical Leads status enum is now exactly **five** snake_case
values, stored on `leads.status`:

| Value           | Label            | Color  |
|-----------------|------------------|--------|
| `new`           | New              | blue   |
| `contacted`     | Contacted        | amber  |
| `quoted`        | Quoted           | purple |
| `closed_won`    | Closed – Won     | green  |
| `closed_lost`   | Closed – Lost    | grey   |

Backend:
* `_CANONICAL_STATUSES` + `_STATUS_ALIASES` in `routers/leads.py` were
  rewritten. Any write funnels through `_normalize_status()` which
  maps every legacy value (`New`, `On Hold`, `converted`, `rejected`,
  `qualified`, etc.) to one of the five snake_case values (see the
  full mapping in the source). Unknown values fall back to `"new"`.
* Boot-time `migrate_lead_statuses()` sweep in `server.py` idempotently
  rewrites every row. First-run counts on preview:
  * `new`: 21
  * `contacted`: 1
  * `quoted`: 1
  * `closed_won`: 0
  * `closed_lost`: 2
  * `unknown`: 0

Frontend:
* `LeadsDashboardPage.jsx` — status filter dropdown, badge colors,
  and label lookup all pointing at the new enum.
* `LeadDetail.jsx` — action-button labels + StatusPill + status
  disable-checks all use snake_case values with the friendly labels
  above.

## Mobile parity tasks

### Bulk-select + mass delete
On the mobile admin app (if the Expo app has an admin Invoices /
Estimates / Payments / Leads surface):

1. Add a long-press or explicit "Select" mode to enter bulk mode.
2. In bulk mode, render a checkbox on each row and a top-of-screen
   header checkbox for select-all-on-page (indeterminate state).
3. Show a floating action bar at the bottom with:
   * count
   * "Delete selected" destructive button
   * cancel/clear button
4. Confirmation dialog ("Delete N invoices? This can be restored from
   the archive.").
5. Backend calls: use the four `bulk-delete` endpoints listed above.
6. Handle `failed[]` in the response — surface locked-row reasons
   (Stripe cleared, converted lead with linked customer, etc.) in a
   subsequent toast/dialog so admins know what didn't delete.
7. Scope-appropriate: the mobile app is primarily tech-facing, so
   these surfaces should only render for `admin | super_admin | owner`
   users. Non-admin roles should NEVER see the "Select" affordance.
8. `testID` naming: mirror the web `data-testid` conventions —
   `bulk-select-all`, `bulk-select-row-{id}`, `bulk-action-bar`,
   `bulk-delete-button`.

### Leads status enum
1. Rewrite every reference to the legacy status vocabulary
   ("New", "Contacted", "Quoted", "Closed Won", "Closed Lost",
   "On Hold", "converted", "qualified", "rejected") to the five
   snake_case values.
2. Status dropdown: five options in this order — `new`, `contacted`,
   `quoted`, `closed_won`, `closed_lost` — with the labels
   "New", "Contacted", "Quoted", "Closed – Won", "Closed – Lost".
3. Badge / pill colors: use the color mapping above.
4. Any dashboard tile / KPI (conversion rate, funnel counts) must
   read from the new enum. If a "conversion rate" formula was
   `won / (won + lost)`, keep it working with the new values.
5. Read-side: the backend now returns snake_case values, so the
   mobile app must render them via the label lookup — do NOT display
   the raw enum value to the user.

## Verification checklist
- [ ] Long-press → bulk mode on Invoices/Estimates/Payments/Leads.
- [ ] Header select-all with indeterminate state.
- [ ] Delete confirmation copy matches spec.
- [ ] Locked rows (Stripe payment, closed_won lead) show up in a
      toast with the returned `reason`.
- [ ] Leads status dropdown renders exactly five options with the
      correct labels + colors.
- [ ] Every lead status pill anywhere in the mobile app shows the
      friendly label ("Closed – Won"), never the raw snake_case value.
- [ ] Dashboards / funnel widgets read the new enum values.

Ship as a single mobile PR referencing this brief.
