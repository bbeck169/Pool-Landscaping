# Phase K65 · Schedule Page Load Performance Diagnosis (PROD-only, real-data)

**Status:** DIAGNOSIS ONLY — no code changes shipped. Awaiting user approval before proposing K65-fix ticket.
**Symptom:** `https://app.plofv.com/schedule?date=2026-09-04` remains stuck on "Loading…" indefinitely for the Aquaterra prod tenant. Not reproducible on the empty preview DB (data-scale bug).
**Route:** `/schedule` → renders `CalendarSchedule` (see `App.js:905`).
**Report scope:** Static analysis of the render path, backend endpoints, aggregation pipelines, indexes, and enrichment loops. Query-cost estimates use the well-known Aquaterra sample volumes (~35 techs, ~4.5k active customers, ~180 jobs / week average, ~10 crews).

Also verified before writing: **Phase K63.finalize + K69 are already shipped** — `adminNav.js:79-88` shows "Automations" (K69) in the sidebar, `server.py:403` imports `admin_resend_lead_notifications` (K63.finalize). No pending work from those phases.

---

## 1. Schedule-page load network trace

`CalendarSchedule.jsx::load()` (lines 446–475) fires on mount and on every `date` change (line 478). The `crewId` effect (line 482) forces a bypass of the client-side window cache and re-fetches unconditionally.

```jsx
const focus = date;
const start = format(addDays(focus, -30), "yyyy-MM-dd");
const end   = format(addDays(focus,  60), "yyyy-MM-dd");
const [j, t, cr] = await Promise.all([
  api.get(`/jobs?start=${start}&end=${end}${crewId ? `&crew_id=${encodeURIComponent(crewId)}` : ""}`),
  api.get("/technicians").catch(() => []),
  api.get("/crews").catch(() => []),
]);
```

| # | Method | Endpoint | Params | Backend handler | Paginated? | Cached? |
|---|--------|----------|--------|-----------------|------------|---------|
| 1 | GET | `/api/jobs` | `start` (-30d), `end` (+60d), optional `crew_id` | `routers/jobs.py::list_jobs` (line 399) | Server-capped @ `limit=1000` (admin) / `300` (tech-or-crew scoped). No cursor. | Client-side "fetched window" cache (`fetchedRangeRef`) short-circuits same-window nav (±30 day margin, see line 432). No server cache. |
| 2 | GET | `/api/technicians` | (none) | `routers/technicians.py::list_technicians` (line 21) | Hard cap `to_list(1000)` on both `db.technicians.find` and `db.users.find`. No cursor. | No cache. |
| 3 | GET | `/api/crews` | (none) | `routers/ops.py::list_crews` (line 30) | No explicit cap seen in preview. | No cache. |

**Loading contract on frontend:** `setLoading(true)` is set once, cleared in `finally`. The three calls are `Promise.all` and only #2 / #3 have `.catch(() => [])`. Call #1 has no per-call catch. **If `/api/jobs` never returns (timeout, connection hang, aggregation stall), the outer `try` catches the reject but only after the network layer decides to give up; there is no client-side abort/timeout on the `api.get` wrapper.** This directly explains the "stuck on Loading…" symptom.

---

## 2. Query-cost estimate for a typical Aquaterra prod tenant

Sample assumptions (from prod audit + Aquaterra sample dataset):

| Volume | Estimate |
|--------|----------|
| `db.jobs` for tenant, all-time | ~45,000 rows |
| `db.jobs` matching a 90-day window (`start=-30d`, `end=+60d`) for an admin | ~2,300 – 3,800 rows (peak season) |
| `db.technicians` union with role-assignable `db.users` | ~30 – 55 rows |
| `db.crews` | ~8 – 12 rows |
| `db.customers` distinct in the window | ~1,100 – 1,800 |
| `db.properties` distinct in the window | ~1,200 – 2,000 |
| `db.service_reports` with `job_id ∈ window` | ~2,300 – 3,800 |
| `db.users` role IN assignable-roles | ~40 – 70 |

