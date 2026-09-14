# Feature: Job Timers dashboard — `/job-timers` collection + page

**Date**: Feb-2026
**Status**: Backend + web frontend complete. Mobile parity out of
scope per spec (dashboard is admin-desktop only).

Extends the pre-existing `job_timers` collection + Phase-1 router
(`backend/routers/job_timers.py`) with:

1. Automatic lifecycle hooks on GPS arrival + job completion.
2. A paginated summary + list dashboard at `/job-timers`.
3. New `GET /api/job-timers/summary` metrics endpoint.

---

## 1. Schema (extends Phase 1)

Collection `job_timers` — one row per timer instance. Phase 1
introduced this collection; this phase adds no new columns but
formalises the shape used by the dashboard.

| Field | Type | Notes |
| ----- | ---- | ----- |
| `id` | str | UUID4 primary key. |
| `tenant_id` | str | Tenant scope for every query. |
| `job_id` | str | FK → `jobs.id`. |
| `customer_id` | str? | Denormalised from the job at start. |
| `entity_type` | `"tech"` \| `"crew"` | Phase 1 supported both. |
| `tech_id` | str? | Aliased in API responses as `technician_id`. |
| `crew_id` | str? | |
| `started_at` | ISO ts | |
| `ended_at` | ISO ts? | `null` while the timer is running. Aliased in responses as `completed_at`. |
| `duration_seconds` | int? | Computed on close: `max(0, ended-started)`. |
| `start_source` | `"gps_arrival"` \| `"geofence"` \| `"manual_admin"` | `geofence` retained for backwards compat with Phase 1 rows. |
| `end_source` | `"job_completed"` \| `"service_report_submit"` \| `"manual_admin"` | |
| `created_at`, `updated_at` | ISO ts | |

Dashboard responses fold both source fields into a single spec
alias:

```
source = "gps_arrival"  when start_source in ("gps_arrival", "geofence")
       = "manual"       otherwise
```

### Indexes (idempotent, created on boot)

```
{ tenant_id: 1, tech_id: 1, started_at: -1 }   name: idx_job_timers_tenant_tech_started
{ tenant_id: 1, job_id: 1 }                     name: idx_job_timers_tenant_job
```

Wired from `server.py` alongside the other feature-router index
hooks (`ensure_public_checkins_indexes`).

---

## 2. Lifecycle hooks

```
                 ┌──────────────────────────────────────────┐
POST /api/jobs/{id}/arrive   (GPS gate passes, timer flip)  │
                                                             │
   auto_start_timer_on_arrival()                             │
     • idempotent probe: any open row for                    │
       (tenant, job, tech) with ended_at=null?               │
         ↳ yes → return existing id, DO NOTHING              │
         ↳ no  → insert row with start_source="gps_arrival"  │
                                                             │
                 ▼                                            │
        db.job_timers.{id, started_at, ended_at:null, …}    │
                                                             │
                                                             │
PUT /api/jobs/{id}  (status flips prev != "completed"        │
                     → cur == "completed")                    │
                                                             │
   close_open_timers_for_job(reason="job_completed")         │
     • find every open row for the job                       │
     • set ended_at=now, duration_seconds, end_source        │
     • append audit row to db.job_timer_audit                │
                                                             │
     Idempotent: if no open row exists, returns 0 and        │
     logs a warning (missed arrival is a valid state).       │
                                                             │
POST /api/service-reports  (submit — pre-existing hook,      │
                             unchanged this phase)            │
                                                             │
   close_open_timers_for_job(reason="service_report_submit") │
                 └──────────────────────────────────────────┘
```

Both closing paths are non-fatal to their calling hot-paths —
`close_open_timers_for_job` swallows exceptions and logs a
warning so a bookkeeping failure never breaks arrival or
completion. Same guarantee for `auto_start_timer_on_arrival`.

### Wire points

| Hook | File | Line |
| ---- | ---- | ---- |
| START | `backend/routers/jobs.py` — inside `job_arrive` after `_log("started")` | `try: … auto_start_timer_on_arrival(…) … except: logger.warning(...)` |
| STOP  | `backend/routers/jobs.py` — inside the status → completed transition block, after `emit_event("job_completed")` | `try: … close_open_timers_for_job(reason="job_completed") …` |
| STOP  | `backend/routers/service_reports.py::submit_report` (pre-existing) | Now passes `reason="service_report_submit"` explicitly. |

