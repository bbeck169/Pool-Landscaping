# FOLLOWUP · Dashboard Drilldown tenant isolation backfill

## Discovered during
Data Integrity hard-delete task (recon surprise S1, 2026-02)

## Issue
`routers/dashboard_drilldown.py::_apply_resolve_item` uses
`db.jobs.find_one({"id": job_id})` and
`db.jobs.update_one({"id": job_id}, ...)` without `tenant_id` in the
filter. Cross-tenant isolation today is enforced only indirectly:
`_scan_dangling_refs` (upstream) is tenant-scoped, so a benign UI
never surfaces a cross-tenant job_id in the modal. A malicious admin
submitting a foreign `job_id` directly to
`POST /dashboard/data-integrity/resolve` would mutate cross-tenant.

## Applies to (branches NOT touched by the Feb-2026 hard-delete phase)
- `orphaned_customer_refs` · soft-delete action (`action == "delete"`)
- `orphaned_customer_refs` · assign-customer action (`action == "assign"`)
- `orphaned_technician_refs` · assign-technician action
- `orphaned_technician_refs` · null-out-technician action (`action == "delete"`)
- `unassigned_pending_jobs` · assign-technician action

## Recommended fix
Thread the caller's `tenant_id` into `_apply_resolve_item` (already
plumbed for the hard-delete branch per Feb-2026) and use it in the
find/update filters for every non-hard-delete branch as well. The
hard-delete branch is already tenant-scoped and can serve as the
reference implementation.

```python
find_filter = {"id": job_id, "tenant_id": tenant_id}
job = await db.jobs.find_one(find_filter, ...)
...
await db.jobs.update_one(find_filter, {"$set": {...}})
```

## Priority
P2 — not exploitable via the UI (the scan is tenant-scoped, so the
modal never surfaces cross-tenant job_ids). Exploitable via direct
API call by an authenticated admin with knowledge of foreign
`job_id` values. Non-critical because:
- The mutations are AUDITED (`dashboard_drilldown_edit` records the
  mutating tenant AND the row's tenant).
- The K41c undo path can reverse them (10-minute window).
- Admin-role gate is upstream (403 for non-admin).

## Coordinated tests
Extend `backend/tests/test_k41_dashboard_drilldown.py` with a new
`class TestCrossTenantIsolation` covering:
- Soft-delete a foreign customer-orphan job → expect 404 or 403.
- Assign a foreign job to a customer → expect 404 or 403.
- Assign a foreign job to a technician → expect 404 or 403.

Model on the existing test infrastructure in
`test_data_integrity_drilldown_tenant.py` (which currently covers
the read paths).

## Related landing
- `ce5bfb130` — Marketing Forms Phase 3 (unrelated context marker)
- Feb-2026 · Data-Integrity hard-delete phase (this session) —
  the hard-delete branch established the tenant-filter pattern.
