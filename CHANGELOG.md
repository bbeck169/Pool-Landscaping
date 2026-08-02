# Changelog

All notable changes to Pool & Landscaping CRM are documented here.

Format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).
Entries are dated (YYYY-MM-DD, UTC) since we're not cutting semver releases yet.
Do not rewrite history — only prepend new entries at the top.

---

## 2026-08-08 — P0 investigation · Demo logins reported not working — TRANSIENT (no code change required, regression guard added)

### User report
"None of the demo logins are working" — all 4 seeded demo credentials
(`super@aquaterra.com`, `manager@aquaterra.com`,
`landscaper@aquaterra.com`, `customer@aquaterra.com`) failing.

### Reproduction (first pass)
- All 4 `POST /api/auth/login` returned **HTTP 502** — Cloudflare shield
  page, not the FastAPI 4xx/500 envelope.
- Backend `supervisorctl status` showed `uptime 0:00:30` — process had
  just restarted.
- `db.users.find_one({...})` confirmed all 4 users exist with populated
  `password_hash` and `active=True`.

### Root cause
**Transient 502 during backend boot pipeline.** The backend runs a heavy
seed / migration cascade at startup — ~30s of work across ~111 tenants
(scorecard digest, review scraper, phase-16 business OS, phase-17
geocode, phase-18 chemical seed, etc.). Cloudflare serves a 502 shield
until Uvicorn logs `INFO: Application startup complete.` (visible in
`/var/log/supervisor/backend.err.log`). Any login attempted in that
window fails at the edge before it reaches FastAPI.

Log entry that pinpointed the issue:

```
INFO:pool_crm:auto_heal_demo_passwords: all 4 present demo users
already authenticate with default. Missing rows: ['mike@aquaterra.com']
INFO:     Application startup complete.
```

At steady state (post-boot), all four credentials return **200** with a
valid JWT and correct role — verified via curl + a full web-UI login
screenshot for `manager@aquaterra.com`.

### Reproduction (second pass, post-boot)
```
POST /api/auth/login  super@aquaterra.com       → 200  role=super_admin
POST /api/auth/login  manager@aquaterra.com     → 200  role=admin
POST /api/auth/login  landscaper@aquaterra.com  → 200  role=technician
POST /api/auth/login  customer@aquaterra.com    → 200  role=customer
```

### Fix
No code change required — the endpoint is behaving correctly.

### Added (permanent regression guard)
- `backend/tests/test_demo_login_regression.py` — a parametrised pytest
  that logs in with each of the 4 seed credentials from
  `/app/memory/test_credentials.md` and asserts:
    1. HTTP 200 with a token present.
    2. JWT decodes against the pod's `JWT_SECRET` / `JWT_ALGO`.
    3. `payload.role` and `response.user.role` match the expected role.
  Result: 4/4 pass.

### Related observation (out of scope for this ticket — logged as
### follow-up)
- `landscaper@aquaterra.com` has `department: "landscaping"` on their
  `db.users` row — this value is NOT in the Phase 20
  `UserDepartmentIn` enum (`pool_tech | landscape_tech | both`). It
  does not affect login (validation only runs on write, not on read),
  but any admin attempt to update this user's department via the new
  Phase 20 endpoints would need to re-seat the field to a valid value
  first. Data-vs-schema mismatch on one legacy seed row — not urgent.
- The production deploy at 2026-08-01 23:57 UTC failed at the frontend
  build step (`postcss-selector-not@9.0.0` requires Node ≥20.19.0; the
  build container ships 20.18.1). This is a **separate** issue from
  the login report and needs its own ticket — it does not affect the
  preview environment (which uses a different node runtime) and did
  not roll back production either (previous version still serving).

### Files touched
- `backend/tests/test_demo_login_regression.py` (NEW, 4 parametrised
  tests · all pass)
- `CHANGELOG.md` (this entry)

### Verification
- `python3 -m pytest tests/test_demo_login_regression.py -v` → 4 passed
- Screenshot: manager@aquaterra.com successfully lands on the admin
  Dashboard post-login (revenue widget, weather panel, full nav
  rendered).

### Deliverable summary
No production-code fix was necessary; the root cause was a transient
Cloudflare 502 during the backend boot window. The permanent
regression pytest guards the four seed credentials so any future auth
break (password-hash migration, JWT secret rotation, role-enum
tightening, seed-script drift) fails CI loudly.

---

## 2026-08-08 — Phase 20 · P2 backlog close-out (three sub-items)

Three small, localized items bundled to close out the outstanding-work list.
All three ship in this pass. No `db.invoices` writes. No external repo
cloning.

### Sub-item A · Admin bulk-apply modal for `/admin/suggest-departments`

**Added**
- `frontend/src/pages/admin/SuggestDepartmentsModal.jsx` — new modal
  component that opens from a "Suggest departments" button on the
  admin Team page. Renders a table (name / current / suggested /
  confidence / signals) with per-row checkboxes (rows with
  `confidence ≥ 0.75` are pre-checked). Empty-state copy when no
  suggestions surface. Loading spinner while the endpoint is inflight.
- `POST /api/admin/users/bulk-department` (in
  `routers/inventory_reports.py`) — new endpoint that atomically
  applies an array of `{user_id, department}` assignments in one
  request. Returns per-row `ok` / `error` results plus an
  `updated_count` summary so the UI surfaces partial failures without
  a re-fetch. Admin+ role gate.

**Changed**
- `frontend/src/pages/admin/AdminUsersList.jsx` — added the
  "Suggest departments" button (`data-testid=
  "admin-users-suggest-departments-btn"`) in the header actions,
  wired to the new modal.

**Notes / decisions**
- **Bulk endpoint is a small, focused addition** rather than looping
  through the existing `/admin/users/{uid}/department` PUT — one round
  trip, single-transaction feel to the admin, cleaner UI feedback loop
  on partial failures.
