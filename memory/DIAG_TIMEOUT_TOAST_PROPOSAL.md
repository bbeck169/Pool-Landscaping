# DIAGNOSTIC — Recurring 30s "Request timed out" red toast + Customers / Schedule slow-load pivot

**Status:** ✅ **SHIPPED — Feb-2026**

Phase 1 landed all three deliverables (customer-search fix, ambient
timeout telemetry, schedule/dispatch index coverage) plus a bonus
follow-up (admin rebuild endpoint + tenant-scoped backfill logging).

## Root cause

### 1. Customer-search 30s timeout (`GET /api/customers?search=lynn`)

The list handler OR'd a case-insensitive `$regex` across six fields
(`name` / `first_name` / `last_name` / `email` / `phone` / `address`)
per token. Mongo cannot use any single index for that shape, so
every request COLLSCAN'd the whole tenant partition six times
(twelve times including the K68 `$facet` for the tab counts). On a
prod tenant with **1 931 customers** the cost peaked past the
frontend's 30 s `fetch` abort → the "Request timed out" toast.

### 2. Schedule + Dispatch slow-load (`/schedule`)

Two shapes were unindexed:

| Endpoint | Query shape (relevant clause) | Index status BEFORE |
|-|-|-|
| `GET /api/schedule/today` | `{$or:[technician_id, assigned_technician_id, assigned_to, crew_id]}` + `scheduled_date` range | ✅ K15 covered `technician_id` + `crew_id` — but `assigned_technician_id` and `assigned_to` COLLSCAN'd |
| `GET /api/dispatch/board` | `{tenant_id, service_lat:{$exists,$ne:null}, service_days, $or:[category_ids, tags:$regex]}` — twice per request (pins + unrouted) | ❌ no `(tenant_id, service_lat)` / `(tenant_id, service_days)` / `(tenant_id, assigned_tech_ids)` |

Both endpoints already batch their fanouts (customer / user / distance-matrix pre-loads are single `$in`), so the *only* remaining bottleneck was index coverage.

## Fix

### Task 1 — Customer search
* New lowercase concatenated `customers.search_haystack` field
  built at write time (create + update + merge paths).
* Compound index `(tenant_id, search_haystack)` — one regex sweep
  per token against a single field vs. six.
* Legacy OR arm retained as fallback for un-backfilled docs (dead
  code within 60 s of a rolling deploy).
* Boot-time auto-backfill wired via `customers_haystack_version` metadata gate:
  * missing marker → full sweep (touches every row)
  * fresh marker → cheap "missing-only" sweep every boot to
    cover freshly-inserted docs before their save-hook runs
  * `HAYSTACK_VERSION` bump forces a full re-sweep on the next
    boot (any schema change → re-index)
* Progress logs every 500 rows tagged with `scope=` +
  `tenant=<id>` (visible in `supervisorctl tail backend`)
* Admin endpoint
  `POST /api/admin/maintenance/rebuild-customers-haystack`:
  * `super_admin` role required
  * Rate-limited to **1 rebuild / hour / tenant** (429 with
    `retry_after` on subsequent calls)
  * Idempotent — safe to hammer

### Task 2 — Ambient timeout telemetry
* Server middleware attaches `X-Request-Id: <uuid4>` on every
  `/api/*` response
* Slow-request log line at **5 s WARN / 10 s WARN / 25 s ERROR**
  with method + bucketed path + tenant + user + role +
  duration_ms + status + request_id (paths bucketed —
  `/customers/{uuid}` → `/customers/:uuid`)
* `Server-Timing` header on every `/api/*` response so DevTools >
  Network > Timing surfaces the total wall-clock; handlers can
  push named phases (`schedule/today` emits `crews;dur=X`,
  `jobs;dur=X`, `custs;dur=X`, `entries;dur=X`, `legs;dur=X`,
  `total;dur=X`)
