# AUDIT · Multi-stop routing enhancement

**Type:** Design audit (no implementation code).
**Owner:** main agent.
**Dispatch:** Feb-2026 · P2 audit.
**Scope:** Understand what "multi-stop routing enhancement" plausibly
means in this codebase, given the substantial routing surface that
already exists, and recommend a next-dispatch slice.

---

## 1 · Current routing / scheduling model

The CRM already ships a **mature, multi-tier routing system**. This
is not a green-field feature area.

### 1.1 · Data model — jobs collection

Every `jobs` row carries the routing-relevant fields directly on the
doc:

| Field | Purpose |
| ----- | ------- |
| `technician_id` | Assignee. Nullable → "unassigned". |
| `scheduled_date` | `YYYY-MM-DD` — day bucket. |
| `scheduled_start` / `scheduled_end` | ISO datetimes — time window. |
| `route_index` | **Integer, admin-assigned position within a `(tenant, day, tech)` triple.** Written by `POST /api/jobs/reorder`. Preserved through the tech's `/schedule/today` sort. |
| `site_lat` / `site_lng` (fallback `lat` / `lng`) | Geocoded coords. |
| `address` / `site_address`, `city`, `state`, `zip` | Human-readable. |
| `status` | `pending`, `in_progress`, `completed`, `could_not_service`, `skipped`, `cancelled` (last five are **pinned** during optimization). |
| `priority`, `work_class` (`service` / `repair`), `department` | Filtering / colouring. |
| `from_estimate_id` | Provenance link when a job was scheduled from an accepted quote. |

### 1.2 · Auxiliary collections

| Collection | Key | Purpose |
| ---------- | --- | ------- |
| `dispatch_route_orders` | `(tenant_id, day, tech_user_id)` | Admin-persisted ordered customer-id sequence, driving the Dispatch Board's day view. Written by `POST /api/dispatch/board/apply-order`. |
| `distance_matrix_cache` | `key = hash(from_lat,from_lng,to_lat,to_lng)` | Leg distance/duration cache. Hydrates `route_legs` on `/schedule/today` without a Directions call per leg. |
| `route_optimizations` (per approval router) | `id` | Approval-workflow docs for **tech-proposed / admin-approved** route reorders (`request → preview → approve/reject → apply → undo`). |
| `technicians`, `time_entries`, `job_titles` | — | Assignee metadata + shift/mileage source. |

### 1.3 · Endpoints — routing surface (path × RBAC)

**Admin / dispatcher tier** (admin, super_admin, manager where noted):

- `GET /api/dispatch/board` (`admin` + `super_admin` + `manager` read) — pins by `day`/`tech_user_id`/`route_type`, ordered stops, tech_load strip.
- `POST /api/dispatch/board/optimize` — Google Routes API v2 (`routes.googleapis.com/directions/v2:computeRoutes`) with `optimizeWaypointOrder: true`. Returns reordered customer IDs, encoded polyline, distance/duration, savings.
- `POST /api/dispatch/board/apply-order` — persist `dispatch_route_orders`.
- `POST /api/admin/customers/geocode-backfill` — idempotent geocode backfill.
- `POST /api/dispatch/auto-assign` — assign unrouted jobs.
- `POST /api/dispatch/reassign-job` / `POST /api/dispatch/reassign` / `GET /api/dispatch/reassign` / `POST /api/dispatch/reassign/{oid}/cancel` / `GET /api/dispatch/assignment-change-log` — full reassign lifecycle.
- `POST /api/dispatch/suggest-route` — bulk route suggestion.
- `GET /api/dispatch/route/unscheduled-jobs`.
- `POST /api/dispatch/route/insert` — insert an unrouted job into a tech's day at the optimal position.
- `POST /api/dispatch/route/preview-insert-batch` — batch preview.
- `POST /api/dispatch/route/optimize` — full-day optimizer with hash-cached results.
- `POST /api/dispatch/route/apply`.
- `GET /api/dispatch/route/savings/weekly` — dashboard KPI.
- `POST /api/dispatch/weather-scan` + accept/reject — weather-driven rescheduling.

**Route-optimization approval flow** (tech proposes, admin decides):

- `POST /api/route-optimization/preview` / `request` / `apply` / `{id}/approve` / `{id}/reject` / `undo` / `pending`.

**Technician / schedule tier:**