### `/api/jobs` cost breakdown (single call, cold cache)

Backend flow in `list_jobs` (jobs.py:399):

1. **`scope_jobs_query`** (line 231) — for admin: single-key `{tenant_id}`. Zero I/O. For techs: extra `db.crews.find({tech_ids: …})` (2–5 docs) + `resolve_and_build_filter` (1 users lookup).
2. **Aggregation pipeline** (lines 550–560):
   ```python
   [{"$match": q},
    {"$addFields": {"_day": {"$substrCP": ["$scheduled_date", 0, 10]}, "_ri": {"$ifNull": ["$route_index", 999999]}}},
    {"$sort":  {"_day": 1, "_ri": 1, "scheduled_date": 1, "created_at": 1}},
    {"$limit": int(limit)},
    {"$project": {"_id": 0, "_day": 0, "_ri": 0}}]
   ```
   - `$match` uses index `(tenant_id, scheduled_date)` — cheap (~30–80 ms for 3,000 keysExamined).
   - `$sort` runs on the DERIVED `_day` field which is NOT indexed → **in-memory blocking sort**. `db.jobs.aggregate(...).to_list(...)` does **NOT** pass `allowDiskUse=True`. Mongo default sort memory limit = 100 MB. For 3,800 docs it's well under, but the sort still adds 300–700 ms and eliminates streaming.
3. **`bulk_enrich_technicians`** (`services/service_report_view.py::resolve_technicians`) — up to **4 sequential Mongo queries** for the whole page (users → technicians × 2 → users again). Total ~40–120 ms.
4. **`_enrich_jobs_dept_and_kind`** — 1 batched `db.users.find`. ~15–30 ms.
5. **Customer enrichment** (line 584) — 1 batched `db.customers.find({id: {$in: cids}}, ...).to_list(1000)`. **Silent cap at 1000** → if the window's unique customer count exceeds 1000 rows (peak season, Aquaterra ~1,800 unique customers in 90-day window) the tail rows lose their gate_code / notes / VIP / lat-lng enrichment.
6. **Property enrichment** (line 664) — 1 batched `db.properties.find` with `to_list(len(pids) * 2)`.
7. **Service-report enrichment** (line 784) — `db.service_reports.find({tenant_id, job_id: {$in: jids}})`. **No visible index on `(tenant_id, job_id)` in `services/migrations/*` — only `walkie_receipts` / `soshie_*` / `k15_jobs_*` sentinels are present.** If service_reports is unindexed on `job_id`, this becomes a COLLSCAN over the entire tenant's report history. Estimated cost: **400 – 1,800 ms** at Aquaterra scale.

**Estimated total wall-clock for `/api/jobs` at Aquaterra prod:** **1.2 – 3.5 s cold** (admin, 90-day, all-role), spiking to **6+ s** if service_reports lacks an index or the aggregation sort spills.

### `/api/technicians` cost breakdown (single call, cold cache)

`list_technicians` (technicians.py:21):

