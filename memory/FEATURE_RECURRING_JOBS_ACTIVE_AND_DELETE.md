# FEATURE — Recurring Jobs · `is_active` gate + `start_date` invariant + two delete actions

**Phase:** Web · Preview only  
**Scope:** Backend (model + validation + generator gate + hard-delete + migration) · Web frontend (list badge + active toggle + hard-delete modal) · Tests · Docs.  
**Out of scope:** Mobile Expo parity (delegated to `e1_expo_frontend_dev` after web verification) · Auto-assign / recommend-schedule (future phase) · A–F backlog items.

## Schema delta

`RecurringJobIn` / `RecurringJobPatch` (`backend/routers/recurring_jobs.py`):

- **New** `is_active: bool` — default **`False`** on the create schema, `Optional[bool] = None` on the patch schema. This is the new generator gate.
- **Legacy** `active: bool = True` — unchanged, kept for backward compatibility with existing UI and API consumers (the "Pause / Resume" and "Active / Paused" chip still bind to it).
- `start_date` — was already required on `RecurringJobIn`; unchanged. Migration seeds it from `created_at.date()` on rows where both fields are missing.

## Generator gate

Both the nightly cron (`run_recurring_job_generator`) and the manual `POST /recurring-jobs/{id}/generate` action now honor:

```python
is_active == True   AND   start_date is set
```

**Nightly cron** additionally enforces `start_date <= today` — a template scheduled for a future kickoff sits idle until its start date arrives.

**Manual `/generate` endpoint** relaxes to only require `start_date` to be set (any date). This preserves the historical pre-materialization use case — the operator supplies `through=...` explicitly and can seed future occurrences.

**Tolerant read filter** — the nightly cron picks up EITHER `is_active: True` OR the legacy `active: True` when `is_active` is missing, so pre-migration templates keep generating during the rollout window. The migration then stamps `is_active` on every row, and the tolerant `$exists: false` branch becomes a no-op.

## Migration

`backend/services/migrations/recurring_templates_is_active_backfill.py` — idempotent, wired into `backend/server.py` startup via `step("recurring_is_active_backfill", …)` next to the other Feb-2026 migrations.

Algorithm:

```
for row in recurring_job_templates where is_active NOT EXISTS:
    set is_active = bool(row.active)          # legacy default was True
    if row.start_date is missing AND row.created_at:
        set start_date = row.created_at[:10]  # YYYY-MM-DD slice
```

**Live-preview boot log:** `[migration:recurring_is_active_backfill] scanned=36 is_active_backfilled=36 start_date_backfilled=0`.

Second-run idempotency verified by `test_migration_is_idempotent_on_second_run` — subsequent invocations find zero candidates and return `{scanned: 0, backfilled: 0, start_date_backfilled: 0}`.

## Endpoint contracts

