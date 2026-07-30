# Changelog

All notable changes to Pool & Landscaping CRM are documented here.

Format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).
Entries are dated (YYYY-MM-DD, UTC) since we're not cutting semver releases yet.
Do not rewrite history — only prepend new entries at the top.

---

## 2026-07-30 — Phase 3 · Dispatch Route Optimization

### Added
- `POST /api/dispatch/route/optimize` — nearest-neighbor DRY-RUN preview with per-leg + cumulative distance and hand-order savings (`backend/routers/dispatch_route_optimize.py`).
- `POST /api/dispatch/route/apply` — persists `route_index` 0..N-1 per stop, idempotent (`backend/routers/dispatch_route_optimize.py`).
- `OptimizeRouteModal.jsx` — side-by-side compare + apply flow with skipped-jobs surface (`frontend/src/pages/dispatch/OptimizeRouteModal.jsx`).
- "NN Optimize" button in Dispatch Board · Route Details header, opens the modal for the selected tech + day (`frontend/src/pages/dispatch/DispatchBoardPage.jsx`).
- `isoDateForDayKey()` helper converting DOW tab (`mon`..`sun`) to ISO date within the current week.
- Mongo index `(tenant_id, tech_user_id, scheduled_date, route_index)` on `jobs` (created on first apply).
- Pytest suite `backend/tests/test_dispatch_route_optimize.py` — 4 tests, all passing (nearest-neighbor correctness, skipped list, apply persistence + idempotency, role gate).

### Changed
- Expo mobile schedule (`mobile/app/(app)/schedule/calendar.tsx`) sort now prefers `route_index`, falls back to `route_order`.
- Dispatch Board tech dropdown handles wrapped `{users, count}` response shape from `/api/users?role=technician`.
- Optimizer query matches `technician_id` in addition to `tech_user_id`/`assigned_to`, and matches `scheduled_date` via prefix regex to support both bare-date and full-ISO storage.

### Security
- Both endpoints inherit the `require_gps_read` router guard — Tech and Customer roles receive 403.

---

## 2026-07-29 — Phase 2 rework · Share Replay + GPS Read Lockdown

### Added
- Authed `GET /api/gps/replay/share/{share_id}` — Admin / SuperAdmin only, with view-count and last-viewer-IP-hash tracking.
- `require_gps_read` FastAPI dependency; wrapped every GPS *read* router at `include_router()` (blocks Tech + Customer, allows Manager / Dispatcher / Admin / SuperAdmin).
- Pytest coverage: `test_gps_read_lockdown.py`, `test_replay_share.py`.

### Changed
- `ShareReplayModal` copy → "Admins and Super Admins only. Customers cannot view this link."
- `POST /api/gps/pings` explicitly NOT wrapped by the read-guard — techs continue submitting pings.

### Removed
- Unauthenticated `GET /api/public/replay/{share_id}` route.

### Security
- PII scrub verified on the authed share GET payload (no phone / email / home_address surfaced).

---

## 2026-07-28 — Phase 1 · MR3 Public Widget Analytics

### Added
- `POST /api/public/widget/analytics/track` — public, no-auth, IP-hashed at persistence, sliding-window rate-limited to 60/min per (tenant, IP) with HTTP 429 on breach.
- `GET /api/widget/analytics/summary` and `GET /api/widget/analytics/timeseries` — tenant-scoped read endpoints.
- Web admin page `/admin/moderation/widget-analytics` — KPIs, Recharts time-series, top-10 widgets, range toggle.
- Expo mobile screen `mobile/app/widget-analytics.tsx` — read-only KPIs + top-10 list.
- `widget_analytics_events` collection with `(tenant_id, widget_id, ts)` and `(tenant_id, ts)` indexes.

### Security
- Raw IPs never persisted — `ip_hash` (SHA-256 with tenant salt) stored instead.
- Session-deduped impression firing inside Shadow DOM widget prevents inflation.