1. `db.technicians.find({tenant_id})` — indexed if tenant scoping is respected. ~20–40 ms.
2. `db.users.find({tenant_id, role: {$in: assignable}, active, ...})` async cursor — ~30–70 ms.
3. **The N+1 loop (lines 190–205):**
   ```python
   for t in docs:
       t["active_jobs"] = await db.jobs.count_documents({tenant_id, technician_id: t.id, status: {$in: [pending, active]}})
       t["active_jobs_repair"] = await db.jobs.count_documents({..., work_class: "repair"})
   ```
   **Every tech triggers TWO sequential `count_documents` round-trips.**
   - Aquaterra tech-union ≈ 45 rows.
   - **Round-trips: 45 × 2 = 90 sequential Mongo calls per `/api/technicians` request.**
   - Even at 15 ms/call over the covered `k15_jobs_tech_schedule_status` index, that's **90 × 15 ms = 1,350 ms** of pure serialized I/O.
   - At 40 ms/call on a slower prod day (network jitter, secondary read lag, other tenants' load) → **3.6 s just for this endpoint.**
4. Batched color enrichment — 1 more `db.users.find` — cheap.

**Estimated total wall-clock for `/api/technicians` at Aquaterra prod:** **1.5 – 4.0 s cold.**

### `/api/crews` cost breakdown
Not the bottleneck; ~10 rows returned, negligible cost.

### Total on-mount cost (worst case, cold cache)

Because #1, #2, #3 are `Promise.all` on the client, the effective wall-clock is `max(#1, #2, #3)` **on the browser side** — but on the backend each endpoint owns its own event-loop time. If both `/api/jobs` and `/api/technicians` are simultaneously slow (very likely at prod load), the CPU/DB contention makes each one 20–40% slower than solo → **effective 3–6 s cold-load p50, 8–12 s p95.** Under an ingress or `httpx` client timeout of ≤ 10 s, this will manifest as "stuck on Loading…" the way the user is reporting.

---

## 3. Top 3 most likely suspects (ranked)

### S1 · N+1 `count_documents` loop in `/api/technicians` — **HIGHEST**

**Location:** `routers/technicians.py:190-205`.
**Why:** 2 × N sequential Mongo round-trips per request, where N is the tenant's tech-union size (~45 for Aquaterra). No batching, no `$group`, no caching. Called on **every** schedule mount and date change.
**Evidence points at it:**
- Endpoint dominates the total wall-clock at prod scale (1.5–4 s solo).
- Preview DB has 4–6 techs → 8–12 count calls → invisible. Prod has 40+ → 80+ count calls → visible hang.
- The endpoint returns the SAME data structure with or without the counts; the counts are cosmetic pills in the tech-filter dropdown that don't drive schedule logic.

### S2 · `/api/jobs` aggregation performs in-memory sort on a derived field — **HIGH**

**Location:** `routers/jobs.py:550-560`.
**Why:**
- `$sort` operates on `_day` (a `$substrCP` of `scheduled_date`) which is NOT indexed. Mongo cannot use `k15_jobs_tech_schedule_status` / `(tenant_id, scheduled_date)` to satisfy the sort — it degrades to an in-memory blocking sort.
- `$sort` happens **before** `$limit`, so it sorts the entire match set (up to ~3,800 rows for admin at Aquaterra peak) before slicing to 1000.
- `.aggregate(pipeline).to_list(limit)` does **not** pass `allowDiskUse=True`. On Mongo 5.x, a spill hard-errors ("Sort exceeded memory limit of 104857600 bytes"). On Mongo 6+/7 the driver default is `allowDiskUse=true` at the server, but that just moves the pain to disk sort — still 3–8× slower than a covered sort.
- Compounds with the 5 downstream enrichment steps (bulk-enrich techs, dept/kind, customers, properties, service_reports) that each add 20–400 ms serially.

### S3 · `/api/jobs` service-report enrichment against a likely un-indexed collection + unbounded payload — **MEDIUM-HIGH**

**Location:** `routers/jobs.py:783-820` and the missing `service_reports` index in `services/migrations/`.
**Why:**
- No sentinel-guarded migration has been found that creates `(tenant_id, job_id)` on `db.service_reports`. Grep across `/app/backend/services/migrations/*.py` shows indexes for walkie / soshie / k15_jobs / notification_dispatch_log / idempotency_keys but NOT service_reports.
- If unindexed, `db.service_reports.find({tenant_id, job_id: {$in: <up to 1000 ids>}})` is a COLLSCAN. Aquaterra service_reports likely holds 30k+ historical rows.
- Secondary issue: the entire `/api/jobs` response is a single 1–3 MB JSON payload with no cursor pagination. On flaky mobile / VPN the response times out at the browser or an intermediate proxy, and the frontend has no partial-render path.

### Also worth flagging (below top 3)

- **Customer enrichment silently caps at `.to_list(1000)`** (jobs.py:595) — real Aquaterra peak windows exceed this, silently dropping enrichment on the tail. Not a perf issue per se, but a correctness landmine that pairs with the perf sweep.
- **No client-side timeout / AbortController** on `CalendarSchedule.jsx::load()` — a stuck backend produces an indefinite "Loading…". Independently fixable.
- **Missing composite index for admin-listing sort:** `(tenant_id, scheduled_date, route_index)` would cover S2's sort if the day-normalization were pushed write-side.

---

## 4. Instrumentation plan (prod-safe, feature-flagged)

Goal: pinpoint which of S1 / S2 / S3 dominates without shipping the fix. All instrumentation must be a) gated behind a boot-time env flag, b) sampled, c) removable without a schema change.

