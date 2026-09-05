# Phase K41d · Bulk Operations audit tile — SHIPPED

**Feb-2026 · P2 · Additive backend fields + one admin dashboard tile · Zero new endpoints**

---

## Scope (per brief)

> Add a tile to the admin dashboard: **"Last 24h: N bulk actions · X undone · Y expired"**, wired against the existing `dashboard_drilldown_edit` + `dashboard_drilldown_bulk_undone` indexed audit events. Zero new endpoints.

Delivered exactly.

## Files changed

| Layer | File | Kind |
|---|---|---|
| Backend | `backend/routers/dashboard.py` | +72 lines · additive aggregation inside the existing `/api/dashboard` handler. Three new fields on the response: `bulk_actions_24h`, `bulk_actions_undone_24h`, `bulk_actions_expired_24h`. |
| Frontend | `frontend/src/components/admin/BulkOpsAuditTile.jsx` | NEW · compact tile component. Self-hides on mixed-version rolls (backend older than K41d). Data-testids: `bulk-ops-audit-tile`, `-total-value`, `-undone-value`, `-expired-value`. |
| Frontend | `frontend/src/pages/admin/Dashboard.jsx` | +12 lines · import + one gated render slot immediately below `DataIntegrityTile`. Role gate: `super_admin` / `admin` / `owner`. |
| Tests | `backend/tests/test_k41d_bulk_ops_audit_tile.py` | NEW · 2 pytest cases against the live server. |

## Semantics

- **`bulk_actions_24h`** — distinct `bulk_batch_id` in `dashboard_drilldown_edit` events within the last 24h, scoped to `tenant_id`.
- **`bulk_actions_undone_24h`** — distinct `undone_from_batch_id` in `dashboard_drilldown_bulk_undone` events within the last 24h, scoped to `tenant_id`. Always ≤ `bulk_actions_24h`.
- **`bulk_actions_expired_24h`** — batches whose newest edit is older than the 10-minute undo window AND which have no undo companion. Explicitly excludes batches still inside the undo window (those are actionable, not expired).

**Invariant** (asserted in the test): `undone + expired ≤ total`.

## No new endpoints

The three fields are additive columns on the existing admin `/api/dashboard` payload — same handler, same auth gate, same caching semantics. No new routes registered.

## No new indexes

Backed by the compound indexes shipped in K41c (`audit_events` on `event_type + tenant_id + timestamp + bulk_batch_id`). The two `distinct()` calls and the one `aggregate()` all hit this index.

## Test evidence

```
$ cd /app/backend && python -m pytest tests/test_k41d_bulk_ops_audit_tile.py --tb=short
collected 2 items
tests/test_k41d_bulk_ops_audit_tile.py ..                                [100%]
============================== 2 passed in 3.84s ===============================

$ python -m pytest tests/test_k41d_bulk_ops_audit_tile.py \
    tests/test_k41c_undo_bulk.py tests/test_k41_dashboard_drilldown.py \
    tests/test_k41b_bulk_resolve.py tests/test_k43_ach_verification.py --tb=line
=================== 48 passed, 7 skipped, 1 warning in 4.42s ===================
```

## Visual confirmation

```
$ playwright · super@aquaterra.com → /
K41d TILE FOUND · total=2 undone=1 expired=1
```

Numbers reflect **real ambient audit-event activity** in the tenant from prior
`test_k41c_undo_bulk.py` runs (two batch UUIDs from ~4h ago; one has an undo
companion, one doesn't and is now > 10 min old). NOT fixture-seeded data —
the K41d test's own fixtures are cleaned up in `finally`.

## Non-goals

- No changes to bulk-resolve / bulk-undo endpoints.
- No changes to the `DataIntegrityTile` above it.
- Tile shows nothing (returns `null`) if the backend hasn't shipped K41d yet — safe for mixed-version rolls during a canary.

## Files changed / added

```
 M backend/routers/dashboard.py
 M frontend/src/pages/admin/Dashboard.jsx
?? backend/tests/test_k41d_bulk_ops_audit_tile.py
?? frontend/src/components/admin/BulkOpsAuditTile.jsx
```

## Queue status

- [x] **K45** — Mobile white screen on Schedule. Shipped.
- [x] **K43** — ACH bank verification / Financial Connections. Shipped.
- [x] **K41d** — Bulk Operations audit tile. Shipped (this phase).
