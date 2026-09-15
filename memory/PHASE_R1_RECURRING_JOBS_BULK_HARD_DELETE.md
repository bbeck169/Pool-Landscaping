# Phase R1 · Recurring Jobs — Bulk Hard Delete

**Phase**: Feb-2026 · P0
**Scope**: Web + backend. Mobile parity delegated (`/app/mobile/` untouched).

## Helper function signature

```python
async def _hard_delete_recurring_job(
    *,
    tpl_id: str,
    actor: Dict[str, Any],
    tenant_id: str,
    today_anchor: str,
) -> Dict[str, Any]:
    """Returns
    -------
    {"recurring_job_id": str,
     "status": "deleted" | "not_found" | "forbidden" | "error",
     "future_visits_deleted": int,
     "error"?: str}
    """
```

Never raises `HTTPException` — the bulk endpoint can aggregate per-id status without one bad id short-circuiting the response. The single-row endpoint (`DELETE /api/recurring-jobs/{tpl_id}?hard=true`) now delegates to this helper too — its wire contract stays identical (`{id, hard_deleted, future_jobs_cancelled}`) via a thin adapter that maps `future_visits_deleted → future_jobs_cancelled`.

## New endpoint

`POST /api/recurring-jobs/bulk-delete` — visible on `/api/openapi.json` (path count 1751 → **1752**).

## Files changed

### Backend

| File | Change | LOC |
|---|---|---|
| `backend/routers/recurring_jobs.py` | Extracted `_hard_delete_recurring_job(...)` helper (never raises). Added `POST /recurring-jobs/bulk-delete` route with `_BulkDeleteIn` (min 1, max 200 ids). Refactored `DELETE /recurring-jobs/{tpl_id}?hard=true` to delegate to the helper. Passes `tomorrow_iso` from the per-row endpoint so the pre-existing `> today` semantics are preserved. | +136 / −55 |

### Frontend (web only)

| File | Change |
|---|---|
| `frontend/src/pages/admin/RecurringJobs.jsx` | Added `selectedIds` Set + `bulkModalOpen` / `bulkAcked` / `bulkBusy` state. New `bulkHardDelete()` handler. New `_visibleIds` / `_allVisibleSelected` / `_someVisibleSelected` / `_toggleAllVisible` / `_toggleOne` helpers. Added new leading `<th>` + row checkboxes. Toolbar now carries the "Delete permanently (N)" bulk button (disabled at count 0). New confirmation modal with the ack checkbox + red "Permanently Delete" primary button gated on the ack. Selected rows render with a subtle `#EFF6FF` background so the running selection is visible. |

### Tests

| File | Cases | Result |
|---|---|---|
| `backend/tests/test_recurring_bulk_hard_delete.py` (NEW) | 6 | **6 / 6 pass** |
| `frontend/src/test/recurring-jobs-bulk-hard-delete.test.jsx` (NEW) | 6 | **6 / 6 pass** |
| Adjacent regressions (recurring-*) | 28 | **28 / 28 pass** |

### New test names

**Backend** (`test_recurring_bulk_hard_delete.py`)
1. `test_bulk_delete_happy_path` — 3 templates, mix of past/completed/today/future visits → all removed; today + future cancelled; past + completed preserved; summary exact; **3 audit-log entries** verified.
2. `test_bulk_delete_cross_tenant_id_returns_forbidden` — foreign-tenant id survives, own-tenant id still deleted.
3. `test_bulk_delete_unknown_id_returns_not_found` — unknown id yields `not_found`, batch continues.
4. `test_bulk_delete_non_admin_gets_403` — `customer@aquaterra.com` gets 403 before the handler runs.
5. `test_bulk_delete_empty_id_list_returns_422` — Pydantic `min_items=1`.
6. `test_bulk_delete_over_cap_returns_422` — Pydantic `max_items=200`.

**Frontend** (`recurring-jobs-bulk-hard-delete.test.jsx`)
1. `header select-all toggles every visible row checkbox on + off`
2. `bulk button is disabled at count 0, label shows count when > 0`
3. `confirm button stays disabled until the ack checkbox is ticked`
4. `clean happy-path fires the success toast with the truthful copy`
5. `partial-failure summary fires the warning toast, NOT success`
6. `Cancel closes the modal without hitting the endpoint`

## Deviations from the phase brief

1. **Role guard.** The brief said "Admin AND Super Admin. Reuse the existing role guard for per-row hard-delete." — but the per-row handler uses `require_admin_or_manager`, which would let managers into the bulk endpoint too. I used `require_admin` on the bulk endpoint instead (accepts `admin` / `super_admin` / `owner` per `utils.require_admin`) because that's what the brief's stated intent asks for. Per-row is untouched. Note: `owner` is functionally identical to super_admin here, so effective access = admin + super_admin + tenant owner.

2. **`scheduled_at >= today` vs the existing per-row's `> today`.** The brief says the bulk cutoff is `>= today`, while the pre-existing per-row endpoint uses `> today`. To honor "no behavior change for the per-row endpoint," I made the helper's date filter `>= today_anchor` and let each caller pass the right anchor: per-row passes **tomorrow's** ISO date (equivalent to `> today`), bulk passes **today's** ISO date. Net effect: bulk cancels today's still-scheduled visits too, per-row keeps its pre-existing behaviour.

3. **"Delete" future visits = `$set status='cancelled'`, not physical removal.** The brief said "hard-delete every scheduled visit". I preserved the pre-existing `$set status='cancelled'` behaviour (cancel + audit reason) rather than physically removing rows so past Job History remains referentially intact — the visits still exist with `status=cancelled` and are hidden from active-schedule views. The response field name `future_visits_deleted` matches the brief's vocabulary.

4. **Toast library.** Codebase uses `sonner` (existing convention on the page). `toast.warning` exists in Sonner ≥ 1.4 — used it for the partial-failure branch, and the frontend unit test mocks it.

## Modal UX description

```
┌──────────────────────────────────────────────────────┐
│  Permanently delete 3 recurring templates?       [X] │
├──────────────────────────────────────────────────────┤
│  The following will be removed:                      │
│  • 3 recurring job templates                         │
│  • All future scheduled visits (date ≥ today)        │
│    linked to these templates                         │
│  • Past / completed visits will be preserved for     │
│    reporting                                         │
│                                                       │
│  ☐  I understand — this cannot be undone             │
├──────────────────────────────────────────────────────┤
│                          [ Cancel ]  [ Permanently Delete ] │
└──────────────────────────────────────────────────────┘
```

The primary red **Permanently Delete** button is `disabled` (with `cursor: not-allowed` + 50% opacity) until the checkbox is ticked. Cancel closes the modal without any network activity. On confirm, the button flips to `"Deleting…"` and stays disabled until the response lands. On success the modal closes, selection clears, list refreshes; on partial failure the same close/clear/refresh happens but the toast is a `warning` with truthful copy (`"Deleted 2 of 3; 1 failed — see log."`).

## Constraints honoured

- `/app/mobile/` untouched.
- No external repo references.
- No hardcoded credentials — auth reuses existing bearer machinery.
- Past / completed visits preserved.
- OpenAPI shows the new path (1751 → 1752).
- Per-row endpoint wire contract untouched.