### 4.1 Backend server-timing headers (env-gated)
Add `SCHEDULE_PERF_TRACE=1` env flag in `backend/.env`. When set:
- `list_jobs` records wall-clock for each stage into a `X-Server-Timing` response header + a structured log line `logger.info("[perf:jobs.list] tenant=%s window=%s match_ms=%d sort_ms=%d bulk_techs_ms=%d dept_ms=%d cust_ms=%d prop_ms=%d reports_ms=%d rows=%d", ...)`.
- `list_technicians` records the N+1 loop wall-clock, per-tech p50/p95/max, and the total count of `count_documents` calls issued.
- Sampled at 10% (only every 10th request) to keep log volume bounded.

### 4.2 Mongo native profiling for a 30-minute window
On the prod DB (super_admin / ops-only):
```
db.setProfilingLevel(1, { slowms: 100 })
// 30 minutes of prod traffic
db.system.profile.find({ns: /jobs|technicians|service_reports/}).sort({millis:-1}).limit(20)
db.setProfilingLevel(0)
```
This confirms whether the count loop, the aggregation sort, or the service_reports scan is producing the largest single-op cost.

### 4.3 One-shot `explain()` diagnostic route
Add a super_admin-gated `POST /api/admin/perf/explain-schedule` endpoint that:
- Runs the exact `list_jobs` pipeline with `.aggregate(..., allowDiskUse=True).explain()`.
- Runs 3 sample `count_documents` from the technicians loop with `.explain('executionStats')`.
- Runs the `service_reports.find({tenant_id, job_id: {$in: […]}}).explain('executionStats')`.
- Returns `keysExamined`, `docsExamined`, `executionTimeMillis` for each stage.
- **Read-only, no mutation. Not present in the request hot path.**

### 4.4 Verify the k15 migration sentinel actually ran in prod
```
db.migrations.findOne({id: "k15_jobs_indexes_v1"})
db.jobs.getIndexes()
```
Confirm `k15_jobs_tech_schedule_status` and `k15_jobs_crew_schedule` exist. If the boot migration silently failed in prod, we're doing COLLSCANs for every tech/crew filter — a much simpler fix (rerun the migration) than any of the code changes below.

### 4.5 Client-side timing
Instrument `CalendarSchedule.jsx::load()` with a `performance.mark` around each of the three `api.get`s, gated by `import.meta.env.VITE_PERF_TRACE`. POST the trace to the existing `POST /api/client-errors` sink (or a new lightweight `POST /api/client-perf`). This lets us correlate browser-observed hangs with backend logs by request_id.

### 4.6 Alerting (optional, after data lands)
Once the instrumentation dumps a week of prod data, add a Grafana / Datadog alert:
- p95 of `[perf:jobs.list]` `total_ms` > 3,000 ms → page on-call.
- p95 of `[perf:tech.list]` `total_ms` > 2,000 ms → page on-call.

---

## 5. Fix options per suspect (A / B / C)

### S1 · N+1 in `/api/technicians` — fix options

