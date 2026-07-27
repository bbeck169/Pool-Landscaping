# Phase 34 · Task HH — Bulk lead status change (Mobile)

> Mobile Expo delegation brief. **Do not touch web/backend code**;
> the web + backend agent has already shipped this change.

## Web + backend changes shipped (for context)
Backend: `POST /api/leads/bulk-update-status`
* Payload: `{ids: [...], new_status: "closed_won"}` OR
  `{query_selector: {...}, exclude_ids: [...], new_status: "..."}`.
* `new_status` must be one of the five canonical values (Task CC):
  `new`, `contacted`, `quoted`, `closed_won`, `closed_lost`.
  Anything else → 422.
* Role gate: `admin` / `super_admin` / `owner`.
* Tenant scoped. 400-row cap (Task DD).
* Writes `lead.bulk_status_change` audit log rows with
  `{from_status, to_status, actor_id, at}`.
* Response: `{updated_count, updated[], failed[]}`. Leads already at
  `new_status` land in `failed[]` with reason `"already <status>"`
  — informational, not an error.

Frontend (`LeadsDashboardPage.jsx`):
* New "Change status" dropdown button (`data-testid="bulk-status-change-button"`)
  in the existing bulk-action-bar alongside "Delete selected".
* Menu (`bulk-status-menu`) shows exactly five options in canonical
  order with `data-testid="bulk-status-option-{value}"`. Each option
  renders a colored dot matching the badge palette.
* Confirmation modal (`bulk-status-confirm-modal`): "Change N leads to
  '{label}'? This will overwrite existing statuses. Leads already at
  '{label}' will be skipped."
* Confirm button `bulk-status-confirm-btn`; cancel
  `bulk-status-confirm-cancel`.
* Success toast: "N leads updated to {label}".

## Mobile parity task
On the mobile admin Leads screen:

1. In bulk-select mode (see the Task BB + CC master brief), extend the
   floating action bar to include a "Change status" secondary action
   next to the existing "Delete selected".
2. Tap → opens a bottom sheet with the five canonical options in
   fixed order (labels: "New", "Contacted", "Quoted", "Closed – Won",
   "Closed – Lost"). Use the same color mapping as the Task CC brief.
3. Selecting an option opens a confirmation dialog matching the web
   copy: "Change N leads to '{label}'?".
4. On confirm, POST to `/api/leads/bulk-update-status` with
   `{ids, new_status}`. Handle the `updated_count` + `failed[]`
   response — toast a summary that includes "N already at {status}"
   for the failed rows.
5. `testID` naming: mirror `bulk-status-change-button`,
   `bulk-status-option-{value}`, `bulk-status-confirm-modal`,
   `bulk-status-confirm-btn`.

## Verification checklist
- [ ] Bulk mode → "Change status" button visible next to Delete.
- [ ] Menu shows exactly five options in the correct order.
- [ ] Confirm modal copy matches web.
- [ ] Successful update: rows refresh with the new status badge.
- [ ] `failed[]` "already <status>" reasons surface in a toast.
- [ ] Non-canonical `new_status` never leaves the client (defence in
      depth — the backend also 422s).

Ship as a single mobile PR referencing this brief.
