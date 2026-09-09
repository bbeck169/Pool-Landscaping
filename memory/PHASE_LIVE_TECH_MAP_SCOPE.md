# Live Technician Map · Multi-Phase Scope · AUDIT ONLY

**Status:** AUDIT ONLY — no code, no schema, no migrations. Fold into
the queue after user approval.
**Author:** main agent, Feb-2026.
**User-approved decisions:** 12-color palette, browser geolocation
current-location pin, 30 s dispatch poll, enhance existing `/dispatch`
page, web + mobile parity, `MAPS_BYO_ENABLED=false` ship path.

---

## 1 · Foundational audit — what's already there

### 1.1 · Tech + crew color model (Phase 1's foundation)

**Both fields already exist and are actively used.** No schema
migration is required to store colors — Phase 1 becomes a
Settings-only pass.

| Collection | Field | Type | Coverage today |
| ---------- | ----- | ---- | -------------- |
| `db.users` (technicians) | `display_color_hex` | hex string, e.g. `"#3B82F6"` | Read by `board.tech_load[*].color_hex` in `/api/dispatch/board`, folded into `techColorById` in `DispatchBoardPage.jsx:288`, rendered on every stop pin + live-tech marker on the dispatch map. |
| `db.crews` | `color` | hex string | Used by the crew-color pin mode in `dispatchColors.js` + the crew legend. |

**Backfill gap:** many existing tech rows have `display_color_hex`
null/undefined — the frontend falls back to a hard-coded slate
color today. Phase 1's migration is: for any tech with a null
`display_color_hex`, assign a deterministic color from the 12-color
palette using `hash(user_id) mod 12`. Same for crews (already
partially colored — audit shows some crews already have `color`
set; migration is a fill-null-only pass, idempotent).

### 1.2 · Live-GPS infra (Phase 4's data source)

**Complete.** No new endpoints or Mongo collections needed for the
30 s dispatch refresh.

| Component | Where | Contract |
| --------- | ----- | -------- |
| Ping ingest | `POST /api/gps/ping` → `routers/gps_ingest.py` | Mobile POSTs on `ping_interval_foreground_s=60` (default) / `background_s=300`. Persists to `db.gps_pings`. |
| Live positions read | `GET /api/gps/live-positions` → `routers/gps_live_positions.py` | Returns array of `{user_id, user_name, lat, lon, accuracy_m, captured_at, staleness_s, address}`. **Already staleness-filters at 300 s.** Enriches with Mapbox reverse-geocoded address (cache-first). Cached per-tenant. |
| Live pins renderer | `frontend/src/pages/dispatch/LiveTechPinsLayer.jsx` | Renders one `AdvancedMarker` per live position, colored by staleness bucket (green <120s, amber <300s, gray ≥300s). Wired into `DispatchMapView` via `liveTechPositions` prop. |
| Poll | Currently `showLiveTechs` gate reads once on mount + on manual refresh | **No timer today** — Phase 4 adds a 30 s `setInterval` (debounced, cancel-on-unmount). |

**Ping frequency vs. 30 s dispatch refresh:**
Foreground mobile pings at 60 s. Dispatch refreshes every 30 s. Every
other dispatch poll will see the same ping (no new data since last
poll). This is **acceptable** — pins render sanely, staleness ticks
up by 30 s each cycle until the next ping arrives. No infra bump
needed. (**Decision-Q6** — noted below in case user wants a foreground
bump-down to 30 s in dispatch-visibility.)

### 1.3 · `/dispatch` page audit (Phase 4's canvas)

**Real name:** "Dispatch Board." Route `/dispatch`. Component
`frontend/src/pages/dispatch/DispatchBoardPage.jsx` (1097 lines).

**Current 3-column layout:**

| Column | `data-testid` | Renders today |
| ------ | ------------- | ------------- |
| Left · `lg:col-span-3` | `dispatch-left-col` | Tech dropdown, Route type pills, `SelectCustomerPanel` (search input + 0-of-N row list) |
| Center · `lg:col-span-6` | `dispatch-center-col` | Shift-in banner, savings banner, `DispatchMapView` (Google Maps, tech-colored stop pins, live-tech pins, optimized polyline) |
| Right · `lg:col-span-3` | `dispatch-right-col` | Tech Load strip, Route Details list, Unscheduled Jobs panel |