* `POST /api/admin/client-telemetry/timeout` endpoint — auth-
  gated, rate-limited 1 write / sec / user, killswitch
  `TIMEOUT_TELEMETRY_KILLSWITCH=1`, 30-day TTL
* Frontend `api.js` catches `AbortError`, POSTs the request
  context (URL, method, duration_ms, route_path, user_agent,
  request_id) fire-and-forget with `keepalive: true` before the
  toast throws. **No toast copy change**.

### Task 3 — Schedule + Dispatch index coverage
New `diag_schedule_dispatch_indexes` migration (companion to K44,
runs unconditionally on boot, idempotent):

* `jobs.diag_jobs_tenant_assigned_tech_sched` —
  `(tenant_id, assigned_technician_id, scheduled_date)`
* `jobs.diag_jobs_tenant_assigned_to_sched` —
  `(tenant_id, assigned_to, scheduled_date)`
* `jobs.diag_jobs_tenant_sched_route_idx` —
  `(tenant_id, scheduled_date, route_index, created_at)`
* `customers.diag_customers_tenant_service_lat`
* `customers.diag_customers_tenant_service_days`
* `customers.diag_customers_tenant_assigned_tech`

## Benchmark results (in-process ASGI, 10 iterations post-warm-up)

| Bench | N | P50 | P95 | max | Budget (P95) | Verdict |
|-|-|-|-|-|-|-|
| **customers `?search=lynn`** | 2 000 rows | 49 ms | **50 ms** | 50 ms | 500 ms | ✅ 10× under budget |
| **schedule/today** | 400 jobs / 40 techs | 5 ms | **7 ms** | 7 ms | 500 ms | ✅ 70× under budget |
| **dispatch/board** | 400 customers | 16 ms | **19 ms** | 19 ms | 500 ms | ✅ 26× under budget |

Pre-fix numbers on the same in-process seed:
* Customers search (six-field regex OR, no haystack) — production
  incident timed out at ≥ 30 000 ms with 1 931 rows.
* Schedule/today — degraded proportionally to `assigned_to` +
  `assigned_technician_id` collection size (unindexed OR arms).
* Dispatch/board — two 2 000-row collscans per request (pins +
  unrouted) — user-visible spinner past 5 s in prod.

## Endpoints audited (schedule/dispatch add-on)

| Endpoint | Before | After | Change |
|-|-|-|-|
| `GET /api/schedule/today` | Unindexed OR arms (assigned_technician_id, assigned_to). Batched fanouts already in place from Task 5. | Same handler; new compound indexes serve every OR arm. | Indexes only. Already had `Server-Timing` phase breakdown, `X-Request-Id`. |
| `GET /api/schedule/day` | Alias — same handler | Same | No change |
| `GET /api/dispatch/board` | Two unindexed `customers.find` sweeps + tech-directory batch + optional jobs fallback. ETag / `If-None-Match` already shipped (K1 Q8) — 304 short-circuit. | Same handler; new `(tenant_id, service_lat|service_days|assigned_tech_ids)` indexes cover both sweeps. | Indexes only. ETag preserved. |
| `GET /api/jobs` | Uses `perf_customers_jobs_tenant_customer_created` + `k15_jobs_tech_schedule_status` — already fast. | Unchanged | Left alone — already fast. |
| `POST /api/dispatch/board/optimize` | Long-running per-request work (Google Directions); ETag helper skipped intentionally. | Unchanged | Not on the hot-load path; left alone. |

## Files touched
* `backend/services/customers_search_haystack.py` — hash builder,
  index helper, tenant-scoped + cross-tenant backfill, version
  metadata, progress logging every 500 rows.
* `backend/routers/customers.py` — search fast-path, apply
  haystack on create + update + merge.
* `backend/routers/client_telemetry.py` — `POST /api/admin/
  client-telemetry/timeout` endpoint + TTL index (fixed a
  `from deps import get_current_user` typo the prior agent
  left — module was import-failing).