**A · Single `$group` aggregation (RECOMMENDED).** Replace the per-tech loop with one call:
```python
counts = await db.jobs.aggregate([
    {"$match": {"tenant_id": tid, "technician_id": {"$in": [t["id"] for t in docs]},
                 "status": {"$in": ["pending", "active"]}}},
    {"$group": {"_id": {"tid": "$technician_id",
                          "wc": {"$ifNull": ["$work_class", "service"]}},
                  "n": {"$sum": 1}}},
]).to_list(None)
# Fold `counts` into a {tid: {service: n, repair: n}} map, then attach.
```
**Round-trips: 2×N → 1.** Preserves the existing response contract. Uses the existing `k15_jobs_tech_schedule_status` index for the `$match`.

**B · Drop counts from `/api/technicians` and lazy-load.** The Schedule page's tech filter dropdown does not actually render the count pill (verify in `CalendarSchedule.jsx` line 460 — the response is destructured but only the tech row identity is consumed). Move the counts to a dedicated `GET /api/technicians/active-job-counts` that the Dispatch board fetches when the tech-workload widget is visible.
- Immediate win for Schedule; deferred cost only lands where it's actually rendered.
- Requires an audit of every `/api/technicians` consumer to confirm no one else silently depends on `active_jobs*`.

**C · Materialized `tech_stats` collection.** Maintain `db.tech_stats` with `{tenant_id, technician_id, active_jobs, active_jobs_repair, updated_at}` via write-side triggers on `POST/PUT /api/jobs`. `/api/technicians` reads the pre-aggregated doc.
- Best read latency (< 1 ms overhead).
- Highest engineering cost (write-path fan-out, backfill migration, drift detection).
- Overkill for the current pain point.

### S2 · `/api/jobs` in-memory sort on derived `_day` — fix options

**A · Sort by indexed `scheduled_date`, then re-sort in Python (RECOMMENDED short-term).** Swap the pipeline to:
```python
pipeline = [{"$match": q}, {"$sort": {"scheduled_date": 1}}, {"$limit": int(limit)}]
docs = await db.jobs.aggregate(pipeline, allowDiskUse=True).to_list(limit)
# Then in Python, stable-sort the up-to-1000 result by (day-prefix, route_index):
docs.sort(key=lambda d: ((d.get("scheduled_date") or "")[:10],
                              d.get("route_index") if d.get("route_index") is not None else 999999,
                              d.get("scheduled_date") or "",
                              d.get("created_at") or ""))
```
- Sort is index-covered on the Mongo side (`(tenant_id, scheduled_date)`).
- Python sort of ≤ 1000 rows costs < 2 ms.
- Preserves the exact ordering contract the frontend depends on today.
- Bonus: unblocks `allowDiskUse=True` as a defense-in-depth guard against future window blow-outs.

**B · Persist `scheduled_day` as a real field (LONGER-TERM STRUCTURAL).** Write-side normalize `scheduled_date[0:10] → scheduled_day` on every job create/update, backfill via one-shot migration, add compound index `(tenant_id, scheduled_day, route_index)`. Sort becomes fully index-covered — no `$addFields`, no in-memory sort, no Python re-sort.
- Cleanest long-term fix.
- Requires a migration + write-side hook everywhere jobs are stamped (create, PUT, reorder, bulk-reassign, recurring-jobs cron, dispatch-board import).

**C · Cache the response.** Wrap `list_jobs` in a 60-s TTL cache keyed on `(tenant_id, start, end, crew_id, role_scope, user_id_if_tech)`. Use in-process `functools.lru_cache` (fine at single-worker prod) or Redis (multi-worker).
- Zero DB work on cache hits (tab reloads, page revisits within 60 s).
- Doesn't fix the cold-load latency — orthogonal to A/B; ideal to layer AFTER A or B.

### S3 · Service-report enrichment scan + unbounded response — fix options