- `GET /api/schedule/today` — day items sorted by `(scheduled_date, route_index, created_at)`; also emits `route_legs` (distance/duration between consecutive geocoded jobs).
- `POST /api/schedule/route-leg` — cache-fill a single leg.
- `GET /api/schedule/day` — day range.
- `POST /api/schedule/reschedule`.
- `POST /api/jobs/reorder` — atomic `route_index` update for the tech's day.
- `POST /api/schedule/optimize-route` — tech-side nearest-neighbour Haversine + optional Google Directions upgrade, cached per `(tenant, tech, date, waypoints_hash)`.
- `GET /api/routes/{tech_id}/stops`.
- `GET /api/gps/route` — historical GPS breadcrumb.

**Insta-schedule (self-service booking)** — full suite of `/instaschedule/configs`, `/bookings`, `/public/instaschedule/{slug}/slots` — customer books an open slot on a configured public page. Independent of the routing engine per se.

### 1.4 · UI surfaces

**Admin / dispatcher:**

- `/dispatch` (`DispatchBoardPage.jsx`) — Google Maps with pins, `TechLoadStrip`, `DispatchColorLegend`, `ActiveShiftsSidebar`, `LiveTechPinsLayer`, `DispatchSavingsStrip`, `UnroutedPanel`, `UnscheduledJobsPanel`.
- `OptimizeRouteModal.jsx`, `RouteOptimizationApprovalModal.jsx`, `PendingRouteOptimizations.jsx`.
- `AssignJobModal.jsx`, `DispatchSchedulePanel.jsx`.
- `RouteDetailsList.jsx` — sequenced stops list.
- `ShiftRouteDialog.jsx`.

**Schedule (admin + tech):**

- `TodaySchedule.jsx` / `CalendarSchedule.jsx` — day + calendar with an inline "Optimize route" action.
- `ReorderRouteModal.jsx`, `NumberedReorder.jsx` — drag-drop reorder.
- `ScheduleMap.jsx` — day map with clustering.
- `frontend/src/lib/googleMapsRoute.js` — client-side **multi-stop Google Maps deep-link builder** for bulk-selected jobs. Sorts by `(scheduled_date, route_index/route_order, tech_user_id)`. Caps at Google Maps consumer limit of **10 stops** (destination + 9 waypoints). Surfaces `capped`, `usedCount`, `droppedNoAddress` for toast messaging.

**Mobile (untouched by this dispatch — inventoried only):**

- `mobile/src/components/schedule/DailyRouteMap.{tsx,native,web}.tsx` — route map on tech's phone.
- `NavigateRouteButton.tsx` — opens the platform's native maps app with the day's stops.
- `NavigateJobButton.tsx` — single-stop navigation.
- `OptimizeRoutePreview.tsx` — "Reorders N stops. X mi saved, Y min saved." confirm modal for the tech-proposed re-order.
- `OnMyWayButton.tsx`, `CouldNotServiceButton.tsx` — stop lifecycle actions.

### 1.5 · Optimizer engine

**Backend algorithm** (`services/route_optimizer.py`, 509 LOC):

- Haversine great-circle in miles, `AVG_SPEED_MPH = 30`, 2-minute per-stop settle-in penalty.
- **Pinned statuses** (`completed`, `could_not_service`, `skipped`, `cancelled`) preserve their `route_index` and are excluded from reshuffling — critical for mid-day re-optimization semantics.
- Two-phase: (1) local nearest-neighbour heuristic, (2) optional upgrade to **Google Routes API v2** with `optimizeWaypointOrder: true` when the day has ≤ `GOOGLE_DIRECTIONS_MAX_WAYPOINTS = 25` reshufflable stops.
- Post-pass: `zip_cluster_swap_pass` — a small 2-opt-flavour improvement pass on the Google order.

**Routes API call** (`services/google_maps/directions.py`, `_ENDPOINT = "routes.googleapis.com/directions/v2:computeRoutes"`):

- Currently sends `"routingPreference": "TRAFFIC_UNAWARE"` — see §4.
- Returns polyline + per-leg duration/distance + `optimizedIntermediateWaypointIndex` (the resolved order).
- BYO-key dispatcher (`services/maps/dispatcher.py`) allows tenant-provided keys.

---

## 2 · Candidate interpretations of "multi-stop routing enhancement"