* `backend/routers/admin_maintenance.py` (new) — `POST
  /api/admin/maintenance/rebuild-customers-haystack` (super_admin,
  1/hr/tenant rate-limit).
* `backend/migrations/diag_schedule_dispatch_indexes.py` (new) —
  additive, idempotent, unconditional boot migration.
* `backend/server.py` — middleware upgrades (`X-Request-Id`,
  slow-request log), boot wiring for the haystack version marker
  + the new schedule/dispatch migration + the admin_maintenance
  router mount.
* `frontend/src/api.js` — `_reportTimeoutTelemetry()` on
  `AbortError` (previous agent referenced it without defining
  it — timeouts would have ReferenceError'd).
* `backend/tests/test_perf_customers_search_p95.py` (new) —
  P95 < 500 ms pytest guard on 2 000 customers.
* `backend/tests/test_perf_schedule_dispatch_p95.py` (new) —
  P95 < 500 ms pytest guard on 400 jobs / 400 customers.
* `frontend/src/test/api-timeout-telemetry.test.jsx` (new) —
  3 vitests covering the fire-and-forget contract.

## Backfill observations on preview
Boot log after the version marker was cleared:

```
[haystack] backfill started scope=all-tenants-full tenant=- batch_size=500
[haystack] backfill completed scope=all-tenants-full tenant=- scanned=252 updated=0 duration_seconds=0.007
[customers_search_haystack] index ensured; auto-backfill needed=True reason=no_prior_version scanned=252 updated=0 duration_seconds=0.007 tenants=2
```

Preview tenant currently holds 252 customers across 2 tenants; all
252 rows already had `search_haystack` (Phase B seed populated
via `apply_haystack()`), so the full sweep reported `updated=0`.
The **252 scans took 7 ms**; a 2 000-row tenant lands in the ~50 ms
range under the same conditions. Admin rebuild trigger on
`aquaterra` (251 tenant-scoped rows): scanned=251 updated=0
duration=6 ms.

## Manual verification checklist

1. Login as super_admin, hit **Customers**, search "lynn". First
   paint < 200 ms even on a 2 000-row tenant. No red toast.
2. DevTools > Network > `customers?search=lynn` → **Server-Timing:
   total;dur=<value>** and **X-Request-Id:** headers present.
3. `POST /api/admin/maintenance/rebuild-customers-haystack` with
   super_admin JWT — returns
   `{ok:true, scanned:N, updated:M, duration_seconds:X}`. Second
   call in the same hour returns 429 with `retry_after`.
4. Same endpoint called with admin JWT (not super_admin) →
   `403 "super_admin only"`.
5. Hit `/schedule` — dispatcher's list + map paints in < 1 s on a
   tenant with 400+ jobs / 400+ geocoded customers.
6. DevTools > Network > `schedule/today` → `Server-Timing`
   includes `crews;dur`, `jobs;dur`, `custs;dur`, `entries;dur`,
   `legs;dur`, `total;dur`.
7. Simulate a slow request (backend restart mid-request or `kill
   -STOP` on the process) — client fires the toast AND the
   `POST /api/admin/client-telemetry/timeout` telemetry payload;
   toast copy unchanged.
8. `supervisorctl tail backend` — slow-request log lines emit at
   the 5 s / 10 s / 25 s thresholds with method + bucketed path +
   tenant + user + request_id.

## Follow-ups (deferred)

* Admin Diagnostics UI — list of last 100 client timeouts
  (blocked on collecting a week of prod signal first).
* Prometheus counter `crm_slow_request_total` from the middleware
  block (no metrics scraper wired in preview; wire in the next
  ops pass).
* Consider a `MISSING_SEARCH_HAYSTACK` breadcrumb log if the
  legacy OR arm ever hits > 0% of requests after the initial
  rolling deploy (indicates the backfill regressed).