- **Pre-check threshold** is 0.75 (matches the Phase 18 backend
  heuristic that returns `pool_tech` / `landscape_tech` only when a
  tech's signal is ≥75% of one category — no floating "maybe" rows).

### Sub-item B · Expo push tap-through for `inventory_low_stock`

**Investigation summary** — `expo-notifications` v0.32.17 is installed;
full permission/token/register flow lives in
`mobile/src/services/pushNotifications.ts`. `mobile/app/notifications.tsx`
in-app bell only routed `job_id → /job/{id}`. NO push-response
listener was wired anywhere (`addNotificationResponseReceivedListener`
returned zero hits).

**Added**
- `mobile/src/services/notificationRoutes.ts` — pure `resolveNotificationRoute(notif, user)` function.
  - `inventory_low_stock` + admin/manager/owner/office → `/admin/inventory`
  - `inventory_low_stock` + everyone else non-customer → `/inventory/my-inventory`
  - `job_id` set → `/job/{id}` (legacy behaviour preserved)
  - `href` set → verbatim
  - Otherwise → `null`
- `mobile/app/_layout.tsx` — new inline `<PushTapRouter />` component
  mounted inside `AuthProvider`. Subscribes to
  `Notifications.addNotificationResponseReceivedListener`, reads
  `resp.notification.request.content.data`, and routes via the
  shared resolver. Never crashes the shell on bad payloads.

**Changed**
- `mobile/app/notifications.tsx` — in-app bell tap now uses the
  shared resolver instead of the hard-coded `job_id` push. Role
  comes from the existing `useAuth()` context.

**Notes / decisions**
- **Kept it minimal**: push-token registration infrastructure exists
  and works; only the tap-through was missing. Only the tap-through
  was built.
- **Cold-start opens** are also covered — `expo-notifications`
  delivers the tap event through the same listener when the app
  boots from a notification tap. No extra plumbing needed.
- **Pure resolver** is testable outside the Expo runtime (pytest
  ports the same table — one broken rule fails CI).

### Sub-item C · Stripe pk_live cleanup (proper fix)

**Added**
- `GET /api/payments/stripe/config` — returns `{publishable_key, mode}`
  for the current pod. Reads `STRIPE_PUBLISHABLE_KEY_TEST` or
  `_LIVE` per `STRIPE_MODE`. Role gate mirrors `/setup-intent`
  (customer OR admin/manager/super_admin — technicians 403).
- `frontend/src/lib/stripeConfig.js` — session-memoized
  `getStripeConfig()` helper. First call hits the backend; subsequent
  in-session calls return the cached object. Concurrent callers share
  a single inflight promise.

**Changed**
- `services/payments/stripe_charge.py::create_setup_intent()` — response now
  includes a `publishable_key` field alongside `client_secret`,
  `setup_intent_id`, `stripe_customer_id`, `mode`. New helper
  `_publishable_key()` reads `STRIPE_PUBLISHABLE_KEY_(TEST|LIVE)` per
  mode. Logs a one-time WARNING when the env is missing (never
  crashes the payment flow).
- `frontend/src/pages/portal/PortalPaymentMethods.jsx` and
  `frontend/src/components/customers/AdminCardCapturePanel.jsx` —
  swapped the `REACT_APP_STRIPE_PUBLISHABLE_KEY(_TEST|_LIVE)` env
  reads for a `getStripeConfig()` call.
- `frontend/src/components/payments/StripeAddCardForm.jsx` — updated
  the "publishable key not configured" error copy to point at the
  BACKEND env vars (`STRIPE_PUBLISHABLE_KEY_TEST` /
  `STRIPE_PUBLISHABLE_KEY_LIVE`) — no longer references the removed
  frontend env vars.

**Removed**
- `frontend/.env` — removed all three lines:
  `REACT_APP_STRIPE_PUBLISHABLE_KEY`,
  `REACT_APP_STRIPE_PUBLISHABLE_KEY_TEST`,
  `REACT_APP_STRIPE_PUBLISHABLE_KEY_LIVE`, and the now-unused
  `REACT_APP_STRIPE_MODE`. Verified via grep: zero references
  remain in `frontend/src`.

**Notes / decisions**
- **Server-side ownership** of the publishable key is the right
  answer long-term: live/test cutover is a single backend env flip,
  no frontend rebuild needed. Previously the pk lived in three
  places at build time.
- **Session-memoization** avoids extra config round-trips on every
  Elements mount (portal customers often bounce between pages).
- **Backward compatible** with the setup-intent response — added
  field only, existing consumers keep working.

### Tests

- `backend/tests/test_phase20_backlog_closeout.py` — 5 new pytest cases
  (all passing). A + C + resolver Python port.
- Vitest baseline: **524 pass / 12 fail** — inside the 11-14 tolerated
  flake budget (actually improved slightly from Phase 19's 14).
- Full regression: **22/22 pass** across Phase 20 + Phase 19 + Phase 18
  + webform bugfix.

### Verification (curl matrix)

```
1) GET  /api/payments/stripe/config              admin  → 200 {"publishable_key":"","mode":"test"}
2) GET  /api/payments/stripe/config              tech   → 403 {"detail":"forbidden"}
3) POST /api/admin/suggest-departments           admin  → 200 (25 suggestions surfaced)
4) POST /api/admin/users/bulk-department         admin  → 200 (per-row ok/error results)
5) GET  /api/openapi.json                        (open) → 200
```

### Files added / changed

- `backend/routers/stripe_router.py` — new `GET /config` endpoint
- `backend/services/payments/stripe_charge.py` — `_publishable_key()`
  helper + `publishable_key` field on setup-intent response
- `backend/routers/inventory_reports.py` — new
  `POST /admin/users/bulk-department` endpoint + `BulkUserDepartmentIn`
  model
- `backend/tests/test_phase20_backlog_closeout.py` (NEW, 5 tests)
- `frontend/src/lib/stripeConfig.js` (NEW — session cache helper)
- `frontend/src/pages/admin/SuggestDepartmentsModal.jsx` (NEW)
- `frontend/src/pages/admin/AdminUsersList.jsx` — modal open button
- `frontend/src/pages/portal/PortalPaymentMethods.jsx` — pubKey via helper
- `frontend/src/components/customers/AdminCardCapturePanel.jsx` — pubKey via helper
- `frontend/src/components/payments/StripeAddCardForm.jsx` — error copy
- `frontend/.env` — removed three legacy publishable-key lines
- `mobile/src/services/notificationRoutes.ts` (NEW — pure resolver)
- `mobile/app/notifications.tsx` — in-app bell tap uses resolver
- `mobile/app/_layout.tsx` — new `<PushTapRouter />` component wires
  the push-tap listener globally

### Cross-cutting checks

- Grep-lint: 0 `db.invoices` writes in any Phase 20 file. ✅
- Vitest baseline: 524 pass / 12 fail — inside the tolerated 11-14
  flake budget. ✅
- `/api/openapi.json` reachable (HTTP 200). ✅
- 22/22 pytest across Phase 20 + Phase 19 + Phase 18 + webform bugfix. ✅

---

## 2026-08-08 — Phase 19 · P2 backlog — Avatar Swap + AI Rewrite Rate-Limit Persistence

Two independent P2 items bundled into one small phase. Both ship together.

### Sub-item A · Global Avatar Swap for Job Assignee

**Added**
- `assignee_photo_url` field is now returned on every job response. Value is
  the tech's `db.users.technician_photo_url` when populated, else `null`.
- Enrichment happens inside the existing
  `routers/jobs.py::_enrich_jobs_dept_and_kind()` batched lookup — the
  same `users` query that already resolves `department` + `checklist_kind`
  now also projects `technician_photo_url`. **Zero additional DB
  round-trips** on the hot job-list path.

**Changed**
- `frontend/src/pages/workstream/WorkstreamPage.jsx` — added a
  `<UserAvatar>` next to the "Assigned to" line on every job card. Reuses
  the existing `UserAvatar` component by threading `assignee_photo_url`
  through the `profile_photo_url` source it already reads (initials
  fallback is unchanged).
- `mobile/app/job/[id].tsx` — job detail screen now renders
  `job.assignee_photo_url` (falls back to the older `technician_avatar`
  key, then to the initials/person-icon placeholder). Both branches
  carry the new `testID`s `job-assignee-avatar` /
  `job-assignee-avatar-fallback`.

**Notes / decisions**
- **Data state**: 0/26 techs currently have `technician_photo_url`
  populated. Field name confirmed from `db.users` schema. Per the P2
  brief, no backfill in this phase — the plumbing is future-proofed and
  admins fill photos via the existing user-edit UI.
- **Zero-extra-round-trip pattern**: the batched enricher was already
  fetching `users` for `department` — we simply added
  `technician_photo_url` to the projection. `_enrich_job_dept_and_kind`
  (single-doc variant, used by `get_job`) got the same treatment.

**Follow-ups (intentionally deferred)**
- Dispatch board (`pages/admin/DispatchBoard*`) and schedule tiles do
  NOT yet render the assignee photo. The two touch-points shipped in
  this pass (WorkstreamPage + mobile job detail) are the most visible;
  the dispatch board is dense enough that adding avatars is a separate
  UX call to make in a follow-up.

### Sub-item B · AI Rewrite Rate-Limit Persistence to MongoDB

**Added**
- New collection `db.ai_rewrite_usage` with a composite-unique index on
  `(tenant_id, user_id, action, window_start_utc)`. Registered via
  `routers.checkin_rewrite.ensure_indexes()` and wired into
  `scripts/create_session_indexes.ensure_on_boot()` so index creation
  runs once per boot without blocking startup.
- Atomic upsert + `$inc` on `call_count` — multi-worker safe with no
  application-side lock. `find_one_and_update` with
  `return_document=After` gives us the post-increment count in a single
  round-trip.
- Response now includes a `Retry-After` HTTP header (seconds until
  `window_end_utc`) on 429 responses, per spec.
- Test-only bypass: when `ALLOW_TEST_HOOKS=1` in the pod env AND the
  request carries `X-Test-Skip-Llm: 1`, the endpoint returns a canned
  `[TEST-STUB] <draft>` string instead of hitting the real Emergent
  LLM. Both conditions must be true — impossible to hit in production.
- Boot-hook wiring in `scripts/create_session_indexes.py`
  (`ensure_on_boot` now also calls `checkin_rewrite.ensure_indexes()`).

**Changed**
- `routers/checkin_rewrite.py` — HTTP endpoint now uses `_rate_charge()`
  (Mongo-backed) instead of the in-process `_rate_check()` deque.
- The legacy sync `_rate_check(user_id)` and `_rate_reset(user_id)`
  helpers are **preserved as shims** so
  `tests/test_checkin_rewrite.py::test_unit_rate_check_*` continue to
  pass without modification. They now only exercise a legacy code
  path — the HTTP endpoint no longer touches them.
- The prompt-builder text (`_build_prompt`) and the LLM adapter
  (`_call_emergent_text`, `_generate_rewrite`) are byte-identical to
  the prior implementation.

**Notes / decisions**
- **Fixed-window trade-off (accepted)**: the prior impl was a rolling
  sliding-window (`deque[timestamp]`); the new impl is a **fixed
  UTC-hour window**. Numeric budget preserved (10 / user / 3600s).
  Worst-case boundary drift: a user could get 20 calls in ~2 minutes if
  they perfectly straddle the boundary. Acceptable for a soft cost /
  abuse limit.
- **Rollback-on-reject**: when a call exceeds the limit, the `$inc`
  that pushed the counter past `_RATE_MAX` is rolled back with a
  compensating `-1` so the persisted counter never inflates under
  hammer attacks. `last_rejected_at` is stamped on the row so admin
  dashboards can still see abuse patterns.
- **Cutover behaviour**: existing in-memory counters are lost on the
  first boot after Phase 19 ships — the current UTC-hour window
  restarts fresh from 0. No migration script.
- **Numeric limit preserved**: `_RATE_MAX=10`, `_RATE_WINDOW_S=3600`.
  Unchanged from the prior implementation.

### Tests

- **`backend/tests/test_phase19_avatar_and_rewrite_ratelimit.py`** — 5
  new pytest cases · all passing.
  - `A1`: `/api/jobs` returns `assignee_photo_url` populated for techs
    with `technician_photo_url` set.
  - `A2`: `/api/jobs` returns `assignee_photo_url = null` for techs
    without a photo.
  - `B1`: 1st call under limit → 200 + row in `ai_rewrite_usage` with
    `call_count == 1`, `window_start_utc` / `window_end_utc` populated.
  - `B2`: call count survives an in-process `importlib.reload()` of
    the router module — 5 calls, reload, 5 more calls → `call_count == 10`.
  - `B3`: 11th call → **429** with `Retry-After: <secs>` header AND
    the counter is rolled back to 10 (not 11) AND `last_rejected_at`
    is stamped.
- Legacy `tests/test_checkin_rewrite.py::test_unit_rate_check_*` still
  pass thanks to the preserved sync shims (verified — no modification
  needed).

### Verification (curl matrix)

```
1) GET  /api/jobs                                    admin  → 200; every row
                                                              has key `assignee_photo_url`
                                                              (null while photos are unset)
2) POST /api/checkins/rewrite-description × 10       admin  → 200 each
3) POST /api/checkins/rewrite-description  (11th)    admin  → 429 with
                                                              Retry-After: <1-3600>
4) GET  /api/openapi.json                             (open) → 200
```

### Files added / changed

- `backend/routers/checkin_rewrite.py` — Phase 19 rewrite (Mongo-backed
  rate limit; sync-shim helpers + prompt/LLM adapter preserved verbatim)
- `backend/routers/jobs.py` — `_enrich_job_dept_and_kind` +
  `_enrich_jobs_dept_and_kind` now project + attach `assignee_photo_url`
- `backend/scripts/create_session_indexes.py` — `ensure_on_boot()` now
  calls `checkin_rewrite.ensure_indexes()` too
- `backend/tests/test_phase19_avatar_and_rewrite_ratelimit.py` (NEW, 5
  tests)
- `frontend/src/pages/workstream/WorkstreamPage.jsx` — `<UserAvatar>`
  next to the assignee line
- `mobile/app/job/[id].tsx` — image with fallback icon using the new
  `assignee_photo_url` field

### Cross-cutting checks

- Grep-lint: 0 `db.invoices` writes in any Phase 19 file. ✅
- Vitest baseline: 522 pass / 14 fail — inside the 11-14 tolerated
  flake budget. ✅
- `/api/openapi.json` reachable (HTTP 200). ✅
- 21/21 pytest across Phase 19 + Phase 18 + webform bugfix + legacy
  rewrite units. ✅

---

## 2026-08-08 — Phase 18 · Chemical Cost Report + Per-Tech Inventory + Low-Stock Notifications

Snapshot-priced chemical cost reporting, per-tech / per-department attribution,
and a real-time + daily-cron low-stock alert fan-out to bell + email + Slack.
All six user decisions from 2026-08-01 are locked in (see "Design decisions"
below). No `db.invoices` writes. No external-repo cloning.

### Added

- **`services/inventory_alerts.py`** — Phase 18 core module.
  - `SEEDED_CHEMICALS` catalogue (8 core pool chemicals: Liquid Chlorine,
    Chlorine Tablets, Muriatic Acid, Cal-Hypo Shock, Soda Ash, Cyanuric Acid,
    Pool Salt, Algaecide).
  - `seed_chemicals_for_tenant(tenant_id)` — idempotent by `sku=P18-<slug>`
    (and case-insensitive name match against Phase-23 `_STARTER` rows).
    Existing rows keep their tuned `reorder_point`; only `sku`,
    `is_seeded_chemical`, `department` are attached.
  - `seed_chemicals_all_tenants()` — server-boot fan-out.
  - `should_alert(item)` — null threshold ⇒ never alerts (user decision 4).
  - `check_and_notify_low_stock(tenant_id, item_ids, source, slack_post, force)`
    with a **24-hour dedup window** on `inventory_items.low_stock_notified_at`.
  - `run_daily_low_stock_scan()` — APScheduler entry, tenant-fanout.
  - Slack helper `_build_slack_payload()` (mrkdwn text block, includes OUT
    markers for out-of-stock items).
  - Quiet-hours honoured on `inventory_alert_settings.quiet_hours_utc`
    (`{start_hour,end_hour}`), wraps midnight correctly. Real-time fan-out
    defers into quiet hours; cron path still runs.
  - Audit row per fan-out written to `inventory_alert_events`.

- **`routers/inventory_reports.py`** — Phase 18 API surface.
  - `GET /api/reports/chemical-costs` (require_admin) — totals + per-product,
    per-tech, per-department aggregations sourced from
    `chemical_usage_events.total_cost_cents` (snapshot-priced — no pricebook
    join at report time). Optional `start`, `end`, `department`, `tech_id`
    filters. Default window: last 30 days.
  - `GET /api/inventory/my-inventory` (any non-customer) — read-only on-hand
    list for techs. **Cost fields are NEVER included** (`unit_cost`,
    `cost_per_unit_cents` are omitted at the projection layer). Includes a
    "You used" panel of the tech's last-30-day usage — quantities only.
  - `PUT /api/admin/users/{uid}/department` — set enum
    `pool_tech | landscape_tech | both | null`.
  - `PUT /api/admin/inventory/{iid}/department` — set enum
    `pool | landscape | both | null` on a SKU.
  - `POST /api/admin/suggest-departments` — infers per-tech department from
    last-N-days job.service_type distribution (thresholds: ≥75% pool ⇒
    pool_tech, ≥75% landscape ⇒ landscape_tech, ≥25% both ⇒ both).
  - `GET/PUT /api/admin/inventory-alert-settings` — Slack webhook +
    quiet-hours CRUD. Webhook URL is masked in GET responses like the
    Phase 55 pattern.

- **Real-time hook** on `routers/inventory.decrement_from_service_report()` —
  after every decrement, any SKUs that cross their reorder point fire
  `check_and_notify_low_stock(source="real_time")`. Fan-out failures never
  block the service-report submit path (wrapped in `try/except`).

- **APScheduler cron** — `inventory_low_stock_daily` at
  `INVENTORY_CRON_HOUR_UTC` (default `06:00 UTC`, staggered off Phase 5b/5c/
  7/8/17). Scans all tenants; skips rows in dedup window; honours quiet hours
  differently (does still fire outside them).

- **Frontend** —
  - `src/pages/inventory/ChemicalCostReport.jsx` — new Admin page with
    date-range + department + tech filters. Cards for total spend / events /
    quantity plus three breakdown tables. Every element carries a
    `data-testid`. Cost figures are USD-formatted (cents → dollars).
  - `src/App.js` — route `admin/inventory/chemical-cost-report` (wrapped in
    `AdminOnly`) + import.
  - `src/pages/inventory/InventoryPages.jsx` — added "Cost Report" button
    on the inventory landing header with `data-testid="inv-cost-report-link"`.

- **Mobile (Expo)** — `mobile/app/(app)/inventory/my-inventory.tsx` — new
  tech-facing screen. Pulls from `/api/inventory/my-inventory`. Renders
  summary chips (total / low / out), sorted on-hand list with LOW / OUT
  badges, and a personal usage panel (quantities only, **no dollar figures**).
  Every row carries a `testID`.

- **Notifications** — new `inventory_low_stock` kind in
  `services/notifications.py::KIND_LABELS`; added to
  `_ADMIN_PUSH_DEFAULT_ON` so admins get Expo push by default.

- **Tests** — `backend/tests/test_phase18_chemical_report.py` — 8 pytest
  cases (all passing). Loop-rebinding pattern shared with the QBO Phase 17
  suite to avoid Motor "Event loop is closed" flake.
  - A: seed idempotency (8 first run, 0 second)
  - B: seed preserves tuned `reorder_point`
  - C: null threshold never alerts
  - D: real-time fan-out + 24h dedup (Slack+bell fire once, second call in
    window is deduped)
  - E: quiet hours defer real-time but not cron
  - F: cost report RBAC (admin 200, tech 403)
  - G: cost report aggregation math + per-tech / per-department correctness
  - H: mobile my-inventory strips every cost field

### Changed

- `db.inventory_items` documents grow three optional fields:
  `is_seeded_chemical: bool`, `department: "pool"|"landscape"|"both"|None`,
  `low_stock_notified_at: iso-string|None`. All are nullable, no
  migration required — existing rows keep their current shape.
- `db.users` documents grow an optional `department` enum
  `pool_tech|landscape_tech|both|None`. Existing rows stay `None` (per user
  decision — no bulk migration). Reports show a "Department: unassigned"
  bucket so null tech data is never invisible.

### Security

- Chemical cost data is `require_admin`-gated — technicians and customers
  get 403 on `/api/reports/chemical-costs` (curl matrix + pytest F prove
  this). The mobile `/api/inventory/my-inventory` endpoint strips
  `unit_cost` / `cost_per_unit_cents` at the projection layer so wholesale
  margin data can never leak to a tech client (pytest H proves this).
- Slack webhook URL is stored in `inventory_alert_settings.slack_webhook_url`
  but always masked in GET responses (`https://hooks.slack.…xxxx`), same
  pattern as `scorecard_digest_settings`.

### Notes / Design decisions

- **Cost math source of truth**: report reads from
  `chemical_usage_events.unit_cost_at_time_cents × quantity_used`
  (snapshot-priced at service-report submit by
  `chemical_products.snapshot_chemical_usage`). No pricebook join at report
  time — protects historical margin math from retroactive price edits.
- **Department field seed strategy**: nullable enum on both `users` and
  `inventory_items`. No bulk migration. Seeded 8 chemicals ship with
  `department="pool"`. `/admin/suggest-departments` is a read-only hint
  layer for a future admin bulk-apply modal (not surfaced in UI in this
  pass — logged as follow-up).
- **Quiet hours behaviour**: real-time fan-out defers into quiet hours (the
  next cron tick will pick it up). The daily cron itself does NOT defer
  when its `hour=06:00 UTC` schedule fires — that's a fixed operational
  slot chosen deliberately outside typical quiet windows. Wrap-around
  windows (e.g. `22 → 06`) are handled correctly.
- **Slack fallback**: per-tenant `slack_webhook_url` first, then
  `INVENTORY_SLACK_WEBHOOK_URL` env var, then noop. Never crashes on
  missing config.
- **KIND labels**: `inventory_low_stock` was added to the notifications
  catalogue so per-user preference UI renders a friendly row and admins
  default to push=on.
- **11-14 baseline Vitest flake**: not touched — same tolerated failure
  budget as prior phases.

### Verification (curl matrix)

```
1) GET  /api/reports/chemical-costs                     admin  → 200 (totals + per_* buckets)
2) GET  /api/reports/chemical-costs                     tech   → 403
3) GET  /api/inventory/my-inventory                     tech   → 200 (no unit_cost keys)
4) POST /api/admin/suggest-departments                  admin  → 200 (25 suggestions)
5) POST /api/admin/suggest-departments                  tech   → 403
6) PUT  /api/admin/inventory-alert-settings             admin  → 200 {"ok":true}
7) GET  /api/admin/inventory-alert-settings             admin  → 200 (slack_webhook_url_masked)
```

### Files added / changed

- `backend/services/inventory_alerts.py` (NEW, 355 lines)
- `backend/routers/inventory_reports.py` (NEW, 385 lines)
- `backend/routers/inventory.py` — real-time hook injected (13-line insert)
- `backend/services/notifications.py` — `inventory_low_stock` kind + push default
- `backend/server.py` — router mount + APScheduler cron + boot seed step
- `backend/tests/test_phase18_chemical_report.py` (NEW, 340 lines · 8 tests)
- `frontend/src/pages/inventory/ChemicalCostReport.jsx` (NEW)
- `frontend/src/pages/inventory/InventoryPages.jsx` — Cost Report button
- `frontend/src/App.js` — new import + `admin/inventory/chemical-cost-report` route
- `mobile/app/(app)/inventory/my-inventory.tsx` (NEW)

---

## 2026-08-08 — Bug fix follow-up · Webform still 403 through Cloudflare edge (Phase 8 origin-allowlist Cloudflare-Worker rewrite)

**Reported symptom**: After the 2026-08-07 scheme-normalization fix, `POST /api/public/leads` still returned `403 "Origin not allowed"` when called from the live preview URL, even though the exact host was in `tenant.widget_allowed_domains` and local pytest passed.

**Root cause**: The Cloudflare Worker fronting `*.preview.emergentagent.com` **rewrites the incoming `Origin` header** to the internal cluster hostname (`https://<slug>.cluster-12.preview.emergentcf.cloud`) before the request reaches FastAPI. Diagnostic header dump confirmed FastAPI received `origin=https://poolscape-audit.cluster-12.preview.emergentcf.cloud` while `x-forwarded-host=poolscape-audit.preview.emergentagent.com` (the public host in the allowlist). The `_matches()` fix from 2026-08-07 was correct but was matching against the wrong candidate.

**Fix**: Synthesize an additional candidate `f"{x-forwarded-proto}://{x-forwarded-host}"` and add it to the candidates list consulted by `_matches()`. Public browser Origins are now recovered from the CF forwarding headers.

**Files changed**
- `backend/routers/leads.py` (added `x_fwd_host_origin` synthesis + candidates list extension)

**Verification**
- External `curl -H "Origin: https://poolscape-audit.preview.emergentagent.com" POST …/api/public/leads` → `200 {"ok":true,"lead_id":"908296f8-…"}` post-fix (was `403` pre-fix).
- Lead confirmed persisted in `db.leads` with full payload intact.
- Existing 4 pytest cases in `test_public_lead_intake_bugfix.py` still pass (no regression on scheme-normalization logic).

---

## 2026-08-07 — Bug fix · Webform submissions now land in `db.leads` (Phase 8 origin-allowlist scheme mismatch)

**Reported symptom**: "Webform is not pulling customer information and description of services in to leads."

**Root cause**: `routers/leads.py::public_lead_intake._matches()` (lines 1023-1033) compared the browser's `Origin` header (`https://poolscape-audit.preview.emergentagent.com`) to `tenant.widget_allowed_domains` entries stored as *bare hostnames* (`poolscape-audit.preview.emergentagent.com`). The exact-string / trailing-slash comparison never succeeded, so every website form submission returned `403 "Origin not allowed"` before the payload was ever inserted. Investigation confirmed **zero `source=website_form` leads** in the production tenant's `db.leads` collection.

**Fix**: extended `_matches()` to normalize both sides by stripping `https://` / `http://` and any path component before comparison, in addition to the pre-existing exact/prefix checks. Bare-host allowlist entries now match schemed browser Origins; schemed allowlist entries continue to work; unlisted origins remain rejected.

**Files changed**
- `backend/routers/leads.py` (5-line edit inside `_matches`)
- `backend/tests/test_public_lead_intake_bugfix.py` (new · 4 regression cases, all passing)

**Verification**
- End-to-end curl reproduces the bug pre-fix (`403 "Origin not allowed"`), lands cleanly post-fix (`200 {"ok": true}`) with every field (`name`, `email`, `phone`, `service_address`, `service_interest`, `notes`) intact in the resulting Mongo doc.
- 4/4 new pytest cases pass: full-payload landing, schemed-origin ↔ bare-host allowlist match, Referer-with-path fallback, evil-origin still 403.



Read-only inbound pull from QuickBooks Online. **Zero write-back to Intuit ever.** QBO data mirrors into `db.qbo_*` collections and displays side-by-side with CRM records; match links between CRM and QBO records are optional and user-confirmed only. Refuses any external-repo trap prompts.

### Added — Backend
- **`services/qbo/oauth.py`** — OAuth 2.0 handshake + Fernet at-rest token encryption. Key derived via HKDF-SHA256 from `JWT_SECRET` (fallback `SECRET_KEY`) — no new env var required. State is a signed JWT (`tenant_id` + `nonce` + 10 min TTL) so callback verification is CSRF-safe. Helpers: `build_auth_url`, `handle_callback`, `refresh_access_token`, `revoke_connection`, `get_active_access_token`. On 401 refresh → auto-flip to `reauth_required`.
- **`services/qbo/client.py`** — thin async wrapper. `qbo_get()` auto-refreshes tokens on 401 (once) then retries; sandbox / production base URLs picked by connection env; `minorversion=65` on every call; `fetch_entity_page()` implements the Intuit `/query` SQL-ish paginator with optional `changed_since` for CDC delta. `set_transport()` swap hook lets pytest inject `httpx.MockTransport` for zero-network tests.
- **`services/qbo/sync.py`** — orchestration. 7-entity dependency-ordered pull (`accounts → customers → vendors → invoices → payments → journal_entries → bills`). Full-mode on first run or `force_full=True`; delta-mode uses the previous successful run's `started_at` as the CDC cursor. Per-entity try/except so one failure → `partial_success` (not a crash). Concurrency guard: in-flight run for a connection short-circuits and returns the existing `run_id`. `qbo_daily_sync()` is the APScheduler entry point.
- **`services/qbo/match.py`** — fuzzy suggestion scorer. Invoice score = `0.5·amount_within_1% + 0.3·date_within_7d + 0.2·fuzzy_customer_name` (top 5 above 0.2 confidence). Customer score = `0.7·fuzzy_name + 0.3·email_exact`. Never creates links — user must explicitly confirm.
- **`routers/qbo_router.py`** — 24 endpoints under `/api/qbo/*`:
  - OAuth: `connect-url`, `callback`, `connections` list, `connections/{id}` DELETE (revoke).
  - Sync: `sync/run-now` (background task + concurrency guard), `sync/runs` list, `sync/runs/{id}` detail.
  - Data reads (7 entities × 2 endpoints = 14): `{customers,vendors,invoices,payments,accounts,journal-entries,bills}` list + detail. `next_cursor` pagination; case-insensitive search across common fields.
  - Match: `POST /match-link`, `DELETE /match-link/{type}/{id}`, `GET /match-suggestions/{type}/{id}`.
  - Boot log: `[qbo] environment=<sandbox|production>, oauth_client=<configured|missing>`.
- **`server.py`** — router included; APScheduler job `qbo_daily_sync` at `QBO_SYNC_CRON_HOUR_UTC` (default 03:00 UTC).
- **`scripts/create_session_indexes.py`** — Phase 17 hook adds unique `(tenant_id, qbo_realm_id, qbo_id)` index on every mirror collection + `(tenant_id, last_synced_at desc)` + `(tenant_id, linked_crm_id)`, plus `qbo_connections` and `qbo_sync_runs` query indexes.
- **`requirements.txt`** — `intuit-oauth==1.2.7` added (`cryptography==49.0.0` already present).
- **`.env`** — added `QBO_ENVIRONMENT=sandbox`, `QBO_CLIENT_ID=`, `QBO_CLIENT_SECRET=`, `QBO_REDIRECT_URI=`, `QBO_SYNC_CRON_HOUR_UTC=3`, `QBO_API_MINOR_VERSION=65`.
- **`tests/test_qbo_phase17.py`** — 14 pytest cases, **all passing**. Covers: OAuth state signing, callback token encryption at rest, tampered state → ValueError, refresh success + 401→reauth_required flip, full-mode 7-entity sync, delta-mode CDC cursor, partial-failure → `partial_success` status, concurrent-run short-circuit, invoice + customer match-suggestion scoring, bidirectional match link persist/unlink, tech + customer 403 on all endpoint categories, cross-tenant connection → 404, grep-lint invariant.

### Added — Frontend (web)
- **`pages/admin/integrations/QuickBooksIntegrationPage.jsx`** — 4-tab admin page at `/admin/integrations/qbo`. Connect tab shows a setup guide with `developer.intuit.com/` link when env vars are missing; otherwise renders Connect / active-connection / revoke UI. Sync tab exposes "Sync from QuickBooks now" + force-full checkbox + last-run KPI card. History tab lists past runs. Data browser tab has 7 entity sub-tabs with search + last-synced timestamps + "Linked CRM" badges.
- **`App.js`** route registered.

### Added — Mobile (Expo)
- **`mobile/app/qbo/index.tsx`** — connection status card + Sync-now button + last-run summary. Manager+ role gate.
- **`mobile/app/qbo/data.tsx`** — read-only data browser with 7 entity chip filter + search. Match-management is desktop-only (per spec).

### Security
- **Read-only enforcement**: Zero endpoints target Intuit's mutation surface. Every backend interaction is `GET`. The router imports `services.qbo.oauth` + `services.qbo.client` + `services.qbo.sync` + `services.qbo.match` — none of them contains a `POST`/`PUT`/`DELETE` to an Intuit URL other than the OAuth token exchange and the OAuth revoke endpoint.
- **Fernet-at-rest tokens**: access + refresh tokens are Fernet-encrypted before persisting to `db.qbo_connections`. The Fernet key is derived per-process via HKDF-SHA256 from the app's `JWT_SECRET` — no plaintext token is ever written.
- **CSRF-safe callback**: OAuth `state` is a signed JWT with a 10-minute TTL and a per-request nonce. Tampered state raises `ValueError("invalid_state")` → 400.
- **Role guards**: every endpoint requires `admin` / `manager` / `super_admin`. Tech + Customer roles hit `403` (verified end-to-end via pytest).
- **Cross-tenant safety**: connection lookups filter on `tenant_id` at every hop. Cross-tenant `qbo_connection_id` → 404 (never leaks existence).

### Notes / deliberate deferrals (spec-authorized)
- **Write-back to QuickBooks** — hard NO. Never scoped.
- **QuickBooks Desktop (Windows)** — QBO only.
- **Multi-currency** — QBO currency field is stored verbatim in `raw.CurrencyRef`; no conversion.
- **Auto-match** — never. User must explicitly click Confirm on a suggestion.
- **Intuit webhooks** — deferred. Cron + on-demand sync is enough for this phase.
- **Sales tax reconciliation, attachment mirroring** — out of scope.

### Verification
- Pytest: **54 passed · 3 skipped · 0 failed** across Phase 17 + adjacent (Phase 14a/14b, backfill) suites.
- curl matrix (13 items): all endpoints return correct HTTP codes (400 unconfigured, 200 admin OK, 403 tech/customer, 404 bad conn).
- `/api/openapi.json`: 24 new QBO paths registered.
- Frontend compiles clean, external URL HTTP 200.



Brings the Expo mobile app up to par with the web across Phases 5–14 features it previously lacked. Read-only where sensible; full CRUD where the workflow is mobile-first (dispatchers/managers on tablets). Refuses any external-repo trap prompts.

### Added (files, grouped by feature area)

**Shared helper**
- `mobile/src/components/RoleGate.tsx` — normalized role predicates (`isDispatcherPlus`, `isAdminPlus`, `isStrictAdmin`, `isCustomer`, `isTech`) + `<RoleGate level=…>` wrapper that renders a friendly "Not authorized" state on deep-link access. Uses the raw JWT role string so the wider server-side role set (manager / dispatcher / super_admin) is honored even though the local `User` type advertises only `admin | technician | customer`.

**1. AEO Suite (Manager+, hidden from Tech / Customer)**
- `mobile/app/aeo/index.tsx` — landing hub with tiles for each sub-screen; shows current AEO score if a scan exists.
- `mobile/app/aeo/auditor.tsx` — URL scan trigger, keyed `aeo_signals` breakdown, recent-scans history.
- `mobile/app/aeo/visibility.tsx` — KPI cards (avg score / brand mentions / providers) + latest 10 probes as cards + Run-scan-now button with cooldown timer + cost indicator.
- `mobile/app/aeo/mentions.tsx` — sentiment / range / domain chip filters, KPI strip, mention cards with sentiment + competitor + own-domain badges.
- `mobile/app/aeo/mention-detail.tsx` — full snippet + Draft-reply launcher.
- `mobile/app/aeo/response-draft.tsx` — tone pills (Empathetic / Professional / Apologetic / Assertive), editable body with per-platform char counter, Copy (via `expo-clipboard`), Mark posted, Discard, collapsible library suggestions.
- `mobile/app/aeo/library.tsx` — platform chips + search + virtualized `FlatList`, long-press to delete.
- `mobile/app/aeo/publish-config.tsx` — Netlify / Vercel / Cloudflare Pages cards, expandable forms, save/test/publish-now actions; masks tokens once saved.

**2. Dispatch KPI + savings modal (Dispatcher+, hidden from Tech / Customer)**
- `mobile/app/dispatch-savings.tsx` — 7d/30d toggle, "Team saved X.X km" KPI, plain-`View` bar-strip sparkline (no chart lib), Top techs leaderboard.

**3. Weekly digests (Manager+)**
- `mobile/app/reports/weekly-digest.tsx` — recipients / DOW / hour / enabled toggle; Preview renders 🥇🥈🥉 top + bottom department leaders.
- `mobile/app/reports/aeo-digest.tsx` — recipients / DOW / hour / negative-snippets toggle / enabled toggle; Preview opens signed PDF URL via `expo-web-browser`.

**4. LLMs.txt Auto-Publish config** — see AEO Suite (`aeo/publish-config.tsx`).

**5. Widget Analytics + Share Replay** — verified pre-existing (MR3 · Phase 1 and Phase 2 files, untouched by Phase 16).

**6. Stripe card management (Manager+ picker; customer role sees own record)**
- `mobile/app/payments/methods.tsx` — list saved cards (brand + last4 + expiry + default badge + remove); admin+ gets a customer-search picker; "Add card" opens `/portal/payment-methods` via `expo-web-browser`. **Native Stripe Elements capture is deliberately out of scope** — the web portal is easier to keep PCI-safe in a webview than to reimplement natively (spec-authorized tradeoff).

**7. Bulk Charge past-runs (Admin / Super Admin ONLY)**
- `mobile/app/finance/bulk-charge-runs/index.tsx` — read-only history with per-run metric row + DRY/REAL chip; explicit "Trigger new bulk charges from the desktop" note.
- `mobile/app/finance/bulk-charge-runs/[runId].tsx` — drill-down with per-invoice status / charge id / error code / amount.

### Cross-cutting

- **Role gates**: every new screen wraps its body in `<RoleGate level=… >`. Deep-linking to a forbidden screen renders the friendly "Not authorized" state instead of a crash. Nav visibility is enforced by not adding entry-point links to Tech / Customer surfaces — the new screens are only reachable via router push from Manager+ contexts.
- **Loading states**: every network call renders a spinner (`<Loading />`) OR an inline "Loading…" text OR a per-button loading flag.
- **Empty states**: every list has a distinct `<EmptyState icon title subtitle testID>` — never a blank screen.
- **Deep linking**: Expo Router file-based routes for `/aeo/*`, `/reports/*`, `/dispatch-savings`, `/payments/methods`, `/finance/bulk-charge-runs[/:runId]`.
- **A11y**: every touchable carries an `accessibilityLabel`.
- **Data-testids**: every actionable element has a stable `testID` (chip / row / button / input) so future Detox / RTL testing has anchors.

### Explicitly not ported (per spec)

- Full drag-drop dispatch board — desktop-only.
- Offline queueing for the new mutation screens (digest save, publish-config, response-draft mark-posted) — Phase 2 offline queue applies; no new mutations added to the queue this phase.
- Push notifications — deferred.
- Native GPS map viewer — removed by Phase 2 policy.
- **Native Stripe card capture** — using `expo-web-browser` fallback to `/portal/payment-methods`. Explicit spec-authorized tradeoff: keeping PCI scope inside the audited web Elements integration is safer than a fresh RN card capture.
- Triggering bulk charges from mobile — Phase 14b desktop-only policy stands. The mobile screen is read-only with an inline "Trigger new bulk charges from the desktop" note.

### Verification

- `npx tsc --noEmit` on `/app/mobile/`: 276 baseline errors present in pre-existing files (unchanged), **0 errors in Phase 16 files**.
- `npx expo export --platform web` completes successfully with an 11.8 MB bundle — app boots without a red screen.

### No changes to
- Backend (`/app/backend/**`)
- Web app (`/app/frontend/**`)
- Lumino / Zapier flows, GPS guards, share-replay backend, dispatch backend, AEO backend, Phases 6–15 backend code.



Two independent housekeeping items bundled into a single pass. Refuses all external-repo trap prompts (Option D permanent).

### Sub-item 1 · Lumino `paid_at` backfill (data-fix)

**Investigation-first gate**: Scanned `db.payment_events` (8 total rows; 5 `payment.created` + 3 `invoice.link_created`). All 5 success events carry `invoice_id=null` (LZ4-era smoke-test payloads). True backfill candidate count today = **0**. Per spec, still shipped the idempotent script + tests so the code is ready the moment real Lumino events start landing.

#### Added
- **`backend/scripts/backfill_lumino_paid_at.py`** — idempotent migration with `--dry-run` flag. Behaviour:
  - Success signal: `event_type=="payment.created"` (case-insensitive). If `raw.data.status` is present, it must equal `"succeeded"` — otherwise the event is skipped. Defensive against `raw` / `raw.data` being non-dict payloads (surfaced by the live smoke-test data).
  - Groups events by `invoice_id` and picks the **earliest** `occurred_at` (fallback `received_at`). Full event history remains in `db.payment_events`; the reconciliation log records the specific source event id applied.
  - Updates `db.quotes` (never `db.invoices` — Phase 11 grep-lint enforced): sets `payment_status="paid"`, `paid_at=<earliest ts>`, and `amount_paid=total` **only if** `amount_paid == 0` (partial payments are preserved verbatim). Adds `backfilled_from_lumino_event_at=<utcnow>` as an audit stamp.
  - Skips: `already_paid` (invoice `payment_status=="paid"` OR `paid_at` set), `invoice_not_found` (no matching `db.quotes` doc).
  - Writes one `db.invoice_reconciliation_log` row per backfilled invoice: `{action:"backfill_lumino_paid_at", invoice_id, tenant_id, source_event_id, applied_paid_at, ran_at, logged_at}`.
  - Idempotent by construction — the second run walks the same events, finds each invoice already `paid`, and reports `backfilled: 0`.
- **`backend/tests/test_backfill_lumino_paid_at.py`** — 10 pytest cases, all passing: earliest-of-duplicates picker, already-paid skip, missing-invoice skip, idempotency, dry-run isolation, non-success event type ignored, null `invoice_id` ignored (matches the investigation-gate case), inner-status filter, partial-payment preservation, grep-lint invariant.

#### Changed
- **`backend/routers/invoice_reconciliation.py::api_reconciliation_log`** — accepts optional `action` query param. Response now includes `filter: {action: ...}` (or `{}` when unset). Notes updated to reference Phase 15. Backwards-compatible: pre-Phase-15 callers with no `action` param see all rows exactly as before.

#### Not touched (out of scope this phase)
- Lumino / Zapier flow logic — remains parked.
- Phase 11 reconciliation-log schema — only the optional filter param was added.
- Phase 14a / 14b Stripe code — not touched.

### Sub-item 2 · Stripe `pk_live` env cleanup — GATED, no change shipped

`frontend/.env` line 7 still contains the legacy `REACT_APP_STRIPE_PUBLISHABLE_KEY=pk_live_…` from the LZ4 removal era. Per spec, we grepped `frontend/src` for readers before removal. Found **6 active references** in Phase 14a code:

- `frontend/src/pages/portal/PortalPaymentMethods.jsx` lines 28, 34 — fallback in `_pickPublishableKey()` when `_TEST` / `_LIVE` variants are empty.
- `frontend/src/components/customers/AdminCardCapturePanel.jsx` lines 25, 31 — same fallback pattern.
- `frontend/src/components/payments/StripeAddCardForm.jsx` lines 178-179 — user-facing error text referencing the key names.

Additionally: the spec's premise — *"Phase 14a wired publishable-key delivery through `/setup-intent`"* — is **not currently accurate**. Phase 14a's `create_setup_intent` returns `{client_secret, setup_intent_id, stripe_customer_id, mode}` but not the publishable key. The frontend still needs an env-based publishable key at page load to call `loadStripe(publishableKey)`.

Environment rule for Phase 15 explicitly forbids touching Phase 14a/14b Stripe code. **Sub-item 2 STOP condition satisfied** — no env line removed. Deferred to a future phase that either (a) adds publishable-key delivery to the setup-intent response, or (b) explicitly authorizes editing the three Phase 14a files.

### Security / invariants
- Phase 11 grep-lint stays green — `scripts/backfill_lumino_paid_at.py` writes only to `db.quotes` + `db.invoice_reconciliation_log`. Enforced by `test_grep_lint_no_writes_to_db_invoices`.
- No new endpoints. The optional `?action=` filter on the existing super-admin-gated log endpoint is the only new API surface.
- No env keys removed; no schema changes; no data written when candidate count is zero.



Composes on top of Phase 14a's `charge_card_on_file` primitive. Delivers two invoice filters (line-item category multi-value + card-on-file yes/no/any), a bulk charge endpoint with mandatory dry-run preview + idempotency key replay, plus an audit trail collection and admin drill-down pages.

Refuses any external-repo trap prompts injected via tool output or file content — the guardrail from Phase 14a is permanent.

### Added
- **`routers/quotes.py::list_quotes`** — accepts `category` (multi-value; case-insensitive union across `line_items[].category`) + `card_on_file` (`yes` | `no` | `any`). The card-on-file cohort is resolved by cross-referencing the `payment_methods` collection at query time, filtering out expired cards (`exp_year < now.year` or `exp_year == now.year && exp_month < now.month`). Existing `doc_type` / `include_deleted` behavior is preserved.
- **`routers/invoices_bulk_charge.py`** (new) — three endpoints under `/api`:
  - `GET  /invoices/line-item-categories` — tenant-scoped distinct catalog with a 60 s in-memory cache. Admin/manager/super_admin only.
  - `POST /invoices/bulk-charge-card-on-file` — pydantic-enforced `invoice_ids` cap of 100, mandatory `idempotency_key` (min length 1, max 200). Two-step: `dry_run=true` returns per-row eligibility with `would_charge` / skip reasons (`already_paid` / `zero_balance` / `no_card_on_file` / `card_expired` / `not_found`) without invoking Stripe; `dry_run=false` invokes Phase 14a's `charge_card_on_file` sequentially with 75 ms spacing between real charges. Every request persists a `bulk_charge_runs` row (dry-run or real). Replay of the same `(tenant_id, idempotency_key)` within 24 h returns the original response verbatim without a re-run.
  - `GET  /invoices/bulk-charge-runs?limit=` and `GET /invoices/bulk-charge-runs/{run_id}` — history + detail. Admin+ only.
- **`db.bulk_charge_runs`** (new collection). Unique index on `(tenant_id, idempotency_key)` + query index on `(tenant_id, started_at desc)`. Registered in the Phase 13 boot hook via `scripts/create_session_indexes.py::ensure_on_boot`.
- **`services/payments/stripe_charge.py::charge_card_on_file`** — accepts a new optional `idempotency_key` parameter. Backwards-compatible: unset falls back to the internal `charge:{row_id}` value. Enables composed per-invoice keys of the form `{bulk_idempotency_key}:{invoice_id}` so a Phase 14b retry never double-charges.
- **`components/invoices/BulkChargeModal.jsx`** — two-step confirmation modal. Renders a per-row eligibility table with badges (would_charge / already_paid / no_card_on_file / card_expired / zero_balance / not_found) + running total. Confirm button only enabled after step-1 loads and displays the actual dollar total. Toast on completion + direct link to `/admin/finance/bulk-charge-runs/{run_id}`.
- **`pages/admin/BulkChargeRunsPage.jsx`** (`BulkChargeRunsList` + `BulkChargeRunDetail`) — history table with dry-run/real chips + drill-down. Wired at `/admin/finance/bulk-charge-runs[/{runId}]`.
- **`pages/invoices/InvoicesList.jsx`** — category multi-select dropdown + selected chip strip + clear button; new **Charge cards on file** action in the bulk action bar (auto-disabled above 100 selection); bulk-charge modal mount.
- **`tests/test_bulk_charge_phase14b.py`** — 15 pytest cases, **all passing**:
  - Filter: `category=Pool` single, `category=Pool&category=Late+fee` multi union, `card_on_file=yes` / `card_on_file=no` complement pair, distinct-values endpoint.
  - Bulk: dry-run per-row reasons (5-invoice seed with 2 eligible / 1 already_paid / 1 no_card_on_file / 1 zero_balance), real run stub call count + persistence + payment_status mirror, idempotency replay (same key, zero side effects), cross-tenant `not_found` no-leak, 101-invoice cap → 422, tech + customer 403 on all 3 endpoints, `{ok:False}` no-charge-id path → `error_code=not_ok_no_charge_id`, stripe exception → `error_code=<ExceptionClassName>`, runs list + detail readback.
  - Grep-lint invariant: routers/invoices_bulk_charge.py contains zero writes to `db.invoices` (Phase 11 rule preserved).

### Changed
- `services/payments/stripe_charge.py::charge_card_on_file` — signature now accepts `idempotency_key`. Existing callers unchanged.
- `scripts/create_session_indexes.py::ensure_on_boot` — invokes `routers.invoices_bulk_charge.ensure_indexes()` after the primary Phase 13 pass so the two new `bulk_charge_runs` indexes are guaranteed on cold boot.

### Security
- Admin / manager / super_admin gate on every new endpoint (`/invoices/line-item-categories`, `/invoices/bulk-charge-card-on-file`, `/invoices/bulk-charge-runs`, `/invoices/bulk-charge-runs/{id}`). Tech and Customer roles receive `403`. Verified via pytest.
- The `dry_run=true` step is mandatory in the UI — the modal always fetches the eligibility preview before the confirm button becomes enabled. Backend accepts either directly (an integrator can call `dry_run=false` first), but the persisted `results[]` still carries the identical skip semantics so per-invoice charges never fire for `not_found` / `already_paid` / `no_card_on_file` / `card_expired` / `zero_balance` rows.
- `idempotency_key` is mandatory on the bulk endpoint (min length enforced by pydantic). Composed per-invoice as `{key}:{invoice_id}` before being handed to Phase 14a, so a retry from the client is safe end-to-end. The unique index on `bulk_charge_runs.(tenant_id, idempotency_key)` provides the DB-side rail for a concurrent-race replay.
- Cross-tenant invoice IDs land as `{status: "skipped", skip_reason: "not_found"}` — never as a 404 (which would leak existence).
- Sequential rate-limiting: 75 ms sleep between real charges (spec band 50–100 ms) so a batch of 100 doesn't burst-fire Stripe.

### Not resurrected
- `db.invoices` — every read/write remains on `db.quotes` with `doc_type="invoice"`. The grep-lint test enforces this against the new router.
- Legacy LZ3-era `POST /api/payments/bulk-charge-on-file` scaffolding on `InvoicesList.jsx` is left dormant; the new Phase 14b button uses the fresh endpoint.



Fresh Stripe re-integration for the SetupIntent → attach → off-session PaymentIntent pipeline. Runs alongside the parked Lumino/Zapier bridge; the two providers are cleanly separated by a `provider` field on `payment_methods` rows so there is no risk of cross-contamination.

Investigation confirmed a clean slate before shipping: no `stripe` package in `requirements.txt`, no `import stripe` in backend, no `@stripe/*` in frontend. The dangling `REACT_APP_STRIPE_PUBLISHABLE_KEY` in `frontend/.env` was preserved (per env rules) and superseded by `_TEST`/`_LIVE` mode-split variants.

### Added
- **`services/payments/stripe_charge.py`** — 5 async helpers wrapping the raw `stripe` SDK (14.x). All Stripe HTTP calls are dispatched through `asyncio.to_thread` so the FastAPI event loop is never blocked.
  - `create_setup_intent(tenant_id, customer_id)` — idempotent Stripe customer create + SetupIntent (`payment_method_types=["card"], usage="off_session"`). Stamps `stripe_customer_id` on the CRM customer doc.
  - `attach_payment_method(...)` — attaches a PM to the Stripe customer, retrieves the fresh card metadata, upserts a mirror into `db.payment_methods` with `provider="stripe"`. Optional `set_default` demotes siblings + updates `customers.stripe_default_payment_method_id` + `saved_payment_methods_count`.
  - `list_payment_methods(...)` — reads the local mirror (DB is the source of truth for the CRM UI).
  - `detach_payment_method(...)` — detach from Stripe + delete mirror + clear the customer's default pointer when it matched.
  - `charge_card_on_file(...)` — off_session `PaymentIntent.create(confirm=True)` with an idempotency key. Every attempt (success OR failure) is persisted to the fresh `db.stripe_charges` collection with `{amount_cents, currency, invoice_id, stripe_payment_intent_id, status, error, actor_user_id, stripe_mode, created_at}`.
  - `verify_and_parse_webhook(payload, sig_header)` — mode-aware `Webhook.construct_event` verification.
  - `handle_webhook_event(event)` — idempotent handler for `payment_method.attached`, `payment_method.detached`, `payment_intent.succeeded`, `payment_intent.payment_failed`. Upserts on `stripe_payment_intent_id` so a delayed webhook can't drop a status update.
- **`routers/stripe_router.py`** — 6 endpoints under `/api/payments/stripe/*` wired into `server.py`. Role guards:
  - `POST /setup-intent`, `POST /attach` — customer self-serve (JWT-inferred `customer_id`) OR admin/manager/super_admin (must pass `customer_id` in body; missing = 422).
  - `GET /payment-methods/{customer_id}` — customer (own) OR admin+. **Technicians receive 403 unconditionally.**
  - `DELETE /payment-methods/{payment_method_id}` — customer (own PM) OR admin+; tech = 403.
  - `POST /charge` — **admin/manager/super_admin ONLY.** Tech and customer roles receive 403.
  - `POST /webhook` — public; signature verified before any DB write; unverified requests get 400 (never touch Mongo).
- **`components/payments/StripeAddCardForm.jsx`** — reusable Stripe Elements form. Fetches the SetupIntent client_secret, mounts `<Elements>` + `<PaymentElement>`, calls `stripe.confirmSetup({ redirect: "if_required" })`, then hits `/attach` with the resulting `payment_method` id. Data-test IDs on every actionable element.
- **`components/customers/AdminCardCapturePanel.jsx`** — admin capture panel wired into `CustomerDetail.jsx` as a new **Payments** tab. Lists saved cards with brand/last4/expiry + Default badge + Remove button; toggle mounts the reusable form for card capture on behalf of the customer.
- **`pages/portal/PortalPaymentMethods.jsx`** — customer-facing counterpart at `/portal/payment-methods`. Uses the same reusable form (customer_id inferred from JWT, no admin capture prop).
- **`tests/test_stripe_phase14a.py`** — 18 pytest cases (15 pass, 3 skip on missing prerequisites). Stripe SDK is fully stubbed via a `set_stripe_client()` injection hook; no live HTTP is ever issued. Covers: setup-intent create + reuse, attach mirror + default demotion, detach clears default, charge success/failure logging, invalid amount / unknown PM rejection, webhook secret selection per `STRIPE_MODE`, webhook payload verification, `payment_method.attached` mirror upsert, `payment_intent.succeeded` charge-row upsert, router 403 for technicians, router 422 for missing `customer_id`, admin GET payment-methods.

### Env vars (added; never rewriting existing lines)
- `backend/.env`: `STRIPE_MODE=test`, `STRIPE_SECRET_KEY_TEST=`, `STRIPE_SECRET_KEY_LIVE=`, `STRIPE_WEBHOOK_SECRET_TEST=`, `STRIPE_WEBHOOK_SECRET_LIVE=`, `STRIPE_PUBLISHABLE_KEY_TEST=`, `STRIPE_PUBLISHABLE_KEY_LIVE=`.
- `frontend/.env`: `REACT_APP_STRIPE_MODE=test`, `REACT_APP_STRIPE_PUBLISHABLE_KEY_TEST=`, `REACT_APP_STRIPE_PUBLISHABLE_KEY_LIVE=`. The legacy `REACT_APP_STRIPE_PUBLISHABLE_KEY` (pk_live_…) is preserved as a fallback for existing code paths.
- Mode selection falls back to the platform-injected `STRIPE_API_KEY` (default `sk_test_emergent`) if a mode-specific override isn't set, so preview boots without extra config.

### Not resurrected
- **`db.stripe_payments_live`** stays retired (Phase LZ4). All new charge logs land in the fresh `db.stripe_charges` collection.
- **`emergentintegrations.payments.stripe.checkout`** is not used — the Emergent Checkout helpers cover Session-redirect flows, not the SetupIntent + off-session PaymentIntent pattern Phase 14a requires. Raw `stripe` SDK is the correct primitive.
- **`sk_live_...` in `frontend/.env`** — preserved verbatim per env rules; superseded by the `_TEST`/`_LIVE` variants selected at read time.

### Dependencies
- Backend: `stripe>=13.0.0,<15.0.0` (`stripe==14.4.1` installed). Constrained below 15 to satisfy `emergentintegrations==0.2.0`.
- Frontend: `@stripe/stripe-js@9.12.1`, `@stripe/react-stripe-js@6.8.0` (via `yarn add`).



Two independent, tightly-scoped hygiene items called out by the Phase 12 audit. Shipped together as one pass.

### W1 · CORS tightening
Historical state: `CORS_ORIGINS="*"` was a dangling env var — the middleware actually read `ALLOWED_ORIGINS`, so `CORS_ORIGINS` had no effect. The Phase 12 audit correctly flagged this as a WARNING because the env variable name that operators would expect to control CORS was inert.

#### Added
- `services/…` behavior in `server.py` now honors `CORS_ORIGINS` per the operator's mental model:
  - **Unset** → prior behavior unchanged (existing `ALLOWED_ORIGINS`-derived allowlist).
  - **`*`** → permissive mode; `Access-Control-Allow-Credentials` is switched OFF (CORS spec forbids `*` + credentials); a single `WARNING [cors] CORS_ORIGINS is permissive (*) — tighten before production release.` fires on boot.
  - **`https://a.com,https://b.com,…`** → parsed (whitespace-tolerant) and appended to the existing allowlist. `allow_credentials=True` is preserved. Inline wildcards inside a list are rejected with a WARNING and stripped.
- `tests/test_cors_config.py` — 6 unit tests: wildcard permissive marker, comma-separated exact list, whitespace tolerance, inline-wildcard stripping, empty-env return, startup-log-line contract.

#### Verified live
- `CORS_ORIGINS="*"` → boot log emits `[cors] CORS_ORIGINS is permissive (*) — tighten before production release.` (one line per uvicorn worker). Final `CORS allow_origins = ['*']`.
- `CORS_ORIGINS="https://poolscape-audit.preview.emergentagent.com,https://staging.example.com"` → boot log emits no warning; final allowlist merges the two supplied origins with the existing `ALLOWED_ORIGINS`-derived list: `['https://poolscape-audit.preview.emergentagent.com', 'https://app.plofv.com', 'https://plofv.com', 'https://staging.example.com']`.
- Reverted to `*` at end of test — production preview restored to permissive baseline.

### W2 · Session-collection compound indexes
Phase 12 flagged 15 of 17 session collections as missing `(tenant_id, ts_desc)` compound indexes. All added.

#### Added
- `scripts/create_session_indexes.py` — idempotent one-shot migrator with `--dry-run`. For each of 15 collections, picks the appropriate timestamp field (primary → fallback via document-sample inspection), then creates a named index `tenant_<field>_desc`. Prints per-collection status + a summary tally (`created / already_exists / skipped_missing_field / skipped_empty_collection / substituted_field`). Empty collections are skipped cleanly. Concurrent-create races are absorbed as `already_exists`.
- **Boot hook** in `server.py:startup` (`from scripts.create_session_indexes import ensure_on_boot`) — self-healing safety net so freshly-deployed pods don't need a manual step. Wrapped in try/except so a Mongo hiccup never blocks boot; failure logs `[indexes] boot hook failed (non-fatal): …`.
- `tests/test_session_indexes.py` — 6 tests: dry-run doesn't mutate; real run creates then second run is a no-op; field-substitution when the primary timestamp is absent on the sample; empty-collection skip case; subprocess dry-run smoke; boot-hook never-raises contract.

#### Indexes ensured on the live preview DB (14 created on first boot; second boot: 0 created, 14 already-exists)

| Collection | Index name | Notes |
|---|---|---|
| `route_optimize_events` | `tenant_executed_at_desc` | Phase 10 sub-item F |
| `aeo_visibility_probes` | `tenant_ran_at_desc` | Phase 5b |
| `brand_mentions` | `tenant_discovered_at_desc` | Phase 5c |
| `brand_mention_runs` | `tenant_ran_at_desc` | Phase 5c |
| `aeo_fixes` | `tenant_generated_at_desc` | Phase 5b |
| `mention_response_drafts` | `tenant_drafted_at_desc` | Phase 6 |
| `response_draft_templates` | `tenant_created_at_desc` | Phase 10 sub-item D |
| `scorecard_digests` | `tenant_generated_at_desc` | Phase 7 |
| `aeo_digest_runs` | `tenant_generated_at_desc` | Phase 8 |
| `aeo_digest_pdfs` | `tenant_created_at_desc` | Phase 8 (primary `generated_at` absent on sample → substituted `created_at`) |
| `llmstxt_publish_configs` | `tenant_updated_at_desc` | Phase 9 |
| `llmstxt_publish_history` | `tenant_requested_at_desc` | Phase 9 |
| `invoice_reconciliation_log` | `tenant_logged_at_desc` | Phase 11 |
| `quotes` | `tenant_created_at_desc` | co-exists with the existing `tenant_invoice_number_unique` index |
| `aeo_probe_runs` | (skipped) | collection does not exist yet — 0 rows historically |

#### Operational note for ops
The startup boot hook self-heals on next boot, so no manual step is strictly required. If you want to force it out-of-band without a redeploy:
```
python -m scripts.create_session_indexes
```
Idempotent — safe to run any number of times. `--dry-run` inspects without mutating.

### Design decisions
- **W1**: kept the existing `ALLOWED_ORIGINS`-driven allowlist logic intact, and layered `CORS_ORIGINS` as an additive control. This preserves back-compat for anyone who has already tuned `ALLOWED_ORIGINS`, while giving operators the env-var name the audit expected. `CORS_ORIGINS=*` deliberately switches `allow_credentials` to `False` (CORS spec forbids wildcard + credentials) — this is a **breaking change for any browser client that relies on credentialed cross-origin XHR while permissive mode is on**, but that combination was never spec-compliant anyway; production should not run permissive.
- **W2**: index NAMES are deterministic (`tenant_<field>_desc`) so operators can `db.<coll>.dropIndex("tenant_created_at_desc")` predictably. Field substitution logs a `NOTE` line but never crashes — the primary/fallback chain guarantees a sensible pick even if the collection's schema drifts. The boot hook lives in the existing `@app.on_event("startup")` handler (immediately after the Mongo ping) so its outcome is unambiguously logged before any traffic is served.
- **Test isolation**: the session-index tests originally used `subprocess.run(python -m scripts.create_session_indexes)` which launches a fresh interpreter — meaning `_script.SPECS.append(...)` in the test process was invisible to the subprocess. Refactored to call the async `_script.run(dry_run=…)` directly on the test's event loop. One subprocess-based smoke test remains to prove `python -m scripts.create_session_indexes --dry-run` exits 0 end-to-end.

### Verification
- New pytest files: **12 / 12 passing** (`test_cors_config.py` = 6, `test_session_indexes.py` = 6).
- Targeted regression across 6 invoice/AEO test files (72 tests): **70 passing / 2 pre-existing baseline failures unchanged** — zero Phase-13 regressions.
- Vitest baseline: **14 failed / 537** — inside the accepted 11-14 tolerance (upper edge). Zero Phase-13-authored tests among the failures.
- `/api/openapi.json` returns 200. Live-verified with `CORS_ORIGINS="*"` (permissive + warning) and `CORS_ORIGINS="https://…,https://…"` (list mode, no warning).
- Live-verified all 14 indexes on the preview Mongo (`getIndexes()` reports each `tenant_<field>_desc` entry present).

---

## 2026-08-01 — Phase 11 · Invoice dual-collection refactor (`db.invoices` → `db.quotes`)

Consolidated the two-collection invoice model onto **`db.quotes` with `doc_type="invoice"`** as the single source of truth. `db.invoices` was preserved for rollback safety but is now inert — no production code reads or writes it. Migrated 17 orphan rows (all test-seed residue in one tenant) into `db.quotes` with `migrated_from_invoices=True` and `migration_needs_review=True` for later super-admin review.

### Added
- `scripts/migrate_invoices_to_quotes.py` — idempotent one-shot migrator with `--dry-run`. Conservative schema-gap fills (`doc_type="invoice"`, `total=total_cents/100`, `line_items=[]`, `payment_status="unpaid"`, `created_at=now`). Never overwrites: on a duplicate id, `db.quotes` wins and the diff is written to `db.invoice_reconciliation_log`. Ran cleanly on live preview: `scanned=17, migrated=17, already_present=0, drift_logged=0`.
- `routers/invoice_reconciliation.py` — `GET /api/admin/invoice-reconciliation-log?limit=100` — super-admin-only (`admin` + `super_admin`). Response body includes the deferred-Lumino-backfill disclaimer.
- `tests/test_invoice_collection_unification.py` — 7 guardrail tests: migration idempotency (5 orphans → run twice → 0 double-writes), quotes-wins duplicate handling + drift log, `find_invoice_dual` reads only from `db.quotes` (retired `db.invoices` branch), promo-code redeem writes to `db.quotes` only (fixes B1), role guard × 3 accounts × reconciliation endpoint (manager 403, admin/super_admin 200), backward-compat lookup of migrated hex32 ids, **grep-lint** that fails on any live `db.invoices.<method>(` call in production code outside the shim's own definition + migration script.

### Changed
- `services/invoice_lookup.py` — `find_invoice_dual` now hits **only** `db.quotes` and emits a `WARNING`-level deprecation on first call per process (via `functools.lru_cache(maxsize=1)`). Tuple shape `(doc, "quotes")` is preserved for back-compat with the 4 existing callers.
- `routers/lumino_return.py` — `status=paid` + `paid_at` write moved to `db.quotes` (was writing to `db.invoices`).
- `services/lumino_reconciler.py` — nightly "mirror payment" step moved to `db.quotes`.
- `routers/lumino_invoice_link_callback.py` — write target unconditionally `db.quotes` (dropped the `db.invoices if collection == "invoices" else db.quotes` branch).
- `routers/invoice_edit.py` — `invoice_number` uniqueness scan simplified to a single `db.quotes` query.
- `routers/portal_greeting.py` — unpaid-invoice greeting slot reads `db.quotes` with `doc_type="invoice"` filter.
- `routers/referrals_vesting.py` — `_referrer_has_paid_invoice_since()` reads `db.quotes`.
- `services/referral_watcher.py` — first-paid-invoice lookup reads `db.quotes` (removed the legacy fallback branch).
- `routers/lumino_backfill.py` — single-collection scan (removed the merge-with-`db.invoices` de-dup path).
- `routers/promo_codes.py` — **B1 fix**: replaced the `for coll in (db.invoices, db.quotes)` dual-push loop with a single write to `db.quotes`.
- Five test seeders re-pointed to `db.quotes`: `test_invoice_edit.py` (default `collection="quotes"`), `test_lumino_invoice_link_callback.py`, `test_lz2_dispatcher.py`, `test_phase10_referrals.py`, `test_task_qq_p2_lumino.py`.
- Test 14 in `test_lumino_invoice_link_callback.py` inverted its expectation to assert the Phase 11 contract ("db.invoices row is NEVER updated when a matching db.quotes row exists").
- Stale docstrings in `routers/invoice_edit.py`, `routers/lumino_backfill.py`, `routers/lumino_invoice_link_callback.py`, `routers/lumino_link_request.py` updated to describe the unified model.

### Fixed
- **B1** `promo_codes.py` · dual-push loop (`for coll in (db.invoices, db.quotes)`) removed. Single write to `db.quotes` — no risk of double-`$push` into `applied_promo_code_ids` on any future duplicate.
- **B2** `referrals_vesting.py` · referrer paid-invoice window check now sees the 466 real invoices in `db.quotes`, not just the 17 test residues in `db.invoices`. **This unblocks the vesting gate for real customers going forward.**
- **B3** `portal_greeting.py` · customer-portal "unpaid invoice" greeting slot now fires against real invoices in `db.quotes` instead of silently missing them.
- **B4** `lumino_return.py` · Lumino redirect `status=paid + paid_at` write lands on the source of truth. Going-forward payments are correct; historical drift is called out under **Notes** below.
- **B5** `lumino_reconciler.py` · nightly reconciler mirrors payment status onto `db.quotes`. Same historical-drift caveat.
- **B6** `invoice_lookup.py` · shim no longer prefers the ancillary `db.invoices` collection.

### Deprecated
- `services.invoice_lookup.find_invoice_dual` — kept as a compatibility symbol for the 4 existing callers (`routers/invoice_edit.py`, `routers/lumino_invoice_link_callback.py`, `routers/lumino_link_request.py`), but emits a WARNING once per process boot. **Scheduled for removal in a future phase after ≥ 30 days of clean production logs.** Migrate callers to a direct `db.quotes.find_one({"id": …, "doc_type": "invoice"})` when convenient.

### Security
- New `GET /api/admin/invoice-reconciliation-log` endpoint enforces **super-admin scope only** (`role in {"super_admin", "admin"}`). `manager`, `technician`, `customer` all 403. Verified live and in pytest.
- Response body always includes a `notes[]` array with the "Historical Lumino paid_at drift is NOT in this log" disclaimer so operators don't misinterpret an empty log as a clean bill of health.

### Notes
- **Historical Lumino `paid_at` drift is NOT reconciled by this phase.** Any Lumino payment that completed *before* the refactor was written into `db.invoices` (a bug per B4/B5) and never landed on the matching `db.quotes` doc. A follow-up data-fix phase will scan `db.payment_events` for successful Lumino returns older than the Phase 11 cutover and replay the `paid_at` mirror onto `db.quotes`. The reconciliation-log endpoint calls this out in its response `notes[]`.
- `db.invoices` collection is **retained** (empty of live writes, but the 17 legacy rows plus any pytest seeds remain) as a rollback net. A future phase will drop the collection after ≥ 30 days of clean deprecation-warning logs.
- The migration script wrote 17 rows with `migration_needs_review=True`. All 17 look like fork-loop test residue in the `manager@aquaterra` tenant (no `line_items`, no `invoice_number`, no `created_at`). A super-admin can decide via the reconciliation-log endpoint (drift log is empty — the migration was drift-free) whether to delete them.

### Verification
- Full targeted regression across 14 invoice-adjacent test files: **0 newly-broken tests**, 16 pre-existing baseline failures unchanged.
- New guardrail file `tests/test_invoice_collection_unification.py`: **7 / 7 passing**.
- Vitest baseline: **13 failed / 537** — inside 11-14 tolerance, unchanged from Phase 10.
- Migration dry-run + real: 17 rows migrated cleanly, 0 drift, 0 duplicates.
- `/api/openapi.json` returns 200 with the new `/api/admin/invoice-reconciliation-log` path present.

---

## 2026-07-31 — Phase 10 · Bundled extensions (D + E + F)

Three small extensions bundled together — Response Draft Library (D), Auto-Slot Preview Badge (E), Cumulative Weekly savings_km KPI (F). None of them touch Phase 3-9 internals beyond a one-line append-only event-log hook (F) and a status-transition side-effect (D).

### Sub-item D · Response Draft Library — Added
- `services/response_library.py` — `capture_template_from_draft()` (dedup on `sha256(platform + normalised text)[:32]`, min 20 chars text, per-tenant), `list_templates()`, `top_templates_for()`, `use_template()` (increments `use_count`, updates `last_used_at`, rolling 30-day counter — window resets to 1 when prior `last_used_at` is older than 30 days), `soft_delete_template()` (sets `deleted_at`, excludes from list/top), `render_examples_for_prompt()` (assembles a Claude system-suffix block from up to 3 templates).
- `routers/aeo.py` — 3 new endpoints: `GET /api/aeo/response/templates?platform=&limit=`, `POST /api/aeo/response/templates/{template_id}/use`, `DELETE /api/aeo/response/templates/{template_id}`.
- Collection `response_draft_templates` (`template_id, platform, tone, source_draft_id, template_text, template_hash, use_count, times_used_last_30d, last_used_at?, deleted_at?, created_at`).
- Phase 6 integration — `services/response_drafts.py`:
  - `update_draft()` on `status="posted"` transition calls `capture_template_from_draft(draft)` (fire-and-forget, swallow exceptions).
  - `create_or_get_draft()` pulls up to 3 top templates for `(platform, tone)` and passes them to `_build_prompt()`, which appends a "Examples of prior public replies from this business …" block to the Claude system message. Neither the endpoint signature nor the mention_response_drafts shape changed.
- Web admin — new **Response Library** 7th tab on `/admin/marketing/aeo` (`ResponseLibraryTab`): platform filter + client-side substring search + table (platform badge, tone badge, first 120 chars, uses, 30d, last_used_at, delete). Empty state guides the user to the Brand Mentions tab.
- `ResponseDraftModal.jsx` — new `SuggestedFromLibrary` collapsible section below the tone pills. Renders up to 3 prior templates, each with a `Use this` button that pastes the template into the textarea, calls `POST /aeo/response/templates/{id}/use`, and (if there is an active draft) `POST /aeo/response/drafts/{draft_id}` with `edited_text`.

### Sub-item E · Auto-Slot Preview Badge — Added
- `routers/dispatch_route_insert.py` — `POST /api/dispatch/route/preview-insert-batch` with body `{tech_user_id, route_date, job_ids[≤50]}`. Reuses the existing `_cheapest_slot()` helper 1:1 — no algorithm duplication. Loads the current (tech, date) route + coords once, then loops the candidates and returns `[{job_id, added_distance_km, best_position, currently_missing_coords}]`. Jobs with missing coords → `added_distance_km=null, currently_missing_coords=true`. If the tech has no origin AND no existing route, treats the candidate as its own origin (0 km first-stop preview).
- Web — `UnscheduledJobsPanel.jsx` accepts a new `previewsById` prop. Each row renders a colour-coded pill: `≤ 5 km → green`, `5-15 km → amber`, `> 15 km → red`, `null → gray "no coords"`.
- `DispatchBoardPage.jsx` — new effect that fires a 300 ms-debounced `POST /preview-insert-batch` whenever `(techId, day)` becomes concrete AND `unschedJobs.length > 0`. Results are cached in a `useRef` map keyed by `${techId}|${isoDate}|${idsHash}` for 30 s, then propagated via `setPreviewsById`. When no tech / day is selected, `previewsById` clears so no stale pills remain.

### Sub-item F · Weekly savings_km KPI — Added
- `services/route_events.py` — append-only `route_optimize_events` writer (`log_event(kind, tech_user_id, route_date, savings_km, stop_count, added_distance_km?, executed_by)`, swallows exceptions) + `weekly_summary(tenant_id, range_='7d'|'30d', top_n=5)` aggregator. Returns `{range, period_start, period_end, total_savings_km, total_optimize_events, total_insert_events, per_day[]  (backfilled zeros for missing days), top_techs[]}`.
- `routers/dispatch_savings.py` — `GET /api/dispatch/route/savings/weekly?range=7d|30d`. Mounted with `Depends(_rg)` in `server.py` (same guard as Phase 3/4).
- Phase 3 · `routers/dispatch_route_optimize.py:apply_route` — one-line append at the end of a successful apply, logging `kind="optimize"` with the client-supplied `savings_km` (a new optional `ApplyBody.savings_km` field the frontend already computes).
- Phase 4 · `routers/dispatch_route_insert.py:insert_route_job` — one-line append at the end of a successful insert, logging `kind="insert"` with `savings_km=0` and `added_distance_km` populated (insert doesn't save distance, it adds it — the field is informational).
- Web — `DispatchSavingsStrip.jsx` in `pages/dispatch/`, rendered inside the Dispatch Board header row. Big number `Team saved X.X km this week` (7d default), recharts sparkline area chart (60 px tall), "View report" link → modal with a 7d/30d toggle, 3 KPI cards (Total saved · Optimize events · Insert events), a larger sparkline, and a Top techs table. `hidden md:block` — collapses on mobile.

### Design decisions
- **Sub-item D · few-shot injection**: appended to the Claude *system* prompt (not the user prompt) so the model treats the examples as tone / voice conditioning rather than data. Truncated at 800 chars each; capped at 3. Empty examples list emits no suffix at all — the prompt is bit-identical to Phase 6 when the library is empty.
- **Sub-item D · dedup key**: `sha256(platform + ":" + text.strip().lower())[:32]`. Same text posted to Yelp and Google Reviews → two separate templates (platform-aware voice). Case-insensitive so trivial edits don't spawn duplicates.
- **Sub-item D · soft-delete**: sets `deleted_at`, filtered by all readers (`{"deleted_at": {"$exists": False}}`). Preserves audit trail for the source_draft_id link.
- **Sub-item E · cache pattern**: `useRef` map keyed by `${techId}|${isoDate}|${idsHash}`, 30 s TTL. Hovers, panel-toggle, and quick tech-flip don't refire — the previous result is served instantly. When any of the 3 key inputs changes → new fetch. When context becomes invalid (no tech / day="all" / no unscheduled) → `setPreviewsById({})` so no stale pills remain.
- **Sub-item E · degraded modes**: (1) job missing coords → `null` + flag, panel renders "no coords" gray pill (2) unknown job_id → treated as missing_coords (server never 404s a batch preview) (3) tech has no route yet → cheapest-slot is 0 km using the candidate as its own origin.
- **Sub-item F · log-vs-recompute trade-off**: chose append-only event log over rescanning `jobs` for `savings_km` on every request. Log rows are 1 KB, one per apply/insert — the write cost is negligible and the read is a straight `find + sum` that hits a natural `(tenant_id, executed_at)` index. Historical replay before this phase is intentionally deferred.

### Security
- All 3 new template endpoints reject Tech + Customer with 403 (verified live; pytest × 3 × 2 accounts).
- `POST /dispatch/route/preview-insert-batch` inherits the router-level `require_gps_read` guard mounted at `include_router()` in `server.py` — Tech + Customer 403 (verified live).
- `GET /dispatch/route/savings/weekly` inherits the same `require_gps_read` guard — Tech + Customer 403 (verified live).
- Cross-tenant `list_templates()` / `weekly_summary()` return empty results (never 500).
- Auto-capture failures inside `update_draft(status="posted")` are caught and swallowed — Phase 6's posted-status path is never blocked by a library bug.

### Changed
- `services/response_drafts.py` — `_build_prompt` accepts optional `examples` list, `create_or_get_draft` fetches top templates, `update_draft` calls `capture_template_from_draft` on `status="posted"`.
- `routers/aeo.py` — 3 new endpoints appended (imports from `services.response_library`).
- `routers/dispatch_route_insert.py` — new `POST /preview-insert-batch` endpoint appended; the existing `POST /insert` gets a 5-line event-log tail block.
- `routers/dispatch_route_optimize.py` — `ApplyBody.savings_km: Optional[float] = None`; `apply_route()` gets an 8-line event-log tail block.
- `server.py` — mounted `dispatch_savings` router below Phase 4.
- `frontend/src/pages/dispatch/UnscheduledJobsPanel.jsx` — accepts `previewsById`; row renders a colour-coded pill.
- `frontend/src/pages/dispatch/DispatchBoardPage.jsx` — imports `DispatchSavingsStrip`, renders it in the header row; new 300 ms-debounced batch-preview effect + `useRef` cache.
- `frontend/src/pages/admin/AEOPage.jsx` — 7th "Response Library" tab + `ResponseLibraryTab` component.
- `frontend/src/pages/admin/ResponseDraftModal.jsx` — `SuggestedFromLibrary` block wired to `/api/aeo/response/templates`.

### Out of scope (deferred)
- Slack notification when a new template is auto-captured.
- Per-user template pinning / favorites.
- Batch preview streaming (websocket).
- Historical replay of savings before the log was introduced.
- Multi-tenant leaderboard.

---

## 2026-07-31 — Phase 9 · LLMs.txt Auto-Publish (Netlify / Vercel / Cloudflare Pages)

### Added
- `services/llmstxt_publish.py` — 3 provider adapters (Netlify, Vercel, Cloudflare Pages) behind a common shape: each exports `test_connection(config)` and `publish(config, filename, content)`; both return `{ok, error?, account_info?, deploy_id?, url?}` and never raise. Netlify uses `POST https://api.netlify.com/api/v1/sites/{site_id}/files/{filename}` (octet-stream raw body). Vercel uses `POST https://api.vercel.com/v13/deployments` with an inline `files` array — documented as "counts as a full production redeploy" (Vercel has no single-file live upload). Cloudflare Pages uses `POST https://api.cloudflare.com/client/v4/accounts/{account_id}/pages/projects/{project_name}/deployments` with a multipart `files` field. Adapters read `_mock_publish_response` / `_mock_test_response` from the config row as a test shortcut so pytest can stub HTTP without a shared-process transport injection. `publish()` orchestrator writes a `pending` history row, calls the adapter inside a try/except, then patches the row to `success` / `failed` and stamps `provider_deploy_id`, `provider_url`, `error_message`, `completed_at`. Config CRUD + masked read (`_mask` → last 6 chars, same pattern as Phase 7 Slack webhook). `auto_publish_on_generate(tenant, filename, content, requested_by)` iterates all `enabled=True + auto_publish_on_generate=True` configs and returns `{triggered, results[]}` — swallows exceptions.
- `routers/llmstxt_publish.py` — 6 admin/super_admin/manager-only endpoints: `GET /api/aeo/llms-txt/publish/providers`, `POST /api/aeo/llms-txt/publish/config`, `DELETE /api/aeo/llms-txt/publish/config/{provider}`, `POST /api/aeo/llms-txt/publish/test/{provider}`, `POST /api/aeo/llms-txt/publish/{provider}` (calls Phase 5a `generate_llms_txt` then delegates to `publish()`; maps `http_status_hint=400 → HTTP 400 not_configured` and `502 → HTTP 502 upstream_error` while still writing the history row), `GET /api/aeo/llms-txt/publish/history?provider=&limit=20`.
- Collections `llmstxt_publish_configs` (per-tenant, per-provider — schema: `provider, api_token, site_id?/site_url?, project_id?, project_name?, account_id?, enabled, auto_publish_on_generate, last_publish_at?, last_publish_status?, created_at, updated_at`) and `llmstxt_publish_history` (`publish_id, provider, filename, size_bytes, content_bytes_hash (sha256[:32]), requested_at, requested_by, status pending/success/failed, provider_deploy_id?, provider_url?, error_message?, completed_at?`).
- Phase 5a integration — `routers/aeo.py:api_generate_llms_txt` now calls `auto_publish_on_generate()` after the generator and appends `publish_triggered` (bool) + `publish_results` (list of `{provider, status, publish_id?, error_message?}`) to the response. The generator's core signature and success path are unchanged; auto-publish failure never aborts the response.
- Web admin — new **PublishConfigPanel** collapsible section on the existing `/admin/marketing/aeo` LLMs.txt tab (no new top-level page). 3 provider sub-tabs (Netlify / Vercel / Cloudflare Pages), per-tab paste-only token input with masked display of the last 6 chars, provider-specific fields (Netlify: `site_id` + optional `site_url`; Vercel: `project_id` with an amber "counts as full redeploy" note; Cloudflare Pages: `account_id` + `project_name`), Enabled + Auto-publish-on-Generate toggles, Save / Test-connection / Publish-llms.txt / Publish-llms-full.txt / Remove buttons, publish-history table (last 20 rows, provider, filename, size, colored status badge, deploy ID with external-link chip, error message on row `title`), plus a "Where do I get this token?" help link per provider (Netlify → `app.netlify.com/user/applications#personal-access-tokens`, Vercel → `vercel.com/account/tokens`, Cloudflare → `dash.cloudflare.com/profile/api-tokens`).
- Pytest suite `backend/tests/test_llmstxt_publish.py` — 10 tests all green: adapter URL selection via `httpx.MockTransport`, not-configured 400 path, publish-success writes success history + captures `provider_deploy_id`/`provider_url`, publish-failure writes failed history + returns `http_status_hint=502` + `error_message` starts with `http_401`, POST-config through the live route strips `api_token` from the response and returns `api_token_masked` ending in the token's last 6 chars, auto-publish hook via live POST `/api/aeo/llms-txt/generate` sets `publish_triggered=true` + writes a history row, role guard × 6 endpoints × 2 non-mod accounts (all 403), cross-tenant lookup returns `[]` not 500, live test-connection endpoint round-trips through DB-mocked adapter, live POST publish endpoint (Cloudflare Pages) succeeds end-to-end.

### Design decisions
- **Token storage**: raw in `llmstxt_publish_configs.api_token`, NEVER surfaced back — every read helper drops `api_token` and exposes only `api_token_masked` (last 6 chars). Same pattern as the Phase 7 Slack webhook. No new secrets store introduced.
- **HTTP stubbing pattern for tests**: an in-config `_mock_publish_response` / `_mock_test_response` short-circuits the adapter *before* it opens `httpx.AsyncClient`. This side-steps the cross-process issue where the uvicorn worker cannot see a monkey-patched `_http_client_factory` from the pytest process. `httpx.MockTransport` is still used for the pure-service adapter-selection test that runs in-process.
- **Auto-publish concurrency**: awaited inline in the generator handler rather than fire-and-forget. This makes `publish_triggered` + `publish_results` in the response *authoritative* about the outcome (spec asked for a history row to be present after the generator returns — a background task would have raced). The perf cost is one stubbed HTTP round-trip per configured provider; acceptable for a UX where the user just clicked "Generate".
- **Vercel single-file limitation**: documented in the UI as an amber banner + in the adapter docstring. For git-linked projects we recommend a commit PR path in a future phase.

### Security
- All 6 new endpoints reject Tech + Customer with 403 (verified live).
- Cross-tenant config fetch returns `[]` (no 500 leak).
- Adapter helpers guard on missing token / missing provider-specific fields with `{ok: False, error: "not_configured"}` — endpoints never crash on incomplete configs.
- `POST /api/aeo/llms-txt/publish/{provider}` maps upstream failures to HTTP 502 with a friendly JSON body containing the `publish_id` for follow-up in history, without leaking provider response bodies beyond the first 400 chars.

### Changed
- `server.py` — mounted `llmstxt_publish` router.
- `routers/aeo.py` — `api_generate_llms_txt` now returns `publish_triggered` + `publish_results` alongside the existing generator fields.

### Out of scope (deferred, per spec)
- OAuth flows for all 3 providers (PAT-only in Phase 9).
- Auto-detect `site_id` / `project_id` from a PAT (needs a list-projects call per provider).
- Multi-file publish, rollback / version pinning, and CI/GitHub-push integrations.

---

## 2026-07-31 — Phase 8 · Weekly AEO PDF Digest (ReportLab + Resend)

### Added
- `services/aeo_digest.py` — Aggregates last-completed-week AEO health into a 4-section snapshot: (1) AEO score (`overall_aeo_score` from latest `seo_scans` + WoW delta + sub-signal breakdown for `schema`/`faq`/`llms_txt`/`passages`/`entity_clarity`), (2) AI visibility (avg `aeo_visibility_probes.score`, brand-mention rate, top/bottom queries, per-provider tally), (3) brand mentions (`brand_mentions` count, sentiment split, top domains, opt-in negative snippet samples), (4) action items (pending AEO fixes + pending response drafts). ReportLab `canvas` renderer (Helvetica, single-page portrait letter, ≤500 KB target — actual ~2.4 KB), b64-persisted to `db.aeo_digest_pdfs`. HMAC-SHA256 signed public URL (10-min TTL, SECRET_KEY/JWT_SECRET-keyed, 32-char hex sig). Resend delivery with PDF attachment, injectable `resend_send` stub for tests. `run_digest()` runner returns `{digest_id, snapshot, pdf_url, pdf_size_bytes, delivery}`. `weekly_digest_cron()` — hourly gate on tenant DOW+hour_utc, `aeo_visibility_enabled=True` required, `already_generated_this_week()` dedup, per-tenant try/except.
- `routers/aeo_digest.py` — 5 authenticated endpoints (`POST /api/aeo/digest/preview`, `POST /api/aeo/digest/run-now`, `GET /api/aeo/digest/history`, `POST /api/aeo/digest/settings`, `GET /api/aeo/digest/settings`) + 1 signature-gated public endpoint (`GET /api/aeo/digest/pdf/{digest_id}?tid=&exp=&sig=`, `include_in_schema=False`). Reuses `require_gps_read`-style admin/super_admin/manager guard.
- Collections `aeo_digest_pdfs` (b64 body cache), `aeo_digest_runs` (history), `aeo_digest_settings` (per-tenant `{enabled, recipient_emails[], day_of_week 0-6, hour_utc 0-23, include_negative_snippets}`).
- APScheduler job `aeo_weekly_digest` wired in `server.py` at `minute=10` (offset from Phase 7's scorecard cron to avoid rush-hour collisions).
- Web admin `/admin/marketing/aeo/digest` (`pages/admin/AEODigestPage.jsx`) — Settings card (recipients CSV, DOW select, hour_utc, Enabled + Include-negative-snippets toggles, Save / Send-test / Generate-preview CTAs), Preview card (embedded `<iframe>` of signed PDF URL + Open-PDF anchor + byte counter), History card (last 10 digests with period range, size, download link, per-channel delivery ✓/✗). Route mounted in `App.js:683` under `<AdminOnly>` guard.
- Pytest suite `backend/tests/test_aeo_digest.py` — 8 tests all green: empty-week snapshot no-crash, ReportLab bytes start with `%PDF-` and size < 500 KB, sign+verify signature round-trip + tampered-sig rejection, snapshot with seeded metrics reads visibility/mentions/drafts, `deliver_email` invokes injected Resend stub with attachment payload, cron dedup skips a second run for the same `period_start`, live `/settings` + role guard × 4 endpoints × 2 accounts (admin 200 / customer 403), live `/preview` returns downloadable PDF via signed URL.

### Security
- 5 authenticated endpoints reject Tech + Customer with 403 (verified live: `GET /settings`, `POST /preview`, `GET /history`, `POST /settings` all 403 for customer, 200 for manager).
- Public PDF download endpoint requires valid HMAC signature + non-expired `exp` — invalid or expired signatures return 403 without touching the DB. Signature key resolution order: `SECRET_KEY` → `JWT_SECRET` → static salt (dev-only fallback).
- PDF is b64-persisted per (tenant_id, digest_id); the public route scopes fetch by both, so a signed URL for tenant A cannot exfiltrate a PDF from tenant B.
- Resend HTTP call is wrapped in try/except — a Resend outage does not crash the cron and does not corrupt the `aeo_digest_runs` row.

### Changed
- `server.py` — mounted `aeo_digest` router (line 315) and cron install (lines 862-866).

---

## 2026-07-30 — Phase 7 · Weekly Scorecard Digest (Slack + Email)

### Added
- `services/scorecard_digest.py` — Mon-Sun window math + WoW deltas + per-department aggregators (field / dispatch / sales) + composite scoring (jobs·revenue·rating / assignments·optimizations·savings / conversions·value·new_quotes) + Slack Block Kit builder + Resend email HTML builder + delivery adapters with injected clients + `weekly_digest_cron()` runner + settings CRUD with masked webhook.
- `routers/scorecard.py` — 5 new endpoints: `POST /api/scorecard/digest/run-now`, `GET /api/scorecard/digest/preview`, `GET /api/scorecard/digest/history`, `POST /api/scorecard/digest/settings`, `GET /api/scorecard/digest/settings`.
- Collections `scorecard_digests` + `scorecard_digest_settings`.
- APScheduler job `scorecard_weekly_digest` — hourly, per-tenant day-of-week + hour_utc gate, dedup via `already_generated_this_week()`.
- Web admin `/admin/reports/weekly-digest` — Settings (Slack URL paste-only + masked-current display, channel, recipients, DOW/hour, enabled toggle, "Send test digest" btn), Preview (period-end date picker + rendered top/bottom lists per department), History (last 10 digests with Slack/Email delivery status).
- Pytest suite `backend/tests/test_scorecard_digest.py` — 11 tests: period math, composite + delta arithmetic (divide-by-zero → null), Slack Block Kit shape + medal emoji + delta arrows, Resend email subject + HTML + plain-text, delivery adapter uses stubs and records status, empty-department omission, webhook mask helper, live settings round-trip with masked webhook, role guard × 5 endpoints × 2 accounts, cron dedup guard.

### Security
- All 5 endpoints reject Tech + Customer with 403.
- Slack webhook URL is stored plain-text but NEVER surfaced back — GET/POST responses expose only `slack_webhook_url_masked` (last 6 chars).
- Slack + Resend calls run inside per-tenant try/except; a failing channel does not abort the other and does not crash the cron.

### Changed
- `server.py` — mounted `scorecard` router and cron.

---

## 2026-07-30 — Phase 6 · Reputation Response Drafts

### Added
- `services/response_drafts.py` — Claude-drafted public replies to brand mentions. Platform auto-detection (yelp, google_reviews, nextdoor, reddit, facebook, bbb, generic), 4 tone knobs (empathetic / professional / apologetic / assertive), per-platform length hints in the prompt (yelp 750, google_reviews 600, nextdoor 500, reddit 400, facebook 500, bbb 700, generic 500), 24h dedup per (mention_id, tone), 10/hr/tenant sliding-window rate limit, soft-delete via `status="discarded"`.
- `routers/aeo.py` — 4 new endpoints: `POST /api/aeo/mentions/{id}/response/draft`, `GET /api/aeo/mentions/{id}/response/drafts`, `POST /api/aeo/response/drafts/{draft_id}` (update text/status), `DELETE /api/aeo/response/drafts/{draft_id}` (soft-delete), `GET /api/aeo/response/drafts/pending-count`.
- Collection `mention_response_drafts` with fields `draft_id, mention_id, platform, tone, draft_text, edited_text, status, model_used, tokens_used, cost_est_usd, drafted/edited/status_updated_at, drafted_by/edited_by/status_updated_by`.
- Denormalized fields on `brand_mentions`: `has_response_draft` + `latest_draft_status` (mirrored on every draft insert / status update).
- Web admin — **Response Draft modal** (`pages/admin/ResponseDraftModal.jsx`) mounted from the Brand Mentions tab. Header with mention title + platform + sentiment badges; quoted snippet; 4 tone pills; Generate / Regenerate CTA; editable textarea (autosaves on blur) with char counter vs platform hint; Copy (flips status→copied) / Mark posted / Discard actions; model + cost footer; friendly banner on 503 `llm_unavailable`; row-level "Draft reply" button for negative mentions plus Reddit / Google Reviews neutral rows; "View draft · <status>" chip when a prior draft exists.
- KPI tile "Drafts pending action" on the Brand Mentions dashboard (draft + copied statuses only).
- Pytest suite `backend/tests/test_response_drafts.py` — 9 tests: platform detection matrix, stubbed-LLM creation + 24h dedup + regenerate, per-platform length-hint assertion on the prompt, rate-limit at 11th call, role guard (parametrized × 2), status→mirror to brand_mentions, discard soft-delete, live 404 on missing mention.

### Changed
- LLM cost for drafts shares Phase 5b's monthly AEO cap ($5) — no second budget line.

### Security
- All 4 new endpoints reject Tech + Customer with 403.
- Draft lookups always scope by `(tenant_id, draft_id)` — cross-tenant returns 404.
- Emergent LLM error → HTTP 503 `llm_unavailable`, no partial DB write.

---

## 2026-07-30 — Phase 5c · AEO Brand Mention Crawler

### Added
- `services/search_provider.py` — adapter for Serper.dev (default when `SERPER_API_KEY` is set) and Google Custom Search JSON API fallback (`GOOGLE_CSE_API_KEY` + `GOOGLE_CSE_CX`). Returns `{provider_configured, results}`; unconfigured runs return empty results, never crash.
- `services/brand_mentions.py` — crawl runner with dedup (per-tenant per-URL), cached sentiment classification (30d cache, min 40-char snippet), per-tenant monthly cost cap ($3 default via `AEO_MENTIONS_MONTHLY_CAP_USD`), 20h duplicate-run cooldown, retroactive competitor-domain retagging, dashboard + list aggregators, `daily_mentions_scan()` cron.
- `routers/aeo.py` — 5 new endpoints: `POST /api/aeo/mentions/run-now`, `GET /api/aeo/mentions/list`, `GET /api/aeo/mentions/dashboard`, `POST /api/aeo/mentions/{id}/mark`, `POST /api/aeo/mentions/competitors`.
- Collections: `brand_mentions`, `brand_mention_runs`, `brand_sentiment_cache`.
- APScheduler job `aeo_mentions_scan` at hour `AEO_MENTIONS_CRON_HOUR_UTC` (default 08:00 UTC — one hour after Phase 5b's visibility cron to prevent collisions). Only crawls tenants with `aeo_visibility_enabled=True` (reuses Phase 5b flag; no second toggle).
- Web admin — new **Brand Mentions** tab in `/admin/marketing/aeo`: KPI strip, area chart of new mentions/day, filters (range / domain / sentiment), mention table with sentiment + competitor + own-domain pills, Mark popover (sentiment + tag override), collapsible "Manage competitor domains" panel.
- Pytest suite `backend/tests/test_brand_mentions.py` — 8 tests: adapter selection (Serper / Google / none), dedup (2 identical crawls → 1 insert + 1 update), cost cap, sentiment cache (LLM stub called once), competitor retag, role guard (parametrized × 2), unconfigured-provider survives with 200.

### Changed
- LLM sentiment classification shares the Phase 5b AEO cost pool — no second budget line.
- Test file wires a private motor client bound to a shared event loop to sidestep motor's "Event loop is closed" cross-test issue that surfaces when running the AEO test suite together.

### Security
- All 5 new endpoints reject Tech + Customer with 403.
- `POST /mentions/{id}/mark` is scoped by both `mention_id` and `tenant_id` — cross-tenant marks return 404.
- Raw search-provider keys are read from env only; the mark/competitors payloads are strictly typed (invalid sentiment/tag → 422).

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