---

## 3. Endpoint contracts

### `GET /api/job-timers` (extended)

| Param | Type | Notes |
| ----- | ---- | ----- |
| `job_id` | str? | |
| `technician_id` OR `tech_id` | str? | Spec alias; either works. |
| `crew_id`, `customer_id` | str? | |
| `from` OR `date_from` | ISO date? | Spec alias; either works. |
| `to` OR `date_to` | ISO date? | |
| `page` + `page_size` | int, 1..200 | **Enables paginated envelope.** Both must be present. |
| `open_only` | bool | Legacy. Filters `ended_at=null`. |
| `limit` | int, 1..2000 (default 500) | Legacy — used ONLY when `page`/`page_size` are missing. |

Response — **paginated branch** (both `page` + `page_size` present):

```json
{
  "items": [...],
  "count": 25,
  "page": 1,
  "page_size": 25,
  "total": 137,
  "total_pages": 6
}
```

Response — **legacy branch** (no `page`/`page_size`):

```json
{ "items": [...], "count": 42 }
```

Every row is enriched with `technician_name`, `job_title`,
`customer_name`, `source` (folded from `start_source`),
`completed_at` (aliased from `ended_at`), and `technician_id`
(aliased from `tech_id`). Sort is `started_at DESC`.

### `GET /api/job-timers/summary` (NEW — spec §3.2)

| Param | Type | Notes |
| ----- | ---- | ----- |
| `technician_id` OR `tech_id` | str? | Spec alias. |
| `job_id` | str? | |
| `from` OR `date_from` | ISO date? | |
| `to` OR `date_to` | ISO date? | |

Response:

```json
{
  "avg_seconds": 1800,
  "median_seconds": 1200,
  "min_seconds": 600,
  "max_seconds": 3000,
  "count": 5
}
```

Only closed timers with `duration_seconds > 0` participate — an
in-flight job doesn't skew the average toward zero. Empty
window → every metric is `0` (never `null`).

Role gate: `super_admin`, `admin`, `manager`. Customers → 403.

---

## 4. Dashboard UX (`/job-timers`)