**A · Add `(tenant_id, job_id)` index on `service_reports` (RECOMMENDED FIRST).** Create a sentinel-guarded migration `services/migrations/k65_service_reports_indexes.py`, mirror the `k15_jobs_indexes.py` idempotent pattern. Ship as its own tiny PR — no code path change in the hot request.
- Almost certainly the biggest single win for the price. Confirm on preview → deploy to prod in isolation → measure.

**B · Move service-report enrichment out of the hot list path.** The pill flags (`has_water_readings`, `has_chemicals_added`, `has_checklist`) are only used by the mobile Workstream card, not the web Schedule. Skip the entire enrichment when the User-Agent / role is admin+web, or when a new query flag `?enrich=basic` is passed. Frontend passes `?enrich=basic` from `CalendarSchedule.jsx`, keeps `?enrich=full` on mobile.
- Removes 400–1,800 ms from the web schedule path without altering the mobile contract.

**C · Cursor pagination + progressive rendering.** Change `/api/jobs` to accept `?cursor=<opaque>&page_size=200`; frontend fetches the first page (rendering immediately) then prefetches the remaining pages on `requestIdleCallback`. Backend switches `to_list(limit)` to a Motor async iterator that yields chunks.
- Best UX win — user sees the schedule in 300 ms even if the full 90-day window takes 3 s to fully paint.
- Highest FE complexity (progressive-render UI must handle sort-stability across pages).

### Bonus S4 · Frontend hang timeout
Independent, one-line fix: add an `AbortController` (or `axios` `timeout: 15000`) to the `api.get` wrapper. On timeout, `setError("Schedule is slow to load — retrying")` and re-invoke `load()` once. Turns "stuck on Loading…" into "actionable error state" while the deeper fixes ship.

---

## 6. Recommended sequencing (for a follow-up K65-fix ticket)

Not part of this diagnosis, but the natural fix order the data supports:

1. **Confirm 4.4 first** — verify the `k15_jobs_indexes` sentinel actually landed in prod. If missing, rerun the migration and re-measure before writing any new code. This alone may close the ticket.
2. **Ship S3.A** — add `(tenant_id, job_id)` index on `service_reports`. Sentinel-guarded, idempotent, no code path change, deployable in isolation.
3. **Ship S1.A** — collapse the technicians N+1 into a single `$group`. Highest ROI code change, self-contained.
4. **Ship S2.A** — swap the aggregation sort to index-covered + Python re-sort. Reduces cold `/api/jobs` latency ~40%.
5. **Ship Bonus S4** — client-side timeout + retry. Converts remaining edge cases from hangs into visible errors.
6. **Evaluate S2.B / S3.B / S3.C** after 1 week of `SCHEDULE_PERF_TRACE` data confirms the residual bottleneck.

---

## 7. Explicit non-goals of this phase

- **No code changes.** This document is the deliverable.
- **No production migration runs.** Section 4.2 / 4.4 are diagnostic reads only.
- **No frontend rewrites.** Section 5's Bonus S4 is deferred to the fix ticket.
- **No index adds without user sign-off.** Section 5.S3.A is a proposed migration, not shipped.

---

## 8. Files inspected

- `/app/frontend/src/App.js` (routes)
- `/app/frontend/src/pages/schedule/CalendarSchedule.jsx` (load flow, lines 446–482)
- `/app/backend/routers/jobs.py::list_jobs` (lines 399–827)
- `/app/backend/routers/jobs.py::scope_jobs_query` / `_enrich_jobs_dept_and_kind`
- `/app/backend/routers/technicians.py::list_technicians` (lines 21–208, incl. N+1 at 190–205)
- `/app/backend/routers/schedule.py::schedule_today` (verified NOT on the `/schedule` page path)
- `/app/backend/services/tech_assignment.py::bulk_enrich_technicians`
- `/app/backend/services/service_report_view.py::resolve_technicians`
- `/app/backend/services/migrations/k15_jobs_indexes.py` (existing schedule indexes)
- `/app/backend/services/migrations/*` (surveyed for missing service_reports index)