**Data source:** `GET /api/dispatch/board?day=&tech_user_id=&route_type=&global=&date=` →
returns `{tech_load, route_stops, pins, unrouted, polyline, ...}`.
`tech_load[*]` includes `tech_user_id, name, color_hex, stops[]` —
this is **already** the shape needed for the DispatchSchedulePanel.

**`PIN_COLOR_MODES`:** `tech` (default) / `crew` / `service_day` —
persisted in `localStorage` under `dispatch.pin_color_mode` and
selected via the "COLOR PINS BY" pills.

**Left column below `SelectCustomerPanel`** — currently ends. The
red-circled empty region in the user's screenshot is real. Phase
4.a slots directly there.

### 1.4 · Schedule endpoint audit (Phase 4.a data source)

`GET /api/schedule/day?date=YYYY-MM-DD` and `GET /api/schedule/today`
both delegate to `schedule_today()` in `routers/schedule.py:56`.
The per-item payload emitted at line 201–237 already includes every
field the DispatchSchedulePanel needs:

* `id, title, service_type, work_class`
* `customer_name, customer_id`
* `address, city, state, zip`
* `lat, lng` (from `site_lat/site_lng`)
* `scheduled_start, scheduled_end`
* `status, priority, route_index`

**Missing:** `technician_id` and `crew_id` — these ARE queried
server-side (line 111 filters on `assigned_technician_id`) but the
response doesn't emit them for the frontend. Adding them is a
one-line extension per item.

