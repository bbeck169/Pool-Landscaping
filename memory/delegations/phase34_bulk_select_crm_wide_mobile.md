# Phase 34 · Task LL Phase 2 — CRM-wide bulk-select rollout (Master mobile brief)

> Master delegation brief for the Expo mobile agent. The web +
> backend agent has already shipped ALL backend endpoints for the
> 7 approved P0 surfaces + digest KPIs. This brief covers mobile
> parity guidance for each surface.

## Standing contract (applies to every surface below)

Every bulk endpoint follows the same shape:
* `POST /api/{entity}/bulk-delete` (or `bulk-archive` for comms)
* `POST /api/{entity}/bulk-update` (allow-listed patch keys)

Both accept EITHER `{"ids": [...]}` OR `{"query_selector": {...}, "exclude_ids": [...]}` (Task EE). Both cap at 400 rows and require the `admin` / `super_admin` / `owner` role via `require_admin`. Responses use the shape `{ok, deleted_count | updated_count | archived_count, deleted | updated | archived, failed: [{id, reason, status_code}]}`. Locked rows land in `failed[]` — never cascade.

Every mobile bulk mutation MUST render a confirmation dialog matching the web copy exactly.

## Per-surface contracts

### 1. Customers / Contacts (`/customers/bulk-delete` + `/customers/bulk-update`)
* **Patch allow-list**: `tag`, `assigned_owner_id`.
* **query_selector keys**: `search`, `tag`, `assigned_owner_id`.
* **Locked-state**: customer with N active invoices → "Customer has N active invoice(s) — archive them first" (409).
* **Mobile scoping**: admins only.

### 2. Jobs / Work Orders (`/jobs/bulk-delete` + `/jobs/bulk-update`)
* **Patch allow-list**: `technician_id`, `status`, `scheduled_date`.
* **query_selector keys**: `search`, `status`, `technician_id`, `customer_id`.
* **Locked-state**:
  * Active timer running (`timer_started_at` set, no `timer_stopped_at`) → "Job has an active timer — stop the timer before deleting" (409).
  * Completed job with an invoice → "Completed jobs with an invoice cannot be bulk-deleted" (409).
* **Mobile scoping**: admins only. **Tech role must NEVER see bulk actions** even on the mobile job list.

### 3. Tasks / Follow-ups (`/tasks/bulk-delete` + `/tasks/bulk-update`)
* **Patch allow-list**: `assignee_id`, `status`, `due_date`.
* **query_selector keys**: `search`, `status`, `assignee_id`.
* **Locked-state**: none currently — the endpoint just soft-deletes.
* **Mobile scoping**: admins only.

### 4. Communications (`/communications/bulk-archive` + `/communications/bulk-mark-read`)
* **NO hard-delete endpoint** — audit trail is sacred. Only archive + mark-read.
* Only accepts `{"ids": [...]}` — no query_selector yet.
* **Mobile scoping**: admins only.

### 5. Email templates (`/email-templates/bulk-delete` + `/email-templates/bulk-update`)
* **Patch allow-list**: `category`, `is_archived`.
* **query_selector keys**: `search`, `category`.
* **Locked-state**: none currently. Future: refuse deletion when template is referenced by a live drip.
* **Mobile scoping**: admins only.

### 6. SMS templates (`/sms-templates/bulk-delete` + `/sms-templates/bulk-update`)
* **Patch allow-list**: `category`.
* **query_selector keys**: `search`, `category`.
* **Locked-state**: same as email templates.
* **Mobile scoping**: admins only.

### 7. Pricebook items (`/pricebook/bulk-delete` + `PATCH /api/items/{iid}`)
* Backend shipped in Task KK. Frontend polish (checkbox column + bulk-action-bar + inline row-edit / edit-modal + add-item + soft-delete icon) shipped web-side in this batch.
* **Locked-state**: item referenced by any active invoice / estimate / autobilling → "Item is used on N active document(s) — deactivate via PATCH instead of deleting" (409).
* **Patch allow-list on bulk-update (mobile-side to add if needed)**: `category`, `unit_price`, `cost`, `tax_rate`, `active`. (Note: web currently ships PATCH-per-row only; bulk-update endpoint for pricebook is an LL-P1 follow-up if mobile needs it.)
* **Mobile scoping**: admins only.

## Testid conventions (mirror on mobile `testID`)

Every mobile bulk-select surface should ship testIDs matching web:
* `bulk-select-all` (header checkbox)
* `bulk-select-row-{id}` (per row)
* `bulk-action-bar` (floating action bar container)
* `bulk-action-bar-count` (N selected label)
* `bulk-delete-button` (red destructive action)
* `bulk-clear-selection` (link)
* `bulk-delete-confirm-modal` (confirmation dialog)
* `bulk-delete-confirm-btn` / `bulk-delete-cancel`
* `bulk-status-change-button` (Leads only)
* `bulk-status-option-{value}` (Leads only)
* `bulk-edit-button` / `bulk-edit-modal` / `bulk-edit-confirm-btn` (all surfaces that support bulk-update)

## Weekly Bulk Actions Digest — engagement KPI section (mobile no-op)
Digest email is server-generated. Mobile has nothing to render — this section is FYI only. The digest now includes an "Engagement this week" block underneath the bulk-actions rollup with these lines (each shown only if count > 0):
* N customers opened an invoice
* N invoices paid — $X collected
* N customers submitted a review — avg N★
* N Google review CTA clicks
* N new leads captured
* N portal logins

Delivered every Monday at 08:00 UTC, routed through the Task-L guarded Resend adapter so preview stays dry-run.

## Verification checklist (per surface)
- [ ] Long-press or explicit "Select" mode enters bulk view.
- [ ] Checkbox column visible only in admin-role sessions.
- [ ] Header select-all with indeterminate state.
- [ ] Floating action bar appears when ≥1 selected.
- [ ] Confirmation dialog copy matches web.
- [ ] Locked-row `failed[]` reasons render in a follow-up toast/dialog.
- [ ] Allow-listed patch fields only — do NOT send unlisted keys (server drops silently but mobile should mirror to avoid confusion).
- [ ] Test coverage — snapshot tests for each surface's bulk-mode.

Ship as a single mobile PR referencing this brief.