Renders in `frontend/src/pages/timers/JobTimersPage.jsx`. Route
gate: `AdminOnly` in `App.js` line 1177. Nav entry:
Operations → Workforce → "Job Timers" (already in
`adminNav.js` line 195).

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│ Job Timers            (h1)                                  │
│ retrospective view … (h2)                                   │
├─────────────────────────────────────────────────────────────┤
│ [Avg 30m] [Count 5] [Min 10m] [Max 50m] [Median 20m]        │
│  (SummaryCard — 5 tiles, grid 2/3/5 cols on sm/md/lg)       │
├─────────────────────────────────────────────────────────────┤
│ [Timers] [Avg Time]  (tabs — retained from Phase 1)         │
├─────────────────────────────────────────────────────────────┤
│ [From] [To] [Tech id] [Customer id] [Export CSV]            │
│  (filter strip — navy chrome, dark)                         │
├─────────────────────────────────────────────────────────────┤
│ Date  Job  Tech / Crew  Started  Ended  Duration  Src…      │
│ ...                                                          │
├─────────────────────────────────────────────────────────────┤
│ Page 1 of 6 · 137 entries        [Prev] [Next]              │
│  (Pagination footer — ALWAYS mounted, disabled on edge)     │
└─────────────────────────────────────────────────────────────┘
```

### URL sync

Filter + page state is written to the URL so a shared link
restores state:

| Query key | Field |
| --------- | ----- |
| `from` | Start date (YYYY-MM-DD) |
| `to` | End date (YYYY-MM-DD) |
| `technician_id` | Tech id filter |
| `job_id` | Job id filter |
| `page` | Current page (omitted when 1) |
| `t` | Tab (`timers` \| `avgtime`) |

### `?t=avgtime` deep-link semantics

When the URL query contains `?t=avgtime`:

1. Existing behaviour — flips the tab to Avg Time.
2. **NEW** — the summary card's Average tile gets
   `aria-current="true"`, scrolls itself into view (smooth,
   block=center), and pulses an indigo ring for 2.5 s.

This gives ops a direct deep-link to the metric ("clicking
'avg service duration' in a manager report lands on the
highlighted number"). Scroll behaviour is jsdom-safe (falls
through silently in tests).

### Testids

| Testid | Element |
| ------ | ------- |
| `job-timers-page` | Root wrapper |
| `job-timers-summary-card` | Summary strip container |
| `job-timers-summary-avg` | Average tile |
| `job-timers-summary-count` | Count tile |
| `job-timers-summary-min` | Min tile |
| `job-timers-summary-max` | Max tile |
| `job-timers-summary-median` | Median tile |
| `job-timers-filter-from` | From date input marker |
| `job-timers-filter-to` | To date input marker |
| `job-timers-filter-technician` | Tech-id input marker |
| `job-timers-row-<i>` | Table row (index-based, per spec) |
| `job-timers-pagination` | Pagination container |
| `job-timers-pagination-summary` | "Page N of M · X entries" |
| `job-timers-pagination-prev` | Prev button |
| `job-timers-pagination-next` | Next button |

Legacy Phase-1 testids (`jt-filter-*`, `jt-row-*`, `jt-tab-*`,
`jt-edit-*`) are retained for backwards compat with the existing
Phase-1 tests.

Formatting helper `_fmtDur(seconds)`:

* `>= 3600` → `"1h 05m"`
* `< 3600`  → `"30m 00s"`

---

## 5. Files touched

| File | Change |
| ---- | ------ |
| `backend/routers/job_timers.py` | Added `auto_start_timer_on_arrival` (idempotent GPS-arrival hook), extended `close_open_timers_for_job` with a `reason` param, added pagination envelope + spec aliases to `GET /job-timers`, added `GET /job-timers/summary` (avg/median/min/max/count), added `ensure_job_timers_indexes`. |
| `backend/routers/jobs.py` | Wired START hook after successful `/arrive`; wired STOP hook at `job_completed` status transition. |
| `backend/server.py` | Boot-time `ensure_job_timers_indexes()` alongside the pre-existing index hooks. |
| `frontend/src/pages/timers/JobTimersPage.jsx` | Lifted filter/page state to the page; added `SummaryCard` component; added `?t=avgtime` focus-and-scroll behaviour; added always-mounted pagination footer; added spec-required testid aliases. |
| `backend/tests/test_job_timers_dashboard.py` | **NEW** — 12 tests: summary math × 3, paginated envelope × 3, legacy compat × 1, no-op close × 1 + seed-scoped harness. |
| `frontend/src/test/job-timers-dashboard.test.jsx` | **NEW** — 3 Vitest cases (summary mount + pagination always mounted + `?t=avgtime` focus). |
| `memory/FEATURE_JOB_TIMERS.md` | This memo. |

---

## 6. Test status

* **Backend** (`pytest backend/tests/test_job_timers_dashboard.py
  tests/test_job_timers_phase1.py`) →
  **17 passed** (12 new + 5 pre-existing Phase 1).
* Adjacent-touched sweep (`test_checkin_ai_description.py`,
  `test_tech_checkin_flow.py`, `test_public_checkins.py`) all
  green — **64 total passing** across the touched surface.
* **Frontend** (`yarn test:unit` — full suite):
  **580 files passed | 1 skipped · 4351 passed | 34 skipped**
  (was 4348 → **+3** matching the new file).
* **OpenAPI paths**: **1740** (was 1739 → **+1**). The spec
  predicted +2 for the two new routes; the delta is +1 because
  the existing `GET /api/job-timers` route was EXTENDED in place
  (spec params added as aliases + pagination envelope) rather
  than replaced. The new route is `GET /api/job-timers/summary`.
* `test_iteration39_job_timers.py` has 3 pre-existing failures
  (`test_arrive_starts_timer_and_is_idempotent`,
  `test_status_completed_auto_stops_timer`,
  `test_admin_shape_and_filters`) — verified via `git stash` to
  reproduce on the baseline. Unrelated to this phase.

---

## 7. Migration/backfill

Deferred per spec §5. No `/backfill-job-timers` admin script
added — the Phase-1 router already writes rows on every
`/arrive` and `/complete` from Feb-2026 onward, and back-filling
historical jobs would require GPS timestamps we don't have.

---

## 8. Out of scope

* Mobile parity — dashboard is admin-desktop only per spec.
* Manual start/stop UI — v1 relies on auto-hooks only. Backend
  `POST /job-timers/start` + `/{id}/close` endpoints remain
  available for future manual UI.
* Historical backfill — deferred per spec.
* A–F backlog items.