**One-line follow-on:** the schedule endpoint is per-user
(the caller's own day). For Phase 4.a we need ALL techs' stops on
that day. **The `/dispatch/board` endpoint already does this**
(`tech_load[*].stops[]`), so 4.a uses `board.tech_load` — no new
endpoint required.

### 1.5 · Mobile audit (Phases 3 & 5)

**Native map:** `@rnmapbox/maps` in the mobile app (mobile/app schedule
screens). Verified via `grep -r "rnmapbox" /app/mobile`. Live-tech
pins layer parity present.

**Location library:** `expo-location` is a mobile dep; used already
for the tech's own current-position pin on the native schedule map.

**Expo Web schedule map:** Leaflet + OSM tiles (per handoff note).

**No `display_color_hex`/`techColor` usage on mobile yet** —
mobile reads tech identity but does NOT render a colored dot next
to each stop today. Phase 5 folds that in.

---

## 2 · Recommended 12-color palette (colorblind-friendly)

Pulled from Tailwind 500-tier + adjustments for max hue separation
under deuteranopia + protanopia:

| # | Hex | Tailwind name | Notes |
| - | --- | ------------- | ----- |
|  1 | `#3B82F6` | blue-500     | Primary — matches existing brand accent |
|  2 | `#EF4444` | red-500      | High contrast against greens |
|  3 | `#10B981` | emerald-500  | Fresh-tech green (already used for staleness) |
|  4 | `#F59E0B` | amber-500    | Warm neutral, distinct from red |
|  5 | `#8B5CF6` | violet-500   | Cool complement to amber |
|  6 | `#EC4899` | pink-500     | Distinct from red under CVD |
|  7 | `#14B8A6` | teal-500     | Distinct from emerald |
|  8 | `#F97316` | orange-500   | Distinct from amber (warmer) |
|  9 | `#6366F1` | indigo-500   | Cool anchor |
| 10 | `#84CC16` | lime-500     | Distinct from emerald AND amber |
| 11 | `#06B6D4` | cyan-500     | Cool distinct from teal |
| 12 | `#A855F7` | fuchsia-500  | Warm complement to cyan |

Sits in `constants/tech_colors.py` (backend) + `constants/techColors.js`
(frontend + mobile shared).

---

## 3 · File list + LOC estimates per phase

### Phase 1 · Data model & backend

| File | New/Edit | LOC (est) |
| ---- | -------- | --------- |
| `backend/constants/tech_colors.py` (NEW) | +40 | 12-color palette, `assign_default_color(user_id)` deterministic hash |
| `backend/routers/settings_tech_colors.py` (NEW) | +140 | `GET /api/settings/tech-colors`, `PATCH /api/settings/tech-colors/{tech_id}` (admin-only, hex validation) |
| `backend/routers/schedule.py` | +2 | Emit `technician_id`, `crew_id` in per-item payload |
| `backend/routers/dispatch_board.py` | +0 to +5 | Verify `tech_load[*].color_hex` reads `display_color_hex` (already does per line 291 audit); noop otherwise |
| `backend/migrations/mig_tech_color_backfill.py` (NEW) | +80 | Idempotent — fills null `display_color_hex` on users + null `color` on crews via `assign_default_color()` |
| `backend/server.py` | +3 | Register `settings_tech_colors` router |
| `backend/tests/test_tech_colors.py` (NEW) | +180 | Palette invariants, hash-deterministic assignment, PATCH auth (admin-only), hex validation (regex), migration idempotency, backfill correctness |

**Total Phase 1:** ~445 LOC (backend + tests only, zero frontend).

### Phase 2 · Settings UI (web)

| File | New/Edit | LOC (est) |
| ---- | -------- | --------- |
| `frontend/src/pages/settings/TeamColorsPage.jsx` (NEW) | +260 | List of techs + crews, colored swatch, palette-chip picker, save-on-select |
| `frontend/src/constants/techColors.js` (NEW) | +30 | Mirror of backend palette |
| `frontend/src/pages/settings/SettingsShell.jsx` or router | +5 | Register `/settings/team-colors` route (admin gate) |
| `frontend/src/test/team-colors-page.test.jsx` (NEW) | +140 | RTL: click chip → PATCH fires → swatch updates; non-admin denied |

**Total Phase 2:** ~435 LOC (web only).

### Phase 3 · Schedule map "you are here" pin (web)

| File | New/Edit | LOC (est) |
| ---- | -------- | --------- |
| `frontend/src/pages/schedule/ScheduleMap.jsx` | +45 | `useGeolocation()` hook, `watchPosition` cleanup, pulsing-ring `AdvancedMarker`, silent-decline branch |
| `frontend/src/hooks/useGeolocation.js` (NEW) | +90 | Watch, permission-denied silent, throttle-to-3s |
| `frontend/src/test/schedule-current-location-pin.test.jsx` (NEW) | +150 | Mock `navigator.geolocation`, assert pin renders, assert permission-denied hides silently |

**Total Phase 3:** ~285 LOC.

### Phase 4 · Dispatch page live-map enhancement (web)

#### Phase 4.core · 30-second poll + faded-stale + legend-isolate

| File | New/Edit | LOC (est) |
| ---- | -------- | --------- |
| `frontend/src/pages/dispatch/DispatchBoardPage.jsx` | +40 | `setInterval` 30s for `fetchBoard` + `fetchLivePositions`, in-flight debounce, cancel-on-unmount, `isolateTechId` state |
| `frontend/src/pages/dispatch/LiveTechPinsLayer.jsx` | +25 | Faded style when `staleness_s > 900`, tooltip "Last seen N min ago", dim non-isolated techs |
| `frontend/src/pages/dispatch/DispatchMapView.jsx` | +20 | Accept `isolateTechId`, dim non-matching stop pins + polylines |
| `frontend/src/pages/dispatch/TechLoadStrip.jsx` | +10 | Legend row `onClick` toggles isolation |

**Total Phase 4.core:** ~95 LOC.

#### Phase 4.a · Left-column `DispatchSchedulePanel`

| File | New/Edit | LOC (est) |
| ---- | -------- | --------- |
| `frontend/src/pages/dispatch/DispatchSchedulePanel.jsx` (NEW) | +220 | Scrollable list, grouped by tech (or crew, respects `pinColorMode`), colored dot per row, applies TECH + ROUTE_TYPE + customer-search filters client-side, empty state, click-to-focus map (P2 polish behind a flag) |
| `frontend/src/pages/dispatch/DispatchBoardPage.jsx` | +8 | Mount `<DispatchSchedulePanel>` in the left column below `SelectCustomerPanel` |
| `frontend/src/test/dispatch-schedule-panel.test.jsx` (NEW) | +180 | Renders items grouped by tech · TECH filter narrows list · ROUTE_TYPE filter narrows list · customer search narrows list · empty state · isolate-legend dims correctly |

**Total Phase 4.a:** ~408 LOC.

#### Phase 4.b · Filter-chain unification (map + panel share filters)

| File | New/Edit | LOC (est) |
| ---- | -------- | --------- |
| `frontend/src/pages/dispatch/DispatchBoardPage.jsx` | +20 (net refactor) | Extract filter state into a `useDispatchFilters()` hook; pass same filtered set to `DispatchMapView` and `DispatchSchedulePanel`; ensure tech → route-type → customer-search evaluation order (left → right) is deterministic; NO backend re-fetch on filter change (client-side already) |
| `frontend/src/hooks/useDispatchFilters.js` (NEW) | +80 | Pure hook — takes `(pins, techId, routeType, customerSearch)`, returns filtered slice |
| `frontend/src/test/dispatch-filter-chain.test.jsx` (NEW) | +120 | Sequential filter application invariants |

**Total Phase 4.b:** ~220 LOC.

**Total Phase 4 (all sub-passes):** ~723 LOC.

### Phase 5 · Mobile parity (Expo native + Expo Web)

| File | New/Edit | LOC (est) |
| ---- | -------- | --------- |
| `mobile/src/constants/techColors.ts` (NEW) | +30 | Mirror the 12-color palette. |
| `mobile/src/hooks/useDeviceLocation.ts` (NEW) | +80 | `expo-location` wrapper (already-in-project), silent-decline. |
| `mobile/app/(app)/schedule.tsx` | +60 | Current-location `Marker` on the native/`@rnmapbox/maps` map + Leaflet Web equivalent. |
| `mobile/src/components/dispatch/*` | (deferred) | Native dispatch view is read-only and low-priority — most admins use desktop `/dispatch`. **Recommendation: defer to a P2 follow-up.** |
| `mobile/tests/schedule-current-location-pin.test.tsx` (NEW) | +140 | Mock `expo-location`, assert current-location marker. |

**Total Phase 5:** ~310 LOC (schedule-map parity only; dispatch-view mobile deferred).

**GRAND TOTAL across all phases:** ~2 200 LOC + tests over 5 phases.

---

## 4 · Risks / unknowns per phase

| Phase | Risk | Mitigation |
| ----- | ---- | ---------- |
| 1 | `display_color_hex` is already partially populated → migration must be idempotent (fill nulls only, never overwrite) | Migration guard: `if not user.get("display_color_hex")`. Explicit test `test_migration_never_overwrites_existing_color`. |
| 1 | Existing dispatch board depends on `tech_load[*].color_hex` — if migration ever assigns an invalid hex, the map breaks | Palette is compile-time constant of 12 vetted hexes; hex-validation regex on PATCH endpoint. |
| 2 | Admin-only gate — must use existing `require_admin` pattern, not roll a new one | Reuse `Depends(require_admin)` from `auth.py`, matching every other admin-only settings page. |
| 3 | Browser permission denial in Safari on macOS 15 sometimes throws a permanent error state — user must reset in system prefs | Silent decline (log once, hide pin). No error toast. Test asserts silent-hide. |
| 3 | Geolocation on desktop can be wildly inaccurate (IP-fallback) — pin may jump | `enableHighAccuracy: true`, min accuracy filter (>500 m → don't render), or fade the pin at low accuracy. Confirm with user before shipping (**Decision Q7**). |
| 4.core | `/dispatch/board` is not cheap for tenants with 500+ stops. Polling every 30 s might blow read-load | Add `If-None-Match` / ETag support to `/dispatch/board`; skip the pins/polyline render on 304. **Decision Q8.** Fallback: extend the poll to 60 s. |
| 4.core | 30 s poll + 60 s ping cadence means half the polls see identical positions | Acceptable — pins render sanely, staleness ticks up 30 s. **Decision Q6** (do we drop mobile foreground ping to 30 s when the app is visible?) |
| 4.a | Grouping by tech vs. crew — should the panel respect `PIN_COLOR_MODES` selection? | **Decision Q3** — recommendation: yes, mirror the map's grouping. |
| 4.a | Click-schedule-item → focus map — nice polish, but scope-creep risk | Ship 4.a WITHOUT bi-directional focus; add behind a `?experimental_dispatch_focus=1` flag. |
| 4.a | Filter chain: does map-region pan re-filter the schedule? | Explicit spec answer: NO. Only TECH/ROUTE_TYPE/customer-search filter; map region is view-only. |
| 4.b | Existing filters are half-implemented client-side, half in backend query params | 4.b centralises client-side. Backend query stays for the initial fetch (day/global); refinement is client-only. |
| 5 | Native dispatch view is out-of-scope per recommendation. Sync gate: colors must fetch from the same Settings endpoint | Both platforms hit `GET /api/settings/tech-colors` (Phase 1) — single source of truth. |
| 5 | `@rnmapbox/maps` current-location marker vs. `@rnmapbox/maps`'s built-in `UserLocation` — pick one | Recommend the native `UserLocation` component + a shape override — less code, better accuracy. Confirm with `e1_expo_frontend_dev`. |

---

## 5 · Decisions to route to user BEFORE Phase 1 code ships

### Q1 (Blocker) · Reuse `display_color_hex` or add new `color` field?

`db.users.display_color_hex` already exists and is used across the
dispatch board. Recommendation: **REUSE it**, no schema addition.
Phase 1's migration becomes a null-fill on both `users.display_color_hex`
and `crews.color`. No new field, no new index.

### Q2 (Blocker) · Palette confirmation

Approve the 12-color palette in §2? Colorblind-friendly Tailwind
500-tier. Any brand-color slot preferences (e.g. slot #1 must match
company blue)?

### Q3 · DispatchSchedulePanel grouping

Should the panel's tech/crew grouping mirror the map's
`PIN_COLOR_MODES` selection (tech / crew / service_day)?
Recommendation: **YES** — same source of truth. `service_day` mode
falls back to `tech` grouping in the panel since there's no
day-of-week grouping semantic for the intra-day view.

### Q4 · P2 polish: schedule → map focus

Should clicking a schedule-panel row focus / zoom the map on that
stop's pin? Ships behind a flag if so — otherwise no click behavior.

### Q5 · Current-location pin on admin-viewing-a-tech screens

When an admin views a tech's schedule, whose current location
should the pin show?
* (a) The admin's own browser location (default recommendation —
  matches user's "browser geolocation" decision literally).
* (b) The tech's last GPS ping (data source: `/api/gps/live-positions`).
* (c) Neither — hide the pin on admin-viewing-tech.

### Q6 · Foreground ping cadence bump

Currently 60 s. Dispatch polls every 30 s. Do we drop foreground
ping to 30 s while the app is dispatch-visible? Recommendation:
**NO** — battery cost > refresh-lag benefit. Ping stays 60 s.

### Q7 · Geolocation accuracy threshold

Below what accuracy (in meters) should we hide the current-location
pin? Recommendation: `> 500 m → hide` (typical desktop IP-based
fallback lands at ~1-5 km).

### Q8 · Dispatch-board polling cost

Should we ship an ETag/If-None-Match on `/api/dispatch/board` so
the 30 s poll skips the pin/polyline re-render when nothing has
changed? Cheap read-load insurance, ~40 LOC. Adds one round-trip
save per 30 s tick on quiet boards.

---

## 6 · Ship-order recommendation

1. **Phase 1** (backend + migration + settings API + tests) — 1
   PR. No user-visible change yet, but unblocks Phase 2.
2. **Phase 2** (Settings UI) — 1 PR. Admin can now edit colors;
   changes flow to the dispatch board automatically because the
   board already reads `display_color_hex`.
3. **Phase 4.core + 4.a + 4.b** batched — 1 PR. The dispatch page
   gets its full live-map treatment + the schedule panel + the
   unified filter chain. This is the "wow" ship.
4. **Phase 3** (schedule current-location pin) — small PR, low risk.
5. **Phase 5** (mobile parity) — route to `e1_expo_frontend_dev`
   with the color palette + Phase 1 API URL baked into the brief.
   Native dispatch view is DEFERRED.

Each phase gates on the previous phase's test suite being green
plus a user acceptance walkthrough of the preview environment.

---

## 7 · Out of scope (explicit deferrals)

* Native dispatch view on mobile — most admins use desktop.
* Real-time WebSocket push (instead of 30 s poll) — polling is
  simpler; upgrade only if reads become a load problem.
* Historical route replay ("show me tech X's actual GPS trail
  today vs. planned route") — separate feature ask.
* Tech color rotation policies (e.g. "reassign colors on hire
  churn") — palette assignment is deterministic and stable per
  user_id; churn is a manual admin task.
* Adjusting existing `dispatchColors.js` palette (day + crew) —
  those are already product-vetted; only the tech palette is new.

---

## 8 · What this audit did NOT do

* No code changes. `git status` shows only `/app/memory/PHASE_LIVE_TECH_MAP_SCOPE.md`
  (this file) as new.
* No DB writes. No index changes. No env changes.
* No test files created.
* No external repo cloned/pushed.
* No Chunk 3 files touched.