| Route                                            | Behavior                                                                                                  |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| `POST /api/recurring-jobs`                       | New records default `is_active=false`. Rejects `is_active=true` + missing `start_date` with **422** `start_date_required_for_active` (defense-in-depth — Pydantic already requires `start_date` on the create body). |
| `PATCH /api/recurring-jobs/{id}`                 | Rejects `is_active=true` when neither the patch nor the existing doc carries a `start_date` — **422** `start_date_required_for_active`. |
| `DELETE /api/recurring-jobs/{id}`                | **SOFT delete** (unchanged). Flips `active=false` AND `is_active=false`. Row survives in Mongo so historical children keep resolving. |
| `DELETE /api/recurring-jobs/{id}?hard=true`      | **HARD delete**. Physically removes the template row, cancels every child job with `status=scheduled AND scheduled_date > today` (completed / in-progress / today's route preserved), and writes an `audit_logs` entry with a target snapshot + `future_jobs_cancelled` counter. |
| `POST /api/recurring-jobs/{id}/generate`         | Rejects with **404 `template not found or inactive`** when the gate is off; rejects with **422 `start_date_required_for_active`** when `start_date` is missing. |

**OpenAPI paths: 1736 → 1736** (unchanged — hard delete reuses the same DELETE path with a query flag, no new route).

## Frontend testid map

`frontend/src/pages/admin/RecurringJobs.jsx`:

- `recurring-job-soft-delete-btn-<id>` — outline red button, existing soft-delete flow (`DELETE /recurring-jobs/{id}`).
- `recurring-job-hard-delete-btn-<id>` — solid red button, opens the confirmation modal (does NOT hit the API on click).
- `recurring-job-hard-delete-confirm-modal` — modal root; title "Permanently delete this recurring job?" + body "This removes the recurring template AND cancels any future scheduled jobs derived from it. Completed jobs will not be affected. This cannot be undone."
- `recurring-job-hard-delete-cancel-btn` — safe dismiss (outline).
- `recurring-job-hard-delete-confirm-btn` — destructive confirm (solid red); fires `DELETE /recurring-jobs/{id}?hard=true`.
- `recurring-job-inactive-badge-<id>` — orange chip, rendered only when `is_active === false`. Coexists with the existing "Paused" chip (legacy `active=false`) when both flags are off.
- `recurring-job-active-toggle` — checkbox in the create/edit modal. Disabled when `start_date` is empty; hint reads "Requires start date" until the date is set.
- `recurring-job-start-date-input` — canonical start-date input (renamed from the legacy `recurring-jobs-start` testid on the same input for parity with the new naming convention; the input's runtime behavior is unchanged).

## Tests

### Backend — `backend/tests/test_recurring_is_active_and_hard_delete.py`
1. `test_migration_backfilled_existing_records_to_is_active_true` — every row carries the field after the boot migration.
2. `test_migration_is_idempotent_on_second_run` — 0 rows on re-run.
3. `test_patch_is_active_true_without_start_date_returns_422` — 422 with `start_date_required_for_active`.
4. `test_generator_skips_is_active_false_templates` — `POST /generate` → 404 on an inactive template.
5. `test_soft_delete_marks_inactive_but_row_survives` — DELETE without `hard` flag keeps the row.
6. `test_hard_delete_removes_template_and_cancels_future_children` — full 3-fixture matrix (future / completed / today) verifying only future-scheduled children are cancelled, template row is gone, audit entry written.
7. `test_hard_delete_unknown_id_returns_404`.

### Backend regression fix — `backend/tests/test_recurring_quarterly_semiannual_p47.py`
- `_mk_template` fixture now sends `is_active: true` explicitly so the P47 quarterly / semi-annual test suite still exercises the manual-generate branch under the new default-off contract.

### Frontend — `frontend/src/test/recurring-jobs-is-active-and-hard-delete.test.jsx`
1. Both soft + hard delete buttons render with correct testids.
2. Inactive badge only when `is_active === false`.
3. Clicking hard-delete opens the confirmation modal (no API call yet).
4. Cancel dismisses the modal without firing DELETE.
5. Confirm fires `DELETE /recurring-jobs/{id}?hard=true`.
6. Soft delete fires `DELETE /recurring-jobs/{id}` and never opens the hard-delete modal.

### Suite status

- **Backend pytest** — `test_recurring_is_active_and_hard_delete.py` + adjacent recurring-jobs surface: **41 passed / 0 failed** (previous unrelated `test_recurring_jobs_nth_weekday_role_gate.py` "customer not found" pre-existing seed drift verified via `git stash`).
- **Frontend Vitest — full suite: 575 files, 4321 passed / 34 skipped / 0 failed** (net +6 tests).
- **OpenAPI paths: 1736** (unchanged).

## Mobile parity hand-off notes

For `e1_expo_frontend_dev`:

- Read the new `is_active` field from `GET /api/recurring-jobs` and `GET /api/recurring-jobs/{id}` responses. Render an "Inactive" badge parallel to the existing "Paused" chip.
- Add an "Active" switch + start-date field to the create/edit surface. Disable the switch while start_date is empty; treat `is_active=false` as the default for new records.
- Add a second, visually destructive "Delete permanently" button. Show a native `Alert` (title / body / Cancel / Delete permanently) mirroring the web modal copy verbatim. Fire `DELETE /api/recurring-jobs/{id}?hard=true` on confirm.
- Testid convention (Expo): mirror the web names — `recurring-job-hard-delete-btn-<id>`, `recurring-job-hard-delete-confirm-btn`, `recurring-job-hard-delete-cancel-btn`, `recurring-job-inactive-badge-<id>`, `recurring-job-active-toggle`, `recurring-job-start-date-input`.
- Auth: both delete actions are `admin` / `super_admin` only; the mobile UI must hide both buttons for `role === "technician"`.

## Files touched

- `backend/routers/recurring_jobs.py`
- `backend/services/migrations/recurring_templates_is_active_backfill.py` (new)
- `backend/server.py` (migration wire-up)
- `backend/tests/test_recurring_is_active_and_hard_delete.py` (new)
- `backend/tests/test_recurring_quarterly_semiannual_p47.py` (fixture opt-in to `is_active: true`)
- `frontend/src/pages/admin/RecurringJobs.jsx`
- `frontend/src/test/recurring-jobs-is-active-and-hard-delete.test.jsx` (new)
- `memory/FEATURE_RECURRING_JOBS_ACTIVE_AND_DELETE.md` (this doc)
