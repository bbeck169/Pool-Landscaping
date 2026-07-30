# Changelog

All notable changes to Pool & Landscaping CRM are documented here.

Format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).
Entries are dated (YYYY-MM-DD, UTC) since we're not cutting semver releases yet.
Do not rewrite history — only prepend new entries at the top.

---

## 2026-07-30 — Phase 5b · AEO AI Visibility Tracker + LLM Fix Recs

### Added
- `services/aeo_visibility.py` — probe runner (5 default query templates × 3 providers), scoring math (+60 mention / +20 first-para / +15 domain citation / +5 competitor-context), month cost cap ($5 default via `AEO_VISIBILITY_MONTHLY_CAP_USD`), duplicate-run cooldown (20h), sliding-window fix-rate-limiter (5/hour/tenant), dashboard + history aggregators, `daily_visibility_scan()` cron job.
- `services/aeo_fixes.py` — per-sub-signal LLM fix generator; schema + llms_txt fall through to Phase 5a generators (no LLM). FAQ / passages / entity_clarity call Claude via `EMERGENT_LLM_KEY`.
- `routers/aeo.py` — 5 new endpoints: `POST /api/aeo/visibility/run-now`, `GET /api/aeo/visibility/history`, `GET /api/aeo/visibility/dashboard`, `POST /api/aeo/fixes/generate`, `POST /api/aeo/fixes/{id}/apply`, `GET /api/aeo/fixes/pending`.
- Collections: `aeo_visibility_probes`, `aeo_probe_runs`, `aeo_fixes`.
- APScheduler job `aeo_visibility_scan` at hour `AEO_VISIBILITY_CRON_HOUR_UTC` (default 07:00 UTC) — iterates tenants with `aeo_visibility_enabled=True`, skips if latest probe < 20h old, writes an audit row.
- Web admin — two new tabs on `/admin/marketing/aeo`: **AI Visibility** (KPIs / Recharts line / cooldown-aware Run scan now / probe table) and **Fixes** (scan-ID input, Generate button, priority-badged cards with Copy + Mark done).
- Pytest suite `backend/tests/test_aeo_visibility.py` — 9 tests: scoring math (high + low), cost cap, cron cooldown via HTTP, schema fix `<script>` block, rate-limit 429, role guard (parametrized × 2), empty dashboard shape.

### Changed
- LLM probe execution is dependency-injectable — pytest stubs bypass Emergent entirely.

### Security
- All 5 new endpoints reject Tech + Customer roles with 403.
- Fix-generation cross-tenant scan lookup returns 404 (never leaks another tenant's scan_id).
- Cost cap enforced before every probe write; capped tenants receive `cost_capped=true` in response and no probes are written.

---

## 2026-07-30 — Phase 5a · AEO Suite (Auditor + JSON-LD + LLMs.txt)

### Added
- `services/aeo_auditor.py` — pure signal parsers (schema completeness, FAQ presence, llms.txt probe, passage-length median, entity clarity) + weighted `overall_aeo_score` (schema 30 / faq 20 / llms_txt 15 / passages 15 / entity_clarity 20).
- `services/aeo_generators.py` — `generate_jsonld` (LocalBusiness / Organization / Service / FAQPage / HowTo builders, minified & JSON-validated) + `generate_llms_txt` (concise + full styles following llmstxt.org spec).
- `routers/aeo.py` — `POST /api/aeo/jsonld/generate` and `POST /api/aeo/llms-txt/generate`; both admin+/manager only, tenant-scoped, auto-fill from tenant profile.
- SEO scan output now includes `aeo_signals` block on every completed scan (backwards-compatible — existing SEO fields unchanged).
- Web admin route `/admin/marketing/aeo` with 3-tab page: **Auditor**, **JSON-LD Generator**, **LLMs.txt**. All tabs include Copy buttons and install-instructions callouts.
- Pytest suite `backend/tests/test_aeo.py` — 9 tests: high-score/low-score/llms.txt fetch/jsonld valid/llms.txt concise+full/role guard (parametrized × 2)/live jsonld endpoint/live llms endpoint.

### Changed
- `services/seo_scanner.py` — `run_scan` now computes AEO signals via a best-effort second `httpx.AsyncClient` block; failure is logged and stored as `aeo_signals: null`, never breaks a scan.

### Security
- Both new endpoints reject Tech + Customer roles with 403.
- llms.txt fetch is guarded against SPA fallback pages (requires `text/plain`/`text/markdown` content-type OR a body that starts with `"# "`).

---

## 2026-07-30 — Phase 4 · Drag-Drop Unscheduled Jobs with Auto-Insert

### Added
- `POST /api/dispatch/route/insert` — auto-inserts an unscheduled job at the cheapest-position slot in a (tech, date) route via added-leg-distance minimization; shifts subsequent `route_index` on write (`backend/routers/dispatch_route_insert.py`).
- `GET /api/dispatch/route/unscheduled-jobs` — tenant-scoped listing of jobs with no tech and no `scheduled_date` for the Dispatch Board drag source.
- `UnscheduledJobsPanel.jsx` — right-column panel; each row is a `useDraggable` source with fallback "Assign" button (`frontend/src/pages/dispatch/UnscheduledJobsPanel.jsx`).
- `AssignJobModal.jsx` — popup with Day + Tech pickers that hits the same `/insert` endpoint (`frontend/src/pages/dispatch/AssignJobModal.jsx`).
- `RouteDetailsDropZone` — inline droppable wrapper around the Route Details panel; outline + badge appear on hover (armed = blue, needs-filter = orange).
- Pytest suite `backend/tests/test_dispatch_route_insert.py` — 6 tests: cheapest-slot correctness, empty-route insert, missing-coords 422, already-scheduled 409, role gate, cross-tenant 404.

### Changed
- Dispatch Board wraps its Safe container in `<DndContext>` (`@dnd-kit/core`) with a 5px pointer activation constraint.
- Success toast on insert format: `Inserted "<title>" at position N/M · +X.X km`.

### Security
- Both new endpoints inherit the `require_gps_read` guard — Tech and Customer receive 403.

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
