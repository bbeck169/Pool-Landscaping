# Delegation Brief · e1_expo_frontend_dev · Phase 28

**From:** Web team (Phase 28 · Feb 2026)
**To:** Expo mobile frontend
**Priority:** P1
**Status:** Web slice shipped in preview. Mobile parity blocked on your side.

## Context
We just shipped multi-select **bulk reassign** on the web schedule page:

- **Backend endpoint (live in preview):** `POST /api/jobs/bulk-reassign`
  - Auth: `require_admin` (super_admin or admin)
  - Body: `{"job_ids": ["uuid", "..."], "new_tech_id": "tech_id_or_technician_id"}`
  - `new_tech_id` accepts either `users.technician_id` (preferred) OR `users.id` — backend resolves both.
  - Target user MUST have a tech-family role: `pool_tech`, `landscape_tech`, `technician`, or `tech`. Any other role → HTTP 400.
  - Cap: 100 job_ids per call.
  - Writes an `audit_log` row per successful reassign (`action: "job.reassign"`, `old_tech_id`, `new_tech_id`).
  - Writes **in-app notifications** (bell channel only — NO SMS, NO email) to:
    - The **new** tech: title `"You've been assigned N job(s)"`, body = first 3 job titles + `+N more` if applicable.
    - Each **old** tech (deduped): title `"N job(s) reassigned away from you"`, body = first 3 titles + `+N more`.
  - Response: `{"ok": true, "count": N, "reassigned": [ids], "failed": [{job_id, reason, status_code}], "new_tech_id": "...", "new_tech_name": "..."}`
  - No customer notifications (customers get their existing "tech assigned" flow if the tenant has it wired — we don't fire new emails/SMS).

- **Web UX shipped:**
  - Schedule grid multi-select already existed (checkboxes).
  - Selection toolbar (`data-testid="grid-selection-toolbar"`) now includes an "Assign tech ▾" button (`grid-selection-assign`) next to the existing "Delete N" button.
  - Clicking opens a dropdown (`grid-selection-assign-menu`) listing only tech-family users.
  - Picking a tech opens a confirm modal (`grid-bulk-reassign-modal`) with title "Reassign N job(s) to <tech name>?" and copy: "The previously-assigned tech (if any) will get an in-app notification. No SMS or email is sent to the customer."
  - Confirm button (`grid-bulk-reassign-confirm`) POSTs to `/api/jobs/bulk-reassign` and toasts `"N job(s) reassigned to <tech name>"` on success.

## Ask
Add the same bulk-reassign affordance to the Expo schedule multi-select flow.

## Behavior spec
1. On the mobile schedule screen — when multi-select mode is active AND ≥1 job is checked AND the current user is `admin` or `super_admin` — show a **"Assign tech"** action alongside the existing "Delete" bulk action.
2. Tap opens a picker sheet listing techs. Filter client-side to `pool_tech | landscape_tech | technician | tech` roles. Fetch techs via the existing team-listing endpoint your app already uses; do NOT introduce a new one.
3. Picking a tech opens a native confirm dialog:
   - Title: `Reassign {N} job(s) to {tech_name}?`
   - Body: `The previously-assigned tech will get an in-app notification. No SMS or email is sent to the customer.`
   - Actions: "Cancel" (default) · "Reassign" (primary).
4. On confirm, POST to `${EXPO_PUBLIC_BACKEND_URL}/api/jobs/bulk-reassign` with the auth header the app already sends, body `{job_ids, new_tech_id}`.
5. On `200 OK`:
   - Read the response — surface a toast `${count} job(s) reassigned to ${new_tech_name}`.
   - If `failed.length > 0`, toast with error variant instead: `Reassigned ${count} of ${total}, ${failed.length} failed`.
   - Clear the multi-select set and refresh the schedule list.
6. On `4xx` / `5xx`, toast the server-provided detail; do NOT clear the selection so the user can retry.

## data-testid parity (match web contract)
- `grid-selection-assign`
- `grid-selection-assign-menu`
- `grid-selection-assign-tech-{tech_id}`
- `grid-bulk-reassign-modal`
- `grid-bulk-reassign-confirm`
- `grid-bulk-reassign-cancel`

## Guardrails
- Do NOT hardcode URLs — use `EXPO_PUBLIC_BACKEND_URL`.
- Do NOT modify the existing bulk-delete flow — this is purely additive.
- Do NOT fire SMS or email from the mobile side; the backend handles bell-channel notifications on its own.
- Do NOT introduce new backend endpoints — the API contract is stable.
- Do NOT touch `/app/` from the mobile workspace.

## Web references
- Backend source: `/app/backend/routers/jobs.py::bulk_reassign_jobs`
- Web schedule toolbar: `/app/frontend/src/pages/schedule/CalendarSchedule.jsx` (search for `Phase 28 · Feb-2026`)
- Vitest coverage: `/app/frontend/src/test/phase28-bulk-reassign-toolbar.test.jsx`
- Pytest coverage: `/app/backend/tests/test_phase28_slider_and_bulk_reassign.py`

## Deployment
Backend is live on preview and will be live on prod after the next web deploy (user handles). No mobile-side deploy is needed until this ships in a normal Expo release.