Given the maturity of what exists, "multi-stop routing enhancement"
maps onto one of the following gaps. Each entry lists **partial
support in the codebase**, **user impact**, and a **rough LOC
estimate** for a first-pass implementation.

### A. Traffic-aware optimization (RECOMMENDED)

**What's missing:** `services/google_maps/directions.py` currently
passes `"routingPreference": "TRAFFIC_UNAWARE"` on both the optimize
path and the compute-no-optimize path. Google Routes API v2 supports
`TRAFFIC_AWARE` (cheap, real-time only) and `TRAFFIC_AWARE_OPTIMAL`
(expensive, historical + real-time). For a field-service business
running morning routes through metro traffic, this is a direct ETA
accuracy win and a directly measurable "minutes saved" delta on the
dispatch savings strip.

**Partial support:** the entire wiring exists — Routes API is
already called, `savings` are already computed, mobile
`OptimizeRoutePreview` already surfaces "Y min saved". Only the
routing-preference flag + optional `departureTime` need to flow
through.

**Third-party dep:** none new. **Cost impact:** Routes API v2
`TRAFFIC_AWARE_OPTIMAL` is billed at the higher SKU. Need a config
flag so admins can trade cost for accuracy.

**LOC:** ~150–250 (routing-preference param, admin setting,
propagation through optimizer + dispatch board, unit tests).

### B. Time-window / service-window constraints on optimizer

**What's missing:** the current optimizer optimises **distance** only.
`jobs` docs carry `scheduled_start` / `scheduled_end` but the
optimizer does not treat them as constraints — it will happily
reorder a "must arrive before 10 AM" stop to the end of the day.
There is no `service_window_start` / `service_window_end` field on
customers or on jobs at all — a genuine schema gap.

**Partial support:** optimizer already respects `PINNED_STATUSES`,
so the machinery to exclude subsets exists. Adding window
constraints is additive.

**Third-party dep:** none — pure algorithm change. Google Routes
API v2 does NOT natively support arbitrary time windows through the
public interface; those would need to be enforced pre-call (drop
windows to the heuristic and only pass compatible orderings to
Google) or post-call (reject Google's order if it violates a
window and fall back to the heuristic).

**LOC:** ~400–600 (schema field, migration, optimizer changes,
API params, dispatch board UI hint, tests).

### C. Chained-batch multi-stop navigation URL (10-stop cap mitigation)

**What's missing:** `frontend/src/lib/googleMapsRoute.js` hard-caps
at 10 stops (Google Maps consumer limit). When a tech has 12 stops,
the current UX drops stops 11-12 silently with an info toast. A
"chained" navigation (open Maps with stops 1-10; when the tech
finishes stop 10, offer to open a second Maps window with stops
10-12) or a platform-detected fallback (Waze free-tier honours more
stops with a paid Waze Carpool tier; Apple Maps has different caps)
would eliminate the silent-drop UX defect.

**Partial support:** the URL builder exists and is unit-tested
(`bulk-navigate-route.test.jsx`). Adding batch chaining is
front-end only.

**Third-party dep:** none.

**LOC:** ~80–150 (pure JS in `googleMapsRoute.js` + a "continue
route" prompt + tests).

### D. Live re-optimize remaining stops on the tech's phone

**What's missing:** on the tech mobile, mid-day (3/8 stops done),
the OptimizeRoutePreview surface exists but the trigger appears to
be admin-driven. A tech-side "Re-optimize my remaining stops"
button that respects completed / skipped stops (already pinned by
the optimizer) would reduce dispatcher load and let techs recover
from late arrivals or cancellations without radioing dispatch.

**Partial support:** backend optimizer already handles this
correctly (pinned statuses are excluded). Approval-workflow
`route-optimization/preview + request` endpoints exist and are
tech-callable per RBAC in `route_optimization_approval.py`. The
mobile UI hook is the gap.

**Third-party dep:** none.

**LOC:** ~200–300 (mobile-only wire-up — but see mobile
non-goal below).

**Excluded here** — mobile parity is the mobile specialist's
territory per the standing guardrail.

### E. Cross-tech / cross-day rebalance

**What's missing:** every optimizer surface is scoped to one tech
× one day. A "rebalance the week" surface (drag jobs across techs
and across days to level the tech-load strip, then optimize each
tech's day) does not exist. Would be a significant new UX.

**LOC:** 700+ (multi-day drag-drop UI + backend batch endpoint +
constraint solver). **Exceeds the ≤500 LOC target for this
dispatch.**

### F. Route capacity strip (heat-mark over-capacity techs)

**What's missing:** `TechLoadStrip.jsx` shows each tech's load but
doesn't heat-mark over-capacity techs (>8 stops or >6 hours) with
a warning colour. A quick colour rule + tooltip would let
dispatchers spot rebalance candidates.

**Partial support:** all the data (stops per tech, scheduled
hours) is already in the dispatch board response.

**LOC:** ~100–150 (pure UI + a config setting for the thresholds).

### G. Waze / Apple Maps deep-link platform detection

**What's missing:** `NavigateRouteButton` on mobile currently
routes to Google Maps only. Platform-detected deep links (Waze on
iOS/Android, Apple Maps on iOS, Google Maps as default) would
respect the tech's preferred navigation app.

**Excluded here** — mobile-only.

---

## 3 · Existing partial support — file-level pointers

| Candidate | Files to touch |
| --------- | -------------- |
| A · Traffic-aware | `backend/services/google_maps/directions.py` (2 payload sites); `backend/services/route_optimizer.py` (pass-through); `backend/routers/dispatch_board.py` + `backend/routers/dispatch_route_optimize.py` + `backend/routers/route_optimization.py` (accept `routing_preference` param); `frontend/src/pages/dispatch/OptimizeRouteModal.jsx` (radio toggle); `backend/routers/tenants.py` or Business Settings (admin default); new test `test_route_optimize_traffic_aware.py`. |
| B · Time-window constraints | `backend/models.py` (new fields on job + customer); `backend/routers/jobs.py` (validation); `backend/services/route_optimizer.py` (constraint pass); `backend/routers/dispatch_route_optimize.py` (respect constraints); migration `scripts/backfill_service_windows.py`; frontend `JobEditForm.jsx` + `CustomerEditForm.jsx` + `DispatchBoardPage.jsx` (window pill on pin); tests. |
| C · Chained batches | `frontend/src/lib/googleMapsRoute.js` (add `buildMapsRouteBatches`); `frontend/src/pages/schedule/{TodaySchedule,CalendarSchedule}.jsx` (chain prompt); `frontend/src/test/bulk-navigate-route.test.jsx` (batch cases). |
| D · Tech-side re-optimize | mobile only — deferred. |
| E · Cross-tech rebalance | too large for this dispatch. |
| F · Capacity heat-mark | `frontend/src/pages/dispatch/TechLoadStrip.jsx`; `frontend/src/pages/dispatch/dispatchColors.js`; a couple of new tests. |
| G · Platform deep-links | mobile only — deferred. |

---

## 4 · Third-party dependency requirements

**Already configured (no action needed):**

- `GOOGLE_MAPS_API_KEY` in both `backend/.env` and `frontend/.env` (`REACT_APP_GOOGLE_MAPS_API_KEY`).
- Google Routes API v2 endpoint wired at `services/google_maps/directions.py:31`.
- `MAPBOX_ACCESS_TOKEN` present but unused for routing (used for the Mapbox provider fallback in `services/maps/mapbox_provider.py`).
- BYO-key dispatcher in `services/maps/dispatcher.py` — tenant-provided keys already work.

**Would need action only for candidate A (traffic-aware):**

- Google Routes API v2 with `TRAFFIC_AWARE_OPTIMAL` moves to the more-expensive SKU. Rough public rate: Routes API "Advanced" tier is priced per-request; needs a tenant-level "premium routing" opt-in to avoid surprise bills. `TRAFFIC_AWARE` (mid-tier) is a reasonable default that includes real-time traffic without the historical layer.

**None of the other candidates require new keys or new SDKs.**

---

## 5 · User-value ranking (dispatcher / field-service daily use)

Ranked by *frequency of daily impact × severity of the gap it
closes*:

1. **A · Traffic-aware optimization** — dispatchers see cleaner
   ETAs and lower actual drive time on real routes. Every route
   benefits, every day. Directly measurable via the existing
   "miles/minutes saved" chip.
2. **C · Chained-batch navigation** — techs with >10 stops today
   lose stops silently. Small user base but very sharp defect
   when it bites.
3. **F · Capacity heat-mark** — dispatchers spot overload at a
   glance. Low-effort polish that improves the daily-dispatch
   loop.
4. **B · Time-window constraints** — high value but genuinely a
   schema + optimizer change. Better as a standalone P1 phase.
5. **D · Tech-side re-optimize on mobile** — high value for techs
   but deferred (mobile non-goal for this dispatch).
6. **E · Cross-tech rebalance** — high strategic value but too
   large for a single dispatch.
7. **G · Waze/Apple deep-links** — mobile-only, small quality win.

---

## 6 · Recommendation for next dispatch scope

**Recommended slice: Candidate A · Traffic-aware optimization.**

**Why:** highest daily-impact, smallest LOC, zero new schema, zero
new SDK, zero new keys, direct measurable win on the existing
"savings" telemetry. Every optimize call — dispatch board, day
optimizer, tech-proposed re-order — benefits without changing
its public contract.

**Proposed shape (≤300 LOC total):**

- **Backend (~150 LOC):**
  - `services/google_maps/directions.py` — accept `routing_preference` kwarg on `optimize_route` + `compute_route_no_optimize`; default to `TRAFFIC_UNAWARE` for byte-for-byte back-compat.
  - `services/route_optimizer.py` — plumb the same kwarg through `try_google_directions_optimize`.
  - `routers/dispatch_route_optimize.py`, `routers/dispatch_board.py`, `routers/route_optimization.py` — accept optional `traffic_aware: bool` in the request body, default `False`; when `True` map to `TRAFFIC_AWARE` (mid-tier — the sensible default; the OPTIMAL upper tier stays admin-opt-in for later).
  - Business Settings — new tenant-level `default_route_traffic_awareness` (`off` | `on`) stored under existing routing settings collection. Never `OPTIMAL` by default.
  - New audit event on the optimizer response so the "savings" strip can attribute wins to the traffic-aware pass vs. the plain nearest-neighbour pass.

- **Frontend (~100 LOC):**
  - `OptimizeRouteModal.jsx` — a single "Use current traffic (recommended)" toggle above the Apply button, seeded from the tenant default.
  - `DispatchBoardPage.jsx` — persist the toggle in URL params so refreshes retain the choice.

- **Tests (~50 LOC):**
  - `test_route_optimize_traffic_aware.py` — three cases: default off ⇒ existing behaviour byte-for-byte; toggle on ⇒ Routes API payload includes `"routingPreference": "TRAFFIC_AWARE"`; tenant default on ⇒ backend seeds the flag when the body omits it.

**Non-goals for the follow-up dispatch:**

- No `TRAFFIC_AWARE_OPTIMAL` in this slice — it's a premium SKU and
  needs a billing-aware toggle. Explicit follow-up ticket.
- No time-window / service-window fields (Candidate B) — separate
  dispatch.
- No mobile changes (Candidate D + G) — mobile specialist.
- No `dispatch_route_orders` schema changes.

**OpenAPI count:** unchanged at 1731 — this dispatch is a
parameter addition, not a new endpoint.

**Alternative smaller slice** if the user prefers pure-UI and
zero external-cost exposure: **Candidate F · Capacity heat-mark**
(~150 LOC, pure frontend, no billing implications, low daily
impact but sharp polish on the dispatch board).

---

## 7 · Open questions for the user

1. **Slice pick** — A (traffic-aware), C (chained batches), F
   (capacity heat-mark), or a different candidate above?
2. **Traffic-aware billing posture** — comfortable with the mid-tier
   `TRAFFIC_AWARE` SKU as the default when the toggle is on, and
   `TRAFFIC_AWARE_OPTIMAL` gated behind a follow-up admin opt-in?
   Or should even `TRAFFIC_AWARE` require an explicit tenant setting
   before the toggle appears in the modal?
3. **Time-window feature (Candidate B)** — is this on the roadmap?
   If yes, it's a good P1 for the following dispatch; if no, we can
   skip the schema work entirely and stay in optimizer/UI polish
   territory.
4. **Multi-stop navigation cap (Candidate C)** — do we know of real
   field cases where a tech has >10 stops in a day? If common, C
   jumps to #1 priority. If rare, it stays as low-priority polish.
5. **Business Settings surface** — where should the tenant-level
   traffic-awareness default live? Under existing "Routing" section
   or a new "Optimization" subsection?

Once one candidate is picked, next dispatch is a focused
implementation (audit-only means no code was written for this
run — awaiting user alignment).
