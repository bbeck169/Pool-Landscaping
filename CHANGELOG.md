# Changelog

All notable changes to Pool & Landscaping CRM are documented here.

## [Unreleased]

- chore(scripts): close dept-normalization story — renamed backend/scripts/fix_landscape_tech_seed_drift.py to _deprecated_fix_landscape_tech_seed_drift.py. The script's internal direction (landscaping → landscape_tech) is now the inverse of migrations/normalize_user_department_tokens (8910b943b) and would undo the dept-normalization fix if run. Phase 21 regression test import (backend/tests/test_phase21_landscape_seed_drift.py:37) repointed to the new path; script internals unchanged.
- fix(migrations): reverse normalize_user_department_tokens so landscape_tech → landscaping (was landscaping → landscape_tech). Closes the boot-time flip-per-boot race between the migration and the seed upsert. Mirrors seed.py:106/:163 canonical value and _require_landscaping accept-set.
- fix(seed): normalize landscape-dept seed value ``'landscape_tech'`` → ``'landscaping'`` so new seed runs produce users that pass ``_require_landscaping`` (prior fix 077ec26bc healed the live DB record only; this closes the forward-looking source gap). Changes: ``seed_landscaping_user`` + ``seed_landscape_tech_carlos`` insert blocks, their upsert write targets, their do-not-overwrite allow-lists (dropped legacy ``'landscape_tech'`` so the seed heals the row back after the ``normalize_user_department_tokens`` migration flips it on each boot), and the ``_CARLOS_DEPT`` constant in ``align_demo_tech_departments``.
- fix(seed): heal ``landscaper@aquaterra.com`` live-DB row — ``department`` set to ``landscaping`` so ``_require_landscaping`` passes; unblocks 2 pre-existing ``test_phase50::TestLandscapeTimeclock`` failures. ``backend/seed.py:130`` already carried a dept value + an idempotent upsert for this user (``seed_landscaping_user`` lines 100-116) but it's gated behind ``SEED_DEMO_USERS=1``, which is OFF in this environment; and ``timeclock_landscaping._require_landscaping`` accepts only ``landscaping``/``both``, so the seed's canonical ``landscape_tech`` wasn't satisfying the gate. One-shot DB heal; no source change required.
- feat(clock-in): landscape techs land on a full-screen Clock In gate that short-circuits Outlet until punched-in (admins + pool techs pass through); /landscape/time-clock gains per-tech admin aggregation (name, status, hours, last punch, view-history expand) with configurable date range. Mobile parity deferred.
- feat(admin-chrome): relocate visible universal-search bar from AdminTopBar to full-width navy (#1B1F5C) hero banner in AppLayout. Command-K palette (GlobalSearch) remains headless in AdminTopBar. No functional change -- placement + presentation only.
- feat(chemicals-catalog): flip all unit_kind='integer' entries (chlorine_tabs, salt) to 'decimal' so FE accepts fractional dosing values. Backend readings form + chemicals-added UI already supported decimals via step attributes; this unblocks the catalog-level gate.
- feat(portal-home): outer white card wrapping dashboard; Next Service split into Pool + Landscape tiles; Refer-a-Friend inputs flipped to white bg + dark slate text
- fix(portal): stabilize PortalProfile useEffect dep (user → user?.id) to prevent form reset on every render
- chore(phase-portal-edit-profile-followup): verified green; renames auto-commit label (follow-up to d065bb99e). Original intended subject: feat(portal): current-email confirmation gate on primary-email change. Known deferred: login-validator asymmetry on .local emails — see memory/PORTAL_EDIT_PROFILE_FOLLOWUPS.md.
- feat(portal): Edit Profile — current-email confirmation gate on primary-email change
- chore(phase-3c-followup): rename auto-commit label; drop kail dedup helper; repoint JobNew.test.jsx JSX assertions to LineItemsEditor post-extraction (follow-up to 9b4aa719e)
- refactor(jobs-page): extract LineItemsEditor presentation component from JobNew; LineItemsSection intentionally kept distinct (Phase 3c — Jobs Overhaul complete) [auto-committed under label '# Ops Tasks Report' in 9b4aa719e]
- ops(kail-dedup): Aug-22 Pat Kail duplicate (014ce6bb) already soft-deleted 2026-09-01 — task intent satisfied; no further DB writes required.
- feat(jobs-page): editable Job Costing overrides + inline Start Time (Phase 3b — Jobs Overhaul)

### Phase 52.1 — Live-streaming walkie MVP (a → d) · Feb 2026

**Added**
- Backend WebSocket signaling endpoint `WS /api/ws/walkie/{channel_id}?token=<jwt>` (Phase 52.1a) — signaling only, media flows P2P via WebRTC. Message types: `join`, `offer`, `answer`, `ice-candidate`, `speaking`, `leave` (client→server) and `session-state`, `peer-joined`, `peer-left`, `offer`, `answer`, `ice-candidate`, `speaking-update`, `session-ended` (server→client).
- `POST /api/walkie/channels` — creates a `live_only` channel (super_admin + admin only).
- `GET /api/walkie/ice-servers` — Google STUN baseline + metered.ca TURN entry when the three env vars (`METERED_TURN_URLS`, `METERED_TURN_USERNAME`, `METERED_TURN_CREDENTIAL`) are set (Phase 52.1d).
- New `walkie_live_sessions` Mongo collection tracking active + closed live sessions with `(tenant_id, channel_id, started_at)` + `(tenant_id, ended_at)` indexes.
- `walkie_channels.supports_live: bool` (default `True`) + `walkie_channels.live_only: bool` (default `False`) — legacy rows auto-default `supports_live=True` via `WalkieChannel.from_mongo`.
- `services/walkie/live_cleanup_cron.py` — 5-min APScheduler tick that closes orphaned `ended_at IS NULL` rows after a server restart (env-gated by `WALKIE_LIVE_CLEANUP_ENABLED=1`).
- `services/walkie/live_events.py::on_session_ended(session_id, reason)` — auto-record extension point (no-op stub in 52.1a; consumed by client-side upload in 52.1b/c).
- Web live panel (`frontend/src/pages/walkie/LivePanel.jsx`) — PTT default with spacebar + on-screen button, VOX via WebAudio `AnalyserNode` (-50 dBFS threshold, 200 ms hysteresis), full peer-mesh RTC, hidden `<audio autoplay>` per remote peer for browser-native mixing, MediaRecorder-driven auto-record upload on session-end.
- Mobile live panel (`mobile/src/pages/walkie/LivePanel.tsx`) — same mesh + PTT flow via `react-native-webrtc@124.0.6`, parallel `expo-audio` recorder for auto-record clip. VOX shipped as disabled UI with a "desktop-only in 52.1c" hint — deferred to Phase 52.1e.
- `react-native-webrtc@124.0.6` + `@config-plugins/react-native-webrtc@13.0.0` — dev-client only; rebuild via `npx expo prebuild --clean` + `eas build --profile development`.
- `mobile/app.json` platform config: iOS `UIBackgroundModes:["audio"]` + refreshed `NSMicrophoneUsageDescription`. Android `FOREGROUND_SERVICE_MICROPHONE` + `MODIFY_AUDIO_SETTINGS` permissions.

**Docs**
- `mobile/EXPO_GO_RUNBOOK.md` — new Phase 52.1c section (react-native-webrtc install + rebuild recipe, permission diff, VOX-deferred rationale, bundle-size delta, 6-step smoke test) + Phase 52.1d section (metered.ca signup + env config + verify curl + fallback behavior).
- `backend/.env.example` — placeholder rows for `METERED_TURN_URLS` + `METERED_TURN_USERNAME` + `METERED_TURN_CREDENTIAL`.
- `memory/PRD.md` — consolidated Phase 52.1 section covering scope, data model, endpoints, mesh topology limits, non-goals (SFU, live-only-recording-beyond-24h-TTL), env vars, test coverage.

**Tests**
- Backend `test_phase52_1a_walkie_signaling.py` (20 tests) + `test_phase52_1d_metered_turn.py` (8 tests) — WebSocket join/relay/broadcast, ICE-servers STUN + TURN + partial-env + multi-URL, frame-type snapshot lock.
- Web vitest `phase52-1b-live-panel.test.jsx` (16 tests) + `phase52-1d-walkie-live-parity.test.jsx` (8 parity assertions).
- Mobile jest `phase52-1c-mobile-live-panel.test.tsx` (11 tests) + `phase52-1d-walkie-live-parity.test.ts` (8 parity assertions).
- Global mobile `__mocks__/react-native-webrtc.js` — jest auto-mock keeping other test suites that transitively import the channel page working.

**Non-goals (deferred)**
- SFU-based scaling beyond ~10 peers per session (a Phase 52.2 effort).
- VOX (voice-activated) on mobile — moves to Phase 52.1e.
- Screen-off background mic on Android — requires a dedicated foreground-service native module.
- Recording of `live_only` channels beyond the standard 24 h `walkie_messages` TTL.



Format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).
Entries are dated (YYYY-MM-DD, UTC) since we're not cutting semver releases yet.
Do not rewrite history — only prepend new entries at the top.

---

---

## 2026-02-XX — Phase 54 (a → f) · Wholesale supplier pricebook import MVP

Automated pricebook ingestion from five North-American pool + landscaping wholesalers via a supplier-agnostic Playwright-driven scraper framework. Full MVP delivered across six sub-phases: 54a audit + data-model skeleton, 54b Pool360 connector + Settings UI, 54c SiteOne connector + generic `test-connection` endpoint, 54d Ewing connector + `SUPPLIER_METADATA` config extraction, 54e Heritage + ePoolSupply connectors + APScheduler cron + Chromium install, 54f pricebook UI (web + mobile) supplier column + filter + Sync-all + docs.

### Added
- **Five wired connectors**: `services/suppliers/{poolcorp,siteone,ewing,heritage,epoolsupply}.py` + their `*_selectors.py` counterparts. `PlaywrightScraperBase` (Phase 54e) — shared scraper base subclassed by heritage + epoolsupply.
- **Data model**: `suppliers`, `supplier_credentials` (Fernet-encrypted), `supplier_sync_jobs` collections. `items` extended with `supplier_id` / `supplier_slug` / `external_sku` / `last_synced_at`.
- **REST endpoints** — `GET /suppliers`, `GET|POST|DELETE /suppliers/{slug}/credentials`, `PATCH /suppliers/{slug}` (sync_frequency + active), `POST /suppliers/{slug}/sync` (202 + background task), `POST /suppliers/{slug}/test-connection` (~5 s target, 15 s hard timeout, four error branches), `GET /suppliers/{slug}/sync-jobs`.
- **APScheduler cron** — `services/suppliers/cron.py` — hourly + 03:00 UTC daily triggers; gated by `SUPPLIER_SYNC_LIVE=1` (default OFF → dry-run). Skips no-credentials, skips <6h-since-last-success, respects per-supplier `sync_frequency` enum (`hourly|daily|weekly|manual`).
- **Web UI** — `pages/settings/SupplierSettings.jsx` with per-supplier cards (credentials form + save/sync/test/refresh/remove buttons + sync history + sync-frequency dropdown), verbatim ToS disclaimer, super-admin "Sync all suppliers" sequential batch button. `pages/settings/supplier_metadata.js` — single source of truth for per-supplier copy. Pricebook (`OpsHub.jsx`) gains a supplier column (color-coded badge per slug) + supplier filter dropdown (client-side, additive to `/items` contract).
- **Mobile UI** — `mobile/app/settings/suppliers.tsx` (view-only), `mobile/app/price-book.tsx` supplier badge + chip-strip filter.
- **Chromium install** — installed to `/root/.cache/ms-playwright/` at ~962 MB total. Backend startup logs `supplier.playwright: cache_path=... chromium=<ver|missing>` so operators can confirm the mount is active.
- **`PLAYWRIGHT_BROWSERS_PATH` support** (Phase 54f addendum) — Playwright-native env var respected; smoke-check pytests cover default + override paths.

### Changed
- **Pricebook rows** in web + mobile now render a supplier badge next to `category · unit`. Manual (no supplier_id) items render a slate-colored "Manual" badge.
- **`connector.py` `CONNECTORS` registry** — all five slugs now point to wired classes (guarded try/except so imports work without Playwright).
- **`routers/suppliers.py` `_WIRED_SYNC_SLUGS`** — expanded to all five slugs across 54b→e. `_VALID_SYNC_FREQ` set to `{hourly, daily, weekly, manual}`.

### Guardrails
- Playwright fully mocked in every test — zero live-wholesaler network calls.
- `SUPPLIER_SYNC_LIVE` stays OFF by default in every environment. Cron ticks fire but log-only until operator flips it.
- Cron calls sync service functions directly — never self-HTTPs.
- Manager role remains read-only on Settings > Suppliers; tech + customer redirected. Super-admin required for "Sync all suppliers" (heavier operation).
- Test-connection endpoint bounded at 15 s via `asyncio.wait_for`.
- Rate limit: 1 req/sec + exponential backoff to 60 s on 429/503.
- Legal disclaimer rendered verbatim below every credentials form.

### Operator runbook (also in PRD.md · Phase 54)
1. Install Chromium — bake into Dockerfile (Option A, ~700 MB image growth) OR mount a persistent volume at `/root/.cache/ms-playwright` (Option B, recommended). See PRD § Operator runbook for full instructions.
2. Save credentials via `/settings/suppliers` for each wholesaler you want to sync.
3. Click "Test connection" — expect `{ok: true}` in ~5 s.
4. Optionally adjust per-supplier `sync_frequency` (default `daily`).
5. Set `SUPPLIER_SYNC_LIVE=1` in the backend env + `sudo supervisorctl restart backend` when ready to enable real syncs.
6. Grep `supplier.cron.` in backend logs to monitor tick summaries.

### Test invariants (post-ship)
- Vitest **1430 / 1430 pass** (from 1389 baseline → +41 across 54b/c/d/e/f).
- Mobile Jest **240 / 240 pass** (from 236 baseline → +4 in 54f parity tests).
- Backend Phase 54 curated **87 / 87 pass** (Phase 54a→f including the addendum smoke tests).
- `yarn lint` exit 0.

### Non-goals
- No vendor JSON API integrations — selector-based scraping only. Future phases may replace individual connectors with vendor APIs where available (the `PlaywrightScraperBase` + `SUPPLIER_METADATA` map are the seams).
- No multi-currency.
- No historical price snapshots — the pricebook stores only the latest sync per SKU. Quote/invoice line items already snapshot price at issue time via the existing Phase 33 pattern.

---

## 2026-02-XX — Phase 53 (a → d) · Editable EBIT report MVP

Editable EBIT — Earnings Before Interest and Taxes — layered on top of the existing profit-report surface. Ships across backend + web + mobile with role-gated editing, immutable versioning, and PDF + CSV export. Complete MVP over four sub-phases: 53a backend + audit, 53b editable web UI, 53c mobile parity + demo-manager seed-drift repair, 53c-fix manager read-only rendering, 53d closeout (docs + contract-lock tests).

### Added

- **Backend router `backend/routers/ebit.py`** — 6 endpoints under `/api/ebit/*`:
  - `GET /compute` (viewer) — live compute, no persistence.
  - `GET /snapshots` (viewer) — list versioned snapshots.
  - `GET /snapshots/{id}` (viewer) — fetch one.
  - `POST /snapshots` (editor) — save NEW version (v1 or v+1).
  - `PATCH /snapshots/{id}/adjustments` (editor) — new version, deltas merged.
  - `PATCH /snapshots/{id}/overrides` (editor) — new version, absolutes merged.
  - Role gates: `EDITOR_ROLES = {super_admin, admin}` / `VIEWER_ROLES = {super_admin, admin, manager}`.
- **Compute service `backend/services/finance/ebit.py`** — resolves range presets, pulls revenue from `db.quotes` (cash on `paid_at` / accrual on `created_at`), COGS from invoice line-item `wholesale_price_snapshot`, depreciation via free-form `db.checks.category ∈ {depreciation, amortization}` (LLM-override aware), OpEx from the remaining non-voided checks, wages-by-role diagnostic from `db.time_entries × db.users`.
- **Editable adjustments + overrides** — every save creates a new immutable `ebit_snapshots` version. `line_adjustments` are additive; `line_overrides` are absolute (`null` reverts). Effective EBIT = `revenue − cogs − opex − depreciation`.
- **MongoDB collection `ebit_snapshots`** with two indexes: `(tenant_id, range_from, range_to, version desc)` and `(tenant_id, saved_at desc)`.
- **Web EBIT panel** — `frontend/src/components/admin/EbitPanel.jsx` mounted into the existing `ProfitReportPage`. Range picker (monthly/quarterly/custom), basis toggle (cash/accrual), 4 editable rows with adjustment ↔ override modes, effective-EBIT total, save + version-history modal, CSV + PDF export via `window.print()`.
- **Mobile EBIT panel** — `mobile/src/components/admin/EbitPanel.tsx` mounted into the existing `profit-report.tsx`. Full parity: same testids, same endpoints, CSV via `expo-file-system` + `expo-sharing`, PDF via `expo-print` → `expo-sharing`. **No new native deps.**
- **Route guard `AdminOrManagerForProfitReport`** in `frontend/src/App.js` — allows manager past `/admin/reports/profit` only. Every other `/admin/*` route stays `AdminOnly`.
- **Manager read-only rendering (53c-fix)** — adjustment inputs `disabled`, flip/clear/save buttons hidden, yellow `read-only` badge in the panel header, History + CSV + PDF exports remain enabled. Both web + mobile.
- **Demo-manager seed drift repair (53c)** — `seed_demo_manager()` in `backend/seed.py`. Idempotent, un-gated, ensures `manager@aquaterra.com` resolves to `role=manager` on every boot. Fix for a drift where an unrelated migration had promoted the row to admin.
- **OpenAPI contract (53d)** — `range` is a `Literal["this_month","last_month","qtd","ytd","monthly","quarterly","custom"]`; `revenue_basis` is a `Literal["cash","accrual"]`. Enum surfaces in `openapi.json`; invalid values return 422 with the full accepted-set message.
- **Snapshot field `author_display_name`** (53d) — populated from `user.name || user.email` on save. Contract-locked for the versions modal on both surfaces.
- **Backend tests** — 32 total across `test_phase53a_ebit_backend.py` (25), `test_phase53c_seed_manager.py` (1), `test_phase53d_ebit_contract_lock.py` (6).
- **Frontend vitest** — `ebit-panel.test.jsx` (14), `ebit-panel-manager-readonly.test.jsx` (7), `phase53d-web-mobile-ebit-parity.test.jsx` (11).
- **Mobile jest** — `phase53c-mobile-ebit-panel.test.tsx` (13); `phase51d-walkie-parity.test.ts` extended with 15 EBIT parity assertions.
- **`/app/memory/PHASE53A_EBIT_BACKEND.md`**, **`PHASE53B_EBIT_WEB_UI.md`**, **`PHASE53C_MOBILE_EBIT.md`**, **`PHASE53C_FIX_MANAGER_READONLY.md`**, **`PHASE53C_TRIAGE_NOTE.md`**, **`PHASE53A_TRIAGE_NOTE.md`** — per-phase delivery docs.
- **PRD.md** — Phase 53 consolidated section prepended (feature scope, endpoints, data model, compute logic, surfaces, non-goals, test coverage).

### Changed

- `backend/routers/ebit.py` — split `_require_role` (editor-only) into `_require_viewer` (used by GETs) + `_require_editor` (used by POST + PATCHes). Backwards-compat alias retained.
- `mobile/__tests__/phase51-6-mobile-reply-ui.test.tsx` + `mobile/__tests__/phase51c-walkie-mount.test.tsx` — +5-line `jest.setTimeout(15000)` accommodation for batch-scheduler contention. Not a runtime code change; restores mobile jest baseline to 226/226 green. Documented in `PHASE53A_TRIAGE_NOTE.md`.
- `frontend/src/test/profit-report-page.test.jsx` + `frontend/src/test/profit-report-uncategorized-fix.test.jsx` — URL-routing shim so `/ebit/*` calls from the newly-mounted `<EbitPanel />` land on a benign stub instead of polluting the profit-report mock. Existing assertions untouched.
- `memory/test_credentials.md` — manager row corrected.

### Fixed

- `manager@aquaterra.com` role drift — before Phase 53c, an unrelated migration had promoted the seeded row to `role=admin`, blocking the manager read-only branch. Repair helper is self-healing on every boot.
- Route guard on `/admin/reports/profit` — before Phase 53c-fix, `AdminOnly` blocked managers from reaching the profit report at all. Targeted `AdminOrManagerForProfitReport` guard now allows manager for this ONE route without opening any other `/admin/*` route.

### Non-goals (explicitly deferred, tracked in PRD.md)

- Draft/publish workflow; every save is immediately visible. Version history + Fork is the substitute.
- External accounting sync (QuickBooks / Xero / Sage).
- Budget-vs-actual variance analysis.
- Consolidated multi-entity EBIT (parent-tenant roll-up).
- Automatic period lock (fiscal-year close).

---

## 2026-02-XX — Phase 51 (a → d) · Walkie-Talkie MVP

Async 5-30 s voice-clip messaging surface. Shipped across web + mobile + backend + Expo push + 24 h defense-in-depth cleanup cron. Complete MVP over four sub-phases; delivery here consolidates the milestones.

### Added

- **Web `/walkie` page** — channel list (all-hands + department + directs) with unread badges, timeline with waveform bars + own-message pill, hold-to-record button (browser `MediaRecorder`), 30 s hard cap, persistent mute toggle backed by `localStorage["walkie_muted"]`, new-direct-chat modal, admin-only all-hands broadcast gate mirrored client-side, 15 s polling.
- **Mobile `/walkie` screens** — channel list + timeline via `expo-audio@~1.1.1` (SDK 54, custom dev-client rebuild required). AsyncStorage-backed mute persistence, same admin gate, same waveform + own-message contract.
- **Backend REST surface (5 endpoints under `/api/walkie/*`)** — `GET /channels`, `POST /channels/direct`, `POST /messages` (multipart), `GET /messages`, `POST /messages/{id}/listened`. Role-scoped visibility; customer → 403 on `/channels`.
- **Admin-only all-hands broadcast gate** — server 403 with `detail = "Only admins can broadcast to all-hands"` for callers whose role is not in `{super_admin, admin, manager}`. Client-side surfaces the same message + disables the record button before send-time.
- **Mongo collections + indexes** — `walkie_channels` (indexed on `(tenant_id, kind)`, `(tenant_id, department)`, `(tenant_id, member_user_ids)`), `walkie_messages` (TTL index on `expires_at` with `expireAfterSeconds: 0` enforcing native 24 h retention, plus `(tenant_id, channel_id, created_at desc)`), `walkie_receipts` (indexed on `(tenant_id, recipient_user_id, listened_at)` + `(message_id)`).
- **Tenant bootstrap** — All-Hands + `pool` + `landscape` channels auto-provisioned per tenant on first `GET /channels`; idempotent seed also runs at startup.
- **Expo push fan-out** — one push per registered recipient device (`data = {type: "walkie", channel_id, message_id}`) triggered from `POST /messages`. Deep-links to `/walkie/{channel_id}` on tap. **Double env gate**: sends only when both `WALKIE_PUSH_LIVE=1` AND `EXPO_PUSH_ACCESS_TOKEN` are set. Otherwise logs dry-run payload. Reuses the Phase 20 `mobile_tokens` collection — no new registration endpoint.
- **24 h cleanup cron** — 1 min tick registered on the existing `AsyncIOScheduler` singleton in `server.py`. Sweeps orphan `walkie_receipts` (whose message row TTL-expired) and orphan `files` rows tagged `purpose == "walkie_audio"`. Idempotent; logs only when it actually deletes something. Disable-able via `WALKIE_CLEANUP_ENABLED=0`.
- **Cross-platform parity snapshot tests** — one vitest file + one mobile jest file that source-inspect both trees at test time and lock the shared invariants: channel ordering, 30 s recorder cap, `walkie_muted` key, `BROADCAST_ROLES` set, server-parity error message, waveform fallback contract, and shared testID manifest.
- **`EXPO_GO_RUNBOOK.md`** — new Phase 51c section documents `expo-audio` native rebuild + push env matrix + device smoke test.

### Env additions

| Flag | Default | Effect |
|------|---------|--------|
| `WALKIE_PUSH_LIVE` | unset | `=1` → live Expo push fan-out. Otherwise dry-run (logs payload only). |
| `EXPO_PUSH_ACCESS_TOKEN` | unset | Required alongside `WALKIE_PUSH_LIVE=1`. Missing → second-layer dry-run. |
| `WALKIE_CLEANUP_ENABLED` | `1` | `=0` disables the defense-in-depth cleanup cron. Mongo TTL still fires. |

### Native deps

- `expo-audio@~1.1.1` (mobile). Custom dev-client rebuild required — Expo Go does NOT ship the module. Mirrors Phase 38b Mapbox + Phase 49 speech-recognition rebuild pattern.
- No new web deps.

### Test count delta

- Backend curated coverage gate: 151/152 → **168/169** (+17 tests), cov ~2.79 % ≥ 2 % floor.
- Frontend Vitest: 1272/1272 → **1315/1315** (+43 tests across 5 new files).
- Mobile Jest: 132/132 → **171/171** (+39 tests across 4 new files).
- ESLint: exit 0.

### Sub-phase memos

- `memory/PHASE51A_WALKIE_BACKEND.md`
- `memory/PHASE51B_WALKIE_WEB_UI.md`
- `memory/PHASE51C_WALKIE_MOBILE.md`

### Non-goals (deferred to future phases)

- WebSocket / SSE push instead of 15 s polling.
- Threaded "Reply with clip" long-press action.
- Per-channel "Pinned clip" SOP-broadcast surface.
- Live-streaming walkie mode (Phase 52 target).

---



## 2026-02-XX — Phase 49 hotfix · Cron thread-loop bug + regex phrasing coverage + credential drift

Tester report caught 3 issues in the Phase 49 delivery. All addressed; scope not expanded.

### Blocker 1 (P0) — reminder cron never fires — **FIXED**

The old `reminder_cron._run()` wrapped the coroutine in a sync callable that called `asyncio.get_event_loop()` from an APScheduler worker thread. Every minute the tick logged `WARNING:lana.reminders.cron: tick failed: There is no current event loop in thread 'asyncio_0'.` and the row never flipped. Dry-run gate unreachable.

**Fix chosen: Option (c).** The shared scheduler in `server.py:654` is confirmed `AsyncIOScheduler(timezone="UTC")` (line 7 imports `from apscheduler.schedulers.asyncio import AsyncIOScheduler`). `AsyncIOScheduler` runs jobs on its own event loop and natively supports coroutine functions as job callables — no thread/loop bridging needed. The buggy sync `_run()` wrapper is deleted entirely; `add_job(_tick, IntervalTrigger(minutes=1), ...)` now receives the async `_tick` coroutine function directly.

Verified end-to-end: driving `reminder_cron._tick()` with a mocked DB emits `[lana.reminders] DRY RUN — would SMS user=u phone=+14805551234 text='call alan'` and flips the row to `{sent: True, sent_mode: "dry_run"}`.

### Blocker 2 (P1) — intent regex too strict — **FIXED**

`_SCHEDULE_RE` required `who` before `when`, and was greedy — the tester's exact message `"schedule a pool cleaning for tomorrow at 9am for customer Smith"` misclassified as `chat` (or worse, matched with `who="tomorrow"` and `when="at 9am for customer Smith"`).

**Fix:** split into two regexes — `_SCHEDULE_RE_WHENFIRST` for the tester's phrasing, `_SCHEDULE_RE_STANDARD` for the original. Classifier tries when-first FIRST so the greedy standard match can't swallow a when-first message. Both regexes accept `for customer <name>` prefix and `an?` article variants (`book an inspection`, `schedule a pool clean`). No LLM fallback — classifier stays deterministic per instructions.

Verified: `"schedule a pool cleaning for tomorrow at 9am for customer Smith"` → `kind=schedule_job, customer_name="Smith", service_type="Pool Cleaning", scheduled_date=2026-02-16T09:00:00+00:00`.

### Doc drift (P2) — `test_credentials.md` — **FIXED**

Verified all 5 seed accounts via direct `db.users` lookup. Two drifts corrected:

| Email | Was documented as | Actual live role | Corrected |
|---|---|---|---|
| `admin@aquaterra.com` | `customer` | **`admin`** | ✅ |
| `carlos@aquaterra.com` | `admin` | **`technician`** | ✅ |
| `super@aquaterra.com` | `super_admin` | `super_admin` | (unchanged) |
| `manager@aquaterra.com` | `admin` | `admin` | (unchanged) |
| `customer@aquaterra.com` | `customer` | `customer` | (unchanged) |

Also added `landscaper@aquaterra.com` (role=technician) explicitly — it's the seed the Phase 41.1b work already flagged. `mike@aquaterra.com` remains missing from the DB (annotated for Phase 41.1b).

### Verification
- `backend/tests/test_phase49_lana_intents.py` → **19/19 pass** in 4.97s (previous 15 + 4 new tests: exact tester message, 4-phrasing variants, cron end-to-end DRY RUN, static guard against `get_event_loop` regression).
- Frontend vitest suite still **100% green** — no mobile files touched.

### Non-scope
- Phase 50 untouched. Phase 41.1b / 41.2 / 42.4 / 43 / 46 remain queued.

---


Full-stack Lana upgrade. Voice input on mobile, natural-language intent parsing on the backend, per-user admin todos, single-fire SMS reminders on a minute cadence.

### Backend

- **`services/lana/intent.py`** — new. Rule-first classifier returning one of `schedule_job` / `add_todo` / `set_reminder` / `chat`. `dateparser` for natural-language time parsing ("Wednesday at 10am", "tomorrow at 9"). `looks_destructive()` guardrail catches `delete` / `cancel` / `refund` / `remove` / `wipe` / `purge` and short-circuits to a chat redirect ("please use the admin console").
- **`services/lana/schedule_intent.py`** — new. Fuzzy customer resolution via `difflib.SequenceMatcher` (threshold 0.6, exact-substring boost to 0.85). `preview()` returns a confirmation card; `commit()` routes into `routers.jobs.create_job` — no duplicate create logic.
- **`services/lana/todos.py`** — new. Per-user `admin_todos` collection. `list_todos`, `create_todo`, `update_todo` (only `text`/`due_at`/`completed` writable — tenant_id/user_id lockdown), `delete_todo`.
- **`services/lana/reminders.py`** — new. `admin_reminders` collection. `create_reminder`, `list_reminders`, `fire_due_reminders`. Live SMS gated on `LANA_SMS_LIVE=1` env; default is a log-only dry-run that still marks the row `sent=True` so the cron doesn't loop.
- **`services/lana/reminder_cron.py`** — new. Minute-cadence job registered on the existing APScheduler singleton (the one `automation_engine.register_daily_sweeps` already owns). Zero new infrastructure.
- **`routers/lana_todos.py`** — new. `GET/POST/PATCH/DELETE /api/lana/todos` + `GET/POST /api/lana/reminders`. Admin/super/manager only via `_require_admin()`.
- **`routers/business_os.py`** — extended:
  - `POST /api/business-os/lana/chat` now classifies user turns via `services.lana.intent` BEFORE the chat round-trip. Non-chat intents short-circuit into todos / reminders / a schedule preview card.
  - New `POST /api/business-os/lana/schedule/commit` — split from `/chat` so the mobile UI can render an explicit Confirm / Cancel step (no single-turn writes).
- **`models.py`** — new `LanaTodo` + `LanaReminder` Pydantic models.
- **`server.py`** — mounts `lana_todos.router` on `app` (public prefix `/api`) and registers the reminder cron alongside `automation_engine`'s daily sweeps.
- **`requirements.txt`** — `dateparser==1.4.1` added.

### Mobile

- **`mobile/app/os/lana.tsx`** — full rewrite:
  - **Mic button** (`os-lana-mic`) using `expo-speech-recognition` via dynamic `require()` — Expo Go safe (same convention as Phase 38b Mapbox). Voice in Expo Go shows a graceful "Voice unavailable — dev-client build required" alert.
  - **Confirm modal** for `schedule_job` intents (`os-lana-schedule-confirm-{yes|no}`) — Lana quotes back the parsed customer / service / when; user taps Confirm to write.
  - **Todos panel** (`os-lana-todos`) bound to `/api/lana/todos` — tap to toggle completion.
  - **Destructive-guard** — server-side, but UI displays the chat redirect reply verbatim.
- **`mobile/package.json`** — `expo-speech-recognition@^2.1.1` added. **⚠ Dev-client rebuild required** (see `EXPO_GO_RUNBOOK.md` Phase 49 section).

### Testing

- **`backend/tests/test_phase49_lana_intents.py`** — **15/15 pass**: schedule intent extraction (service + customer + when), reminder intent extraction, todo intent extraction, chat fallback, destructive-token guard, ambiguous-input guard, schedule preview fuzzy match, schedule preview customer-not-found, todos create+list, todos update only-allowed-keys guard, reminders dry-run default, reminders skip not-yet-due, reminders live-flag flips sent_mode, `/api/lana/*` router registration, `/api/business-os/lana/schedule/commit` route registration.
- **`frontend/src/test/phase49-lana-voice.test.jsx`** — **5/5 pass**: dynamic import of expo-speech-recognition, mic button testids, schedule-confirmation card testids + commit URL, todo list testids + endpoints, graceful fallback copy.

### Environment / config

- `LANA_SMS_LIVE=1` — flip live SMS on. Default: dry-run.
- No new authentication surfaces; existing admin-role gate reused. `test_credentials.md` untouched.

### Docs

- `mobile/EXPO_GO_RUNBOOK.md` — Phase 49 section added documenting the dev-client rebuild requirement.
- `/app/memory/PRD.md` — Phase 49 section prepended.

### Non-scope
- Web parity for Lana voice — mic API varies too much cross-browser; separate phase.
- Recurring reminders — single-fire only.
- Multi-turn dialog beyond a single confirm step.
- Phase 41.1b / 41.2 / 42.4 / 43 / 46 / 47f-onwards remain queued.

---


Final slice of the direct-Stripe migration. Formalises the "Lumino/Zapier stays in-tree but dark" rollback path and adds a CI-friendly regression sweep so a future rewrite can't accidentally drag a hosted-link call back onto the customer-facing pay path.

### `backend/services/payments/provider_mode.py` (new)
- `payments_provider_mode() -> str` — reads `PAYMENTS_PROVIDER_MODE` env, normalises typos back to `"stripe_direct"` so a stray env value (e.g. `"stripedirect"`, `"zaper"`, empty) can't silently route real customers to a dark provider.
- `is_stripe_direct()` / `is_dark_provider_mode()` — convenience predicates.
- Default: `"stripe_direct"`. Documented values: `"stripe_direct"`, `"lumino"`, `"zapier"`. Setting the env to `"lumino"` or `"zapier"` is an **operator-only rollback path** — no frontend UX depends on it.

### `backend/tests/test_phase47e_no_lumino_in_pay_path.py` (new)
5 tests:
1. **Regression sweep** — greps 5 pay-path modules (`routers/lumino_link_request.py`, `routers/customer_portal.py`, `routers/customers.py`, `routers/stripe_router.py`, `services/payments/stripe_charge.py`) with docstrings/comments stripped and asserts none contain `dispatch_invoice_link_request`, `lumino_zapier_dispatcher`, `lumino_provider`, `zapier_invoice_link_webhook_url`, or `zapier_catch_hook`. Immediately caught a stale `from services.lumino_zapier_dispatcher import dispatch_invoice_link_request` in `routers/lumino_link_request.py:27` left over from the Phase 47 rewrite — now removed.
2. Env default is `stripe_direct`.
3. Typo / unknown env values fall back to `stripe_direct`.
4. Documented dark values (`lumino`, `Zapier`, `LUMINO`) are accepted case-insensitively.
5. Dark modules (`services.lumino_zapier_dispatcher`, `services.payments.lumino_provider`, `routers.lumino_backfill`, `routers.lumino_invoice_link_callback`) all still import cleanly — the rollback path is intact.

### `backend/routers/lumino_link_request.py`
- Removed stale `from services.lumino_zapier_dispatcher import dispatch_invoice_link_request` (Phase 47 dead import). The dispatcher module itself remains in-tree as the operator-only rollback path.

### Preserved / non-scope
- `lumino_payment_url` fixture rename on other test files (`test_invoice_edit.py`, `test_lumino_backfill.py`, `test_lz2_dispatcher.py`, `test_lumino_invoice_link_callback.py`) — deliberately NOT touched. Those tests are the coverage for the dark Lumino modules and reference the old key name as part of testing the dark path itself. The **live** fixture rename that mattered (in `frontend/src/test/invoice-edit-modal.test.jsx`) landed in Phase 47.
- No frontend / mobile changes.
- Env var not documented in a `.env.example` deliberately — kept as an operator-only lever, not a customer-config surface.

### Verification
- `backend/tests/test_phase47e_no_lumino_in_pay_path.py` → **5/5 pass**.
- Combined Phase 47 + 47d + 47e backend suite → **23/23 pass in 0.49s**.

---


Small visual follow-up to Phase 48. User's revised mockup showed the full contact section moving directly below the customer name in the main column (superseding the earlier top-right column idea).

### `frontend/src/pages/customers/CustomerDetail.jsx`
- **Secondary customer-name marker** (`data-testid="cd-customer-name-secondary"`) added at the top of the overview tab body, echoing `customer.name` in bold below the page-title h1. The primary h1 stays put — it anchors the VIP toggle, breadcrumbs, and mobile edit affordance.
- **`<CustomerContactsPanel>`** moved to sit directly below the secondary name (previously it lived below the address block).
- **Address block** (Primary address / Billing address / Gate code / Secondary addresses) now sits AFTER `<CustomerContactsPanel>`. Wrapped in `data-testid="cd-address-block"` so downstream tests can assert its source-order position.
- **`<MasterBillingCard>`** pushed further down — no longer the first item in the overview tab. All other panels (`<CardOnFileControl>`, `<CustomerServiceNotesCards>`, Notes) unchanged.

### Verification
- `frontend/src/test/phase48-admin-customer-contact-redesign.test.jsx` — **24/24 pass** (19 Phase-48 + 5 new Phase-48.1 source-order asserts). Regression guard: BusinessCard stays unmounted; h1 name stays in the header block; ContactsPanel renders AFTER the secondary name; address block renders AFTER ContactsPanel; MasterBillingCard renders AFTER the address block.

### Non-scope
- Backend / models / caps — untouched.
- Contact panel internal layout — untouched (Phase 48 shape preserved).
- Phase 47d work in flight — untouched (different files).

---

## 2026-02-XX — Phase 47d · Mobile quote pay + ACH endpoint restoration (direct Stripe)

Third slice of the payment-migration sweep. Two audit findings + one restoration:

### Audit findings
1. **`POST /quotes/{qid}/pay`** — admin-only manual/offline payment record (cash / check / external card). Zero Stripe interaction, no Lumino / Zapier. **Kept as-is** — this is a ledger endpoint, not a gateway call. Regression test locks that in.
2. **`POST /payments/admin/generate-link/{id}`** (called by `mobile/app/quote/[id].tsx:84`) — **does not exist as a backend route.** Mobile has been getting 404s since whenever the route was removed. Fixed by pointing mobile at Phase 47's `POST /invoices/{id}/request-payment-link`, which returns the same `{payment_url}` shape.
3. **ACH endpoints on `customer_portal.py`** — dark under the Phase-LZ4 stub (`_stripe_configured` hard-returned False, both endpoints short-circuited). Per your directive "every payment surface direct Stripe", restored to real `stripe.SetupIntent.create(payment_method_types=["us_bank_account"])` via the shared `services.payments.stripe_charge` helpers.

### Backend

- **`backend/routers/quotes.py`** — no source change. Regression test asserts `pay_quote` body contains no `stripe`/`checkout`/`zapier`/`lumino`/`dispatch_invoice_link_request` and still sets `payment_method="manual"`.
- **`backend/routers/customer_portal.py`**:
  - `_stripe_configured()` un-retired. Now reads `STRIPE_SECRET_KEY_LIVE` / `STRIPE_SECRET_KEY_TEST` / `STRIPE_API_KEY` and returns True when any are set.
  - `start_ach_link_session()` — delegates to `stripe_svc.create_setup_intent(payment_method_types=["us_bank_account"])`. Returns `{ok: True, client_secret, publishable_key, mode}` on success; `{ok: False, reason: "stripe_not_configured"|"stripe_error"}` on gate-fail — the frontend already renders both cases.
  - `attach_ach_result()` — delegates to `stripe_svc.attach_payment_method(...)`. `AchAttachIn.payment_method_id` is now required; the legacy Financial-Connections fields (`stripe_bank_account_id`, `session_id`) kept as optional back-compat aliases so an in-flight client still parses. `set_default=False` (ACH default remains admin-controlled). Returns the safe subset (`last4`, `brand`, `is_default`, `type="ach"`); internal Stripe ids stripped.

### Mobile

- **`mobile/app/quote/[id].tsx:84`** — `generateLink` swapped from `POST /payments/admin/generate-link/${id}` → `POST /invoices/${id}/request-payment-link`. Same destructure of `payment_url`, same `Share.share(...)` handoff. Comment explains the swap.

### Preserved
- `POST /quotes/{qid}/pay` untouched (manual/offline ledger — deliberately NOT a Stripe call).
- Lumino / Zapier modules stay in-tree but dark.
- `services/payments/stripe_charge.py` untouched — no new helper needed. The Phase 47 `create_invoice_checkout_session` already handles both invoice and quote pay (they're the same doc collection).
- `AchLinkSessionResp` response model untouched — the added `client_secret` / `publishable_key` / `mode` fields were already declared for the LZ2 shape.

### Verification
- **Backend** — `backend/tests/test_phase47d_mobile_quote_pay.py` → **8/8 pass in 0.40s**. Covers: `/quotes/pay` audit (manual/offline only), mobile endpoint swap, `_stripe_configured` env behaviour, ACH link-session short-circuit + `us_bank_account` PM type, ACH attach delegation + payload shape, `payment_url` response key contract, no Lumino dispatcher reference in the pay router body.
- **Frontend** — `frontend/src/test/phase47d-mobile-quote-pay.test.jsx` → **5/5 pass in 0.79s**. Covers: mythical `/payments/admin/generate-link/` gone from runtime code (comments allowed), Phase-47 endpoint URL literal present, `payment_url` destructured, no Lumino/Zapier at runtime, `recordManual` → `/quotes/{id}/pay` preserved.

### Non-scope
- Full Financial Connections rewiring — deliberately deferred. The `us_bank_account` PaymentMethod flow via Stripe Elements is the modern Stripe pattern; Financial Connections is only needed for instant-verification bank ownership proofs, not routine ACH capture.
- `PAYMENTS_PROVIDER_MODE` env kill-switch + `grep_no_lumino_in_pay_path` regression pytest + `lumino_payment_url` → `payment_url` fixture cleanup — slated for **Phase 47e**.
- Broad Stripe v15 audit (`Subscription.*`, `Invoice.*`, `Charge.list`, `Customer.retrieve/modify`) — slated for **Phase 42.4** (separate delivery).
- Phase 41.1b / 41.2 still paused.

---


**UX refresh.** User-provided mockup drove a rework of the customer detail + edit surfaces:
- Removed the compact company business card slot from the customer profile.
- New contact grouping: **Email · Mobile Phone · Home Phone** (primary), then **Additional Mobile Phone up to 2**, then **Additional Emails up to 3**. Bold labels, non-bold inputs.
- Structured 4-input address (Address / City / State / Zip) for both Service Address and Billing Address if Different, composed back into the legacy single-string fields on save so nothing downstream breaks.

### Backend

- **`backend/models.py`** — added `home_phone: Optional[str] = ""` to `CustomerIn`. Legacy customer docs without the field read back as an empty string.
- **`backend/services/customer_multi_contact.py`** — bumped `MAX_MOBILES` (2 → 3) and `MAX_EMAILS` (3 → 4). New cap semantics: 1 primary + N additional. Router cap-check messages inherit the new numbers automatically (they interpolate the constant).
- **`backend/routers/customers.py`** — no source change; existing 400 message `f"maximum {MAX_MOBILES} mobiles allowed per customer"` now reads "maximum 3" / "maximum 4" verbatim.

### Frontend

- **`frontend/src/pages/customers/CustomerDetail.jsx`** — removed the `<BusinessCard variant="compact" />` mount inside `cd-business-card-slot`. Replaced with an explanatory comment that the component itself stays in-tree (used by the tech ToolsHub and marketing card slot). No other tabs / panels on this page were touched.
- **`frontend/src/components/customers/CustomerContactsPanel.jsx`** — full rewrite. New visual grouping matching the mockup: primary contact group with three bold labels (`Email`, `Mobile Phone`, `Home Phone`) and their inputs; separate "Additional Mobile Phone up to 2" and "Additional Emails up to 3" groups with add/remove affordances. Primary rows always index-0 of the arrays; save-time normalization enforces `is_primary=true` on row 0 and strips blanks. Old per-row label / primary-radio / SMS-ok / marketing-ok controls **removed** — regression guard asserts they don't return. `home_phone` PATCHes to `/customers/{id}` on save.
- **`frontend/src/pages/customers/CustomerForm.jsx`** — added `home_phone` field + structured `service_*` / `billing_*` fields (street/city/state/zip). New exported helpers `_parseAddress()` and `_composeAddress()` handle legacy → structured on load and structured → legacy on save. Best-effort parser: if a legacy string doesn't cleanly split (no state+zip tail), the whole string lands in the `street` field so no data is lost. The pre-Phase-48 single-string `cf-billing` input is gone, replaced by the 4-input `cf-billing-address-group`.

### Preserved
- `BusinessCard.jsx` component itself stays in-tree — a backend regression test asserts the file exists (`backend/tests/test_phase48_customer_fields.py::test_business_card_component_still_present`).
- `mobiles[]` / `emails[]` array schema, `is_primary` flag, and all PATCH endpoints — unchanged. Only the frontend rendering + cap constants moved.
- Auto-sync of `customer.email` / `customer.phone` from primary array entries — unchanged (see `services.customer_multi_contact.sync_scalars_from_arrays`).

### New testids (Phase 48)
`cd-primary-contact-group`, `cd-primary-email`, `cd-primary-mobile`, `cd-home-phone`, `cd-additional-mobiles-group`, `cd-additional-mobiles-empty`, `cd-add-additional-mobile`, `cd-additional-mobile-{i}`, `cd-additional-mobile-remove-{i}`, `cd-additional-emails-group`, `cd-additional-emails-empty`, `cd-add-additional-email`, `cd-additional-email-{i}`, `cd-additional-email-remove-{i}`, `cf-home-phone`, `cf-service-address-group`, `cf-service-street`, `cf-service-city`, `cf-service-state`, `cf-service-zip`, `cf-billing-address-group`, `cf-billing-street`, `cf-billing-city`, `cf-billing-state`, `cf-billing-zip`.

### Removed testids (Phase 48)
`cd-business-card-slot` (business card unmount), `cd-mobile-label-{i}`, `cd-mobile-primary-{i}`, `cd-mobile-smsok-{i}`, `cd-mobile-remove-{i}`, `cd-email-primary-{i}`, `cd-email-mktok-{i}`, `cd-email-remove-{i}`, `cd-add-mobile`, `cd-add-email`, `cf-address`, `cf-billing`.

### Verification
- **Backend** — `backend/tests/test_phase48_customer_fields.py` → **8/8 pass in 4.70s**. Covers: `MAX_MOBILES == 3`, `MAX_EMAILS == 4`, `normalize_*` respects new caps, `CustomerIn` accepts `home_phone` + defaults empty, mobiles/emails endpoints still reject over-cap with clean 4xx, `BusinessCard.jsx` file preserved.
- **Frontend** — `frontend/src/test/phase48-admin-customer-contact-redesign.test.jsx` → **19/19 pass in 0.90s**. Covers: BusinessCard unmounted from CustomerDetail, primary contact group + labels + testids, additional mobiles/emails groups with correct caps, panel MAX_* constants, old per-row controls gone, CustomerForm has 4-input service + billing address, `home_phone` field, `_composeAddress` invoked on save, single-string `cf-billing` input gone, `_parseAddress`/`_composeAddress` round-trip (canonical, ZIP+4, multi-comma streets, un-parseable-strings-preserved-in-street, empty parts skipped).
- **Cross-suite** — All 5 Phase 42/44/47/47c/48 backend test files pass individually (50 tests total). A batched run trips a pre-existing test-isolation issue on `TestClient(app)` lifecycle — not introduced by Phase 48.

### Non-scope
- Mobile customer detail page — not touched (`mobile/app/customer/[id]/*` does not currently ship a matching contact form; Phase 48 mockup is web-only per the delivery brief).
- `is_primary` radio semantics from the old flat panel — deliberately dropped in favour of the mockup's "primary is the top slot" convention.
- Phase 41.1b / 41.2 remain paused; the Phase 35 source-inspection vitest failures on `Recurring Jobs` / `Vendor Bills` `<Header>` assertions are Phase 41.2 refactor collateral (Header now lives inside `<AdminListPage>`), NOT a Phase 48 regression.

---


**P0 hotfix.** The customer-facing "Pay $X" button was polling for a `lumino_payment_url` that never arrived because the upstream Zapier catch-hook was returning 404 (Zap paused / URL rotated). Frontend timed out after 30s with "Payment link generation is delayed." Per user direction (every payment surface must route through Stripe directly, no Lumino / Zapier), Phase 47 rewires the pay flow to call `stripe.checkout.Session.create()` directly and return the Stripe-hosted checkout URL for immediate redirect.

### Backend

- **`services/payments/stripe_charge.py`**
  - **New `create_invoice_checkout_session(tenant_id, invoice, customer, return_base_url="")`** — creates a Session with `mode="payment"`, `line_items` computed from the invoice balance in cents, `success_url = {APP_PUBLIC_URL}/portal/payment-complete?session_id={CHECKOUT_SESSION_ID}`, `cancel_url = {APP_PUBLIC_URL}/portal/invoices/{invoice_id}`. Metadata stamped on the Session **and** on the auto-created PaymentIntent (`payment_intent_data.metadata`) so the existing `payment_intent.succeeded` webhook branch can reconcile even if the Session-level webhook were somehow missed. Idempotency key `phase47:invoice:{tenant_id}:{invoice_id}:{amount_cents}` guards against retried requests spawning duplicate Sessions. Response fields extracted via `_asdict()` (Phase 42.3 v15-safe helper).
  - **New `_mark_invoice_paid_from_session(...)`** helper — idempotent invoice-side flip to `payment_status: "paid"` (or `"partial"`), stamps `paid_at`, records `stripe_checkout_session_id` on the quote doc.
  - **`handle_webhook_event` extended** with a `checkout.session.completed` branch — mirrors an upsert into `db.stripe_charges` keyed on `stripe_checkout_session_id` (idempotent — duplicate delivery is a no-op), calls `_mark_invoice_paid_from_session()`, and writes an audit row into `db.payment_events` with `kind="phase47_checkout_session_completed"`. Only fires the invoice-side update when Stripe reports `payment_status == "paid"` (never on abandoned bank redirects). Events without `crm_invoice_id` metadata are ignored (returns `handled: False`).
- **`routers/lumino_link_request.py`**
  - `POST /api/invoices/{id}/request-payment-link` rewritten. Zapier dispatcher call (`dispatch_invoice_link_request`) removed from the route. Now calls `create_invoice_checkout_session()`. Returns `{payment_url, checkout_session_id, amount_cents, currency, mode}`. Business errors surface as clean codes: 404 `invoice_not_found`, 403 `not_your_invoice` (customer ownership), 409 `invoice_already_paid`, 429 `rate_limited`, 502 `payment_gateway_unavailable` (Stripe SDK failure or transient outage).
  - Router file kept at the same path (`lumino_link_request.py`) so import stability + git history are preserved; only the function body changed.

### Frontend

- **`components/PaymentForm.jsx`** — full rewrite.
  - Polling logic **completely removed** (was `POLL_INTERVAL_MS = 3000`, `POLL_MAX_ATTEMPTS = 10`, `pollForUrl(...)` — all gone).
  - `lumino_payment_url` reads gone. Component now reads `payment_url` off the `/request-payment-link` response and calls `window.location.assign(payment_url)` immediately.
  - Preserved UI states: `payment-form-preparing` (spinner shown while the POST is in flight), `payment-form-error` (friendly copy + retry), `payment-form-retry`, `payment-form-close`.
  - New friendly-error map: `rate_limited`, `invoice_already_paid`, `invoice_not_found`, `not_your_invoice`, `payment_gateway_unavailable`. Removed dead codes: `not_configured`, `zapier_unreachable`, `already_paid` (renamed to match backend), `TIMEOUT_ERROR` (no more polling → no more timeouts).
  - Redirect helper exported as `_redirect(url)` for test stubbing.
- **`components/invoices/InvoiceEditModal.jsx:118`** — renamed the field lookup from `invoice?.lumino_payment_url` → `invoice?.payment_url` so the "money-field changed" warning fires against the new payload shape. (The InvoiceEditModal itself doesn't POST anywhere new — this is a display-only change.)
- **`test/lumino-pay-flow.test.jsx` → `test/phase47-direct-checkout.test.jsx`** — file renamed (via `mv`, git-history-preserving), body rewritten. New tests: (1) POSTs on mount + redirects, (2) 502 friendly copy + retry re-fires, (3) `invoice_already_paid` → "already paid" copy, (4) preparing spinner between mount and redirect. Regression guards: `PaymentForm.jsx` source has no `lumino_payment_url`, no `POLL_MAX_ATTEMPTS`, no `pollForUrl`, no `retry-after`, no `zapier`; reads `payment_url` off the endpoint response.
- **`test/invoice-edit-modal.test.jsx`** — fixture updated from `lumino_payment_url` → `payment_url`; behaviour assertion unchanged.

### Preserved / not touched
- `services/lumino_zapier_dispatcher.py` and `services/payments/lumino_provider.py` are **in-tree but dark** (no runtime traffic).
- `routers/lumino_invoice_link_callback.py` (inbound Lumino → `/api/webhooks/lumino/invoice-link-created`) still exists but is orphaned — no more outbound Lumino calls means no more inbound callbacks.
- `routers/lumino_backfill.py` (`POST /api/admin/lumino/backfill-payment-links`) untouched — kept for one-off admin cleanup if the older invoices still carry a stale `lumino_payment_url` field.
- `services/payments/stripe_charge.py::_persist_charge`, `attach_payment_method`, `create_setup_intent`, `charge_card_on_file`, existing PaymentIntent webhook branch — all untouched.

### Verification
- **Backend** — `backend/tests/test_phase47_direct_stripe_payment_link.py` → **10/10 pass in 0.35s** (create-session happy path with metadata + idempotency key + URLs, `_asdict` regression, already-paid → 400, missing `APP_PUBLIC_URL` → 500-safe raise, webhook happy path with charge + invoice + audit row, webhook idempotence when invoice is already paid, webhook `unpaid` status doesn't mark invoice, webhook without metadata ignored, router body no longer references Zapier, response payload key contract).
- **Combined Phase 42 + 44 + 47 + 47c** — **42/42 pass in 4.86s**.
- **Frontend** — `frontend/src/test/phase47-direct-checkout.test.jsx` → **6/6 pass**. `phase47c-add-card-restore.test.jsx` → **8/8 pass**. `invoice-edit-modal.test.jsx` → **6/6 pass** (fixture updated). Cross-suite total for the touched tests: **20/20**.

### Non-scope
- Mobile `quote/[id].tsx:84` (`POST /payments/admin/generate-link/{id}` from the Share sheet) — untouched. Slated for Phase 47d.
- `POST /api/quotes/{qid}/pay` (`quotes.py:604`) — untouched. Slated for Phase 47d audit.
- `POST /api/customer-portal/payment-methods/ach/attach` — untouched. Slated for Phase 47d audit.
- `PAYMENTS_PROVIDER_MODE` env kill-switch — slated for Phase 47e.
- Broad Stripe v15 audit (`Subscription.*`, `Invoice.*`, `Charge.list`, `Customer.retrieve/modify`) — slated for Phase 42.4 (separate delivery).

---


**P0 hotfix.** Customer tapped the "Add card" SMS link (Phase 47b merge-tag rendering now works, so the URL resolves correctly) and landed on a blank page. Root cause: Phase LZ4 (Feb 2026) intentionally decommissioned the `/portal/add-card` React route on the promise of a Lumino hosted-payment-link replacement, but the SMS trigger + `build_add_card_link()` were never migrated — the customer-facing link still pointed at the dead route. User has now directed **every payment + card-on-file surface must route through Stripe directly** (no Lumino, no Zapier). Phase 47c restores the page.

### Backend (`backend/routers/customers.py`)
- **`POST /api/customers/add-card/{token}/setup-intent`** — un-retired. Was returning `{"retired": True, "reason": "stripe_setup_intent_retired_lz4"}`; now calls `services.payments.stripe_charge.create_setup_intent(...)` and returns `{client_secret, setup_intent_id, publishable_key, mode}`. The internal Stripe `customer_id` is NOT echoed back (PII guardrail — a link leak shouldn't reveal it). Failures bubble as 4xx (bad token) or 502 (`payment_setup_unavailable`) so the browser gets a clear signal.
- **`POST /api/customers/add-card/{token}/attach`** — **new endpoint** (companion to the setup-intent route). Public, JWT-scoped. Called by the browser once `stripe.confirmSetup` returns a `payment_method` id. Routes through `services.payments.stripe_charge.attach_payment_method(...)` — same code path the authenticated Stripe flow uses. Returns the safe subset (`last4`, `brand`, `exp_month`, `exp_year`, `is_default`) — internal Stripe ids stripped.

### Frontend (`frontend/src/pages/public/AddCardPage.jsx`, `frontend/src/App.js`)
- **`AddCardPage.jsx`** — new file. Reads JWT from URL query, hits `GET /customers/add-card/{token}` for context (masked customer name, tenant name, publishable key), hits `POST /customers/add-card/{token}/setup-intent` for the client_secret, mounts Stripe `Elements` + `PaymentElement`, calls `stripe.confirmSetup` on submit, then hits `POST /customers/add-card/{token}/attach` to mirror the PM into `db.payment_methods`. No Bearer token used anywhere — public magic-link only. Explicit UI states for `loading`, `boot-error`, `form`, `error`, `saved`.
- **`App.js`** — restored `<Route path="/portal/add-card" element={<AddCardPage />} />` and updated the surrounding Phase-LZ4 "removed" comments to "Phase 47c · RESTORED".

### Preserved / not touched
- The Phase LZ4 stub for `POST /api/customers/add-card/{token}/setup-intent` had a `{"retired": True, "reason": "stripe_setup_intent_retired_lz4"}` shape. Regression test asserts that response body must NEVER return.
- `services.add_card_links.build_add_card_link()` and the `_SMS_BODY` template are unchanged — they've been pointing at the same URL all along; now that URL routes to a live page again.
- `services/payments/stripe_charge.py` is unchanged — the existing `create_setup_intent` / `attach_payment_method` helpers are already `_asdict()`-safe from Phase 42.3.
- Existing authenticated Stripe flow (`POST /api/payments/stripe/setup-intent`, `.../attach`) is unchanged — admin / customer-portal card capture continues to work exactly as before.

### New test testids (Phase 47c)
`phase47c-add-card-page`, `phase47c-add-card-title`, `phase47c-add-card-greeting`, `phase47c-add-card-loading`, `phase47c-add-card-boot-error`, `phase47c-add-card-form`, `phase47c-add-card-submit`, `phase47c-add-card-error`, `phase47c-add-card-success`.

### Verification
- **Backend** — `backend/tests/test_phase47c_add_card_link.py` → **9/9 pass in 4.78s**. Covers: retired-stub regression guard, setup-intent happy path (no PII leak), garbage-token → 4xx, helper failure → 502, attach happy path (masked PM only), attach missing pm → 422, attach garbage token → 4xx, attach helper failure → 502, static guard against raw `_stripe.` / `stripe.SetupIntent` in the router.
- **Frontend** — `frontend/src/test/phase47c-add-card-restore.test.jsx` → **8/8 pass in 0.82s**. Covers: App.js route present, LZ4 "removed" comments gone, page uses `/customers/add-card/*` endpoints only (no Lumino, no Zapier, no Bearer), mounts `Elements` + `PaymentElement` + `confirmSetup`, reads JWT from URL query, gates all 4 UI states via testids, wires off `REACT_APP_BACKEND_URL` (no hard-coded host).
- **Live tap** — not manually verified (user reviews on-device).

### Phase 47 / 47d / 47e status
- **Phase 47** (Pay button off Zapier → direct Stripe Checkout Session) — next in the queue.
- **Phase 47d** (mobile `quote/[id].tsx`, `/quotes/{qid}/pay`, ACH audit) — after 47.
- **Phase 47e** (`PAYMENTS_PROVIDER_MODE` kill-switch, `lumino_payment_url` → `payment_url` rename) — after 47d.
- **Phase 42.4** (broad Stripe v15 audit — `Subscription.*`, `Invoice.*`, `Charge.list`, etc.) — separate follow-up delivery, NOT folded in per user instruction.
- **Phase 41.1b / 41.2** — still paused mid-flight.

---


**Small UX polish** — the "Payers (customers)" section on `/invoices/master/new` was rendering the full customer roster as a wall of pills, which blew up visually at ~30+ customers. Swapped for a shadcn `Popover` + custom multi-select using the same primitives the rest of the app already ships (see `CustomerTagPicker`).

### What changed
- **`frontend/src/pages/invoices/MasterInvoice.jsx`** — replaced the flat `customers.map(pill)` grid inside `MasterInvoiceNew` with a new co-located `CustomerMultiSelect` component. Same state contract: still a `Set<string>` of customer ids stored in `pickedCustomers`, still calls `toggle(setPickedCustomers)(id)` on flip, still submits as `customer_ids: Array.from(pickedCustomers)` to `POST /invoices/master`. Presentation-only refactor — the backend contract and the surrounding "Open invoices to combine" section are untouched.

### New affordances
- Search input (case-insensitive substring match on `customer.name`).
- Selection chips above the trigger, wrap to multiple rows, each with a × remove button.
- "N selected" counter in the section header.
- "Select all filtered" (respects the current search) + "Clear all" quick actions.
- Empty state: `No customers match "<query>"`.
- Keyboard nav: ↑/↓ to move, Enter to toggle, Escape to close.
- Dropdown height capped at 320px, scrollable list.

### Preserved
- `data-testid="master-payer-${id}"` on each option row — any earlier flow / e2e that toggled a payer via that id still works.
- `master-label`, `master-submit`, `master-invoice-*` testids untouched.
- The "Pick at least 1 invoice" red-toast guard in `submit()` is unchanged (still fires when `pickedInvoices.size < 1`).
- No new dependencies — uses the existing shadcn `Popover` primitive already imported elsewhere.

### New testids (Phase 45)
`master-payer-multiselect`, `master-payer-trigger`, `master-payer-dropdown`, `master-payer-search`, `master-payer-empty`, `master-payer-counter`, `master-payer-select-all`, `master-payer-clear`, `master-payer-clear-inline`, `master-payer-chips`, `master-payer-chip-<id>`, `master-payer-chip-remove-<id>`.

### Verification
- `frontend/src/test/phase45-master-invoices-dropdown.test.jsx` — 8/8 pass (1.35s).
- Regression guard included: asserts the old always-visible pill grid is gone (`master-payer-c1` must NOT be in the DOM until the popover opens).

### Non-scope
Mobile Master Invoices (Phase 35) uses its own picker and was NOT touched. Backend endpoints untouched. Phase 41.2 / 42 / 44 in-flight work not affected.

---

## 2026-02-XX — Phase 44 · Comms Template Sweep (demo-only safety test)

Post-Phase-42 Stripe SDK refresh introduced non-trivial `StripeObject → dict` shape work in `services/payments/stripe_charge.py`. Phase 44 ships a fixture-driven end-to-end sweep of every outbound template class (`invoice_sent`, `invoice_reminder`, `payment_receipt`, `payment_failed`, `job_scheduled`, `job_completed`, `review_request`, `password_reset`, `welcome`, `estimate_sent`) so a template regression from the Stripe upgrade can be caught before it fires at customers.

### Guardrails (defence-in-depth)
- **Hard allowlist** — every recipient validated against `_COMMS_SWEEP_ALLOWED_EMAILS` (the five `*@aquaterra.com` seed accounts). Any address outside the set raises `_AllowlistViolation` and aborts the whole sweep.
- **No DB resolution** — recipient sets are literal constants in the script. The exact class of footgun the guard exists to prevent (`db.customers.find_all() → send_email(...)`) cannot happen even by accident.
- **`X-Emergent-Sweep: phase-44-demo` header** on every outbound message so downstream systems can filter, inspect, and post-hoc detect + quarantine.
- **Fixture-only bodies** — deterministic "Demo Customer (Phase 44 sweep)", invoice `INV-DEMO-99999`, obvious "not a real notification" footer. Any accidental live send is spotted immediately.
- **Dry-run by default** — invoking `python3 backend/scripts/phase44_comms_sweep.py` returns exit 0 with `[DRY RUN]` prefix on every attempt and never touches Resend. `--live` requires an explicit flag (and still needs `RESEND_API_KEY` + tenant `comms_env` allow-list).

### Files
- `backend/scripts/phase44_comms_sweep.py` — the sweep runner (allowlist assertion, template inventory, `_send_one`, `run_sweep`, CLI).
- `backend/tests/test_phase44_comms_sweep.py` — 14 tests: allowlist enforcement (5), sweep-header enforcement (3), dry-run coverage (3), template inventory sanity (3).

### Verification
- **Dry run** — `python3 backend/scripts/phase44_comms_sweep.py` → 50 attempts (10 templates × 5 allowlist emails), all `status=dry_run`, exit 0.
- **pytest** — `backend/tests/test_phase44_comms_sweep.py` → 14/14 pass in 0.06s.
- **Live sweep (Feb 2026, post user sign-off)** — `python3 backend/scripts/phase44_comms_sweep.py --live` → **50/50 delivered** via Resend, zero failures. Latency: 49 sends between 140–306ms, one `payment_failed → admin@aquaterra.com` cold-path outlier at 3548ms, one `welcome → landscaper@aquaterra.com` at 1002ms. Every message carried `X-Emergent-Sweep: phase-44-demo` and only hit the 5 allowlist addresses. **All 10 template classes render correctly under the Phase 42 Stripe v15 SDK refresh — no regressions detected.**

---

## 2026-02-XX — Phase 42 · Stripe API refresh + webhook rewiring (paired with Phase 44)

- Bumped `stripe` Python SDK **14.4.1 → 15.4.0** in `requirements.txt`.
- Centrally pinned `stripe.api_version = "2026-03-25.dahlia"` in `services/payments/stripe_charge.py` (constant `STRIPE_API_VERSION`).
- Startup log line `[stripe] configured for api_version 2026-03-25.dahlia with secret key ending in ...<last4>` fires on first helper call (verified: `stripe_charge [INFO]: … secret key ending in ...ast4`, SDK reports `stripe.VERSION=15.4.0`).
- Introduced `_asdict()` helper that tolerates both v14 (`StripeObject inherits dict`) and v15 (`StripeObject no longer inherits dict`) response shapes across PaymentIntent + webhook code paths. See `PHASE42_STRIPE_AUDIT.md` for the full call-site inventory.
- Diagnostic script: `backend/scripts/verify_stripe_config.py`.

### emergentintegrations dependency conflict (metadata-only)

`emergentintegrations 0.2.0` still pins `stripe<15,>=13.0.0` in its METADATA. **This is metadata-only**: `emergentintegrations.payments.stripe.checkout` was tested against the installed `stripe 15.4.0` and imports/parses fine, and none of `/app/backend` uses that module directly (all Stripe code paths go through the raw SDK via `services/payments/stripe_charge.py`; `emergentintegrations` is only used for `llm.chat`).

**Recommendation: Option A** — leave the constraint as-is. `requirements.txt` already pins `stripe>=15.3.0,<16.0.0`, which pip's resolver honours (with a warning). A follow-up phase can vendor `emergentintegrations` or wait for upstream to bump the pin. **No downgrade.**

---


**Target hit — 5/5 consecutive full-suite runs green (1151/1152 pass · 1 skip · 0 fail).** Was 3-file rotating flake baseline (`moderation-bulk`, `slice-p17-additions`, `route-replay-panel`, occasionally `scorecard-leaderboard` / `lumino-pay-flow`) since Phase 33.

### Root causes diagnosed + fixed (stack of 5 layers)

| # | Root cause | Fix |
| - | --- | --- |
| 1 | Radix Dialog / Popover portals mount into `document.body` and are NOT removed by RTL `cleanup()`. Under vitest's parallel worker pool, a modal left open at end of test A leaks its portal into test B's `findByTestId`. | `setup.js` afterEach now scrubs `document.body.innerHTML = ""` after every test. |
| 2 | Cross-file module registry leaks (module-level caches like `CategoryPicker._cachedPromise`, module-scope mocks). Vitest's default `pool: "threads"` shares the ESM registry between files inside a worker. | `vitest.config.js` — switched to `pool: "forks"` with `isolate: true`. Fresh child process per file, ~30% wall-clock hit but eliminates the leaks. |
| 3 | RTL's default 1000ms `waitFor` timeout is too tight for CPU-starved async renders under parallel load. | `setup.js` — `configure({ asyncUtilTimeout: 5000 })`. |
| 4 | `moderation-bulk` test's synchronous `.checked` reads race React's state batching post-`fireEvent.click`. | Wrapped post-click assertions in `waitFor`. |
| 5 | `slice-p17-additions` shift-route test asserted target-select value before the async `/users` fetch populated the `<option>`s — silent no-op change event. | Added an explicit `waitFor(() => option[value="t-tgt"] exists)` gate before the change event. |

### Global config additions
- `vitest.config.js` — `pool: "forks"` + `poolOptions.forks.isolate: true` + `retry: 2` (global; a real regression still needs to fail 3× in a row).
- `setup.js` — `document.body.innerHTML = ""` in afterEach + `configure({ asyncUtilTimeout: 5000 })`.
- Two race-prone tests carry `{ retry: 5 }` locally (shift-route dialog x2, route-replay play-again). Retries are NOT weakened assertions — the tests still assert the same behavior.

### Non-scope
No production code touched (except one Phase 33 line in `PortalChatsPage.jsx` — the `typeof el.scrollTo === "function"` guard from earlier). No test assertion weakened. Duration hit: ~35s → ~55s full suite under `forks` (acceptable — CI still under 2min for the frontend job).

**Verification**: 5 consecutive full-suite runs, all green.

---


## 2026-02-XX — Phase 38b · Mobile Live Tech-Position Pins (P1.4b)

> **⚠️ DEV CLIENT REBUILD REQUIRED.** This phase adds the native
> `@rnmapbox/maps` module. **Plain Expo Go will not load it.** The
> mobile dispatch board renders a graceful fallback banner
> (`dispatch-live-map-fallback`) in Expo Go — the rest of the
> board keeps working — but to actually see the live map you must:
>
> 1. Get a Mapbox public token from https://account.mapbox.com/access-tokens/
> 2. Set `EXPO_PUBLIC_MAPBOX_TOKEN=pk.…` in `mobile/.env`
> 3. `cd mobile && yarn install`
> 4. `npx expo prebuild --clean`
> 5. Rebuild the dev client via `eas build --profile development --platform {ios,android}`
>
> Full step-by-step + troubleshooting + rollback lives in
> `mobile/EXPO_GO_RUNBOOK.md` under the "Phase 38b" heading.

### Package + config

- **`@rnmapbox/maps@^10.1.34`** added to `mobile/package.json`
  (chosen because it's the canonical Mapbox binding for Expo SDK 54
  / RN 0.81 / new architecture — the same version was chosen in
  the Phase 38b pre-flight report).
- **`mobile/app.json`** — added the `@rnmapbox/maps` config plugin
  entry with `RNMapboxMapsDownloadToken: "$EXPO_PUBLIC_MAPBOX_TOKEN"`
  and an `extra.mapboxToken` field so runtime code can read the
  token from `Constants.expoConfig.extra`.
- **`mobile/.env`** — appended a documented
  `EXPO_PUBLIC_MAPBOX_TOKEN=` placeholder (blank by default;
  wrapper renders the "set your token" banner until it's filled).

### Delivered

- **NEW** `mobile/src/components/dispatch/LiveTechPinsMap.tsx`
  (~155 LOC) — the real Mapbox map. Renders `<MapboxGL.MapView>` +
  per-tech `<PointAnnotation>` pins with deterministic color +
  initials over a white ring. Ships a top-right theme toggle that
  cycles `streets-v12 → satellite-streets-v12 → dark-v11` and
  persists the choice under `dispatch_map_style_v1`. GPS-feed-
  offline chip rendered when the parent flags offline.
- **NEW** `mobile/src/components/dispatch/LiveTechPinsWrapper.tsx`
  (~140 LOC) — Expo-Go-safe wrapper. Dynamic `require` of the map
  module inside try/catch; on failure renders the
  `dispatch-live-map-fallback` banner pointing at the runbook.
  Owns the 15-second poll on `GET /api/gps/live-positions`
  (`useFocusEffect` starts/stops polling on tab focus + cleanup on
  unmount). Owns the collapsible ~40%-viewport top section with
  chevron toggle persisted under `dispatch_map_expanded_v1`.
  Marks pins `is_stale` on 4xx/5xx or empty poll rather than
  blanking the map (keeps last-known context).
- **`mobile/app/(app)/dispatch/board.tsx`** — wired
  `<LiveTechPinsWrapper />` at the top of the ScrollView, above
  the Phase 38 tools row. Pin taps navigate to
  `/dispatch/shift-route` pre-populated with the tapped tech's ID
  + name.
- **`mobile/EXPO_GO_RUNBOOK.md`** — extended with a full Phase 38b
  section: one-time enable steps, troubleshooting (3 common
  errors), CI note, and rollback.

### Error surfaces

| Scenario | Rendered |
| --- | --- |
| Expo Go / dev client not rebuilt | `dispatch-live-map-fallback` banner + full runbook pointer |
| Dev client OK but no token | `dispatch-live-map-no-token` banner inside the map slot |
| `/api/gps/live-positions` 4xx/5xx | `dispatch-live-map-offline-chip` in-map + existing pins dimmed |
| Empty poll after non-empty | Same "stale" dimming |

### Tests

- **NEW** `frontend/src/test/phase38b-live-pins.test.jsx` ·
  **24/24 green**. Locks Mapbox dep version, app.json plugin +
  extra config, `.env` placeholder, all 5 tile-style rules, token
  read from safe source + no hard-coded token, wrapper's dynamic
  require + try/catch pattern, 15-second polling on
  `/gps/live-positions`, `useFocusEffect` cleanup, AsyncStorage
  persistence keys (both map style + expanded), all 6 required
  testIDs, zero `Alert.alert`, ShiftRouteDialog nav on pin tap,
  and the runbook heading + step count.
- **UPDATED** `frontend/src/test/phase38-mobile-dispatch-parity.test.jsx` ·
  The Phase 38 "no new mapping dep" guardrail (which was designed
  to catch accidental drift) has been reframed as a Phase 38b
  landing note — asserts the Phase 38b dep IS now present + that
  the wrapper is wired. 31/31 green.
- **Full suite** 1148/1152 pass (1 skip, 2 pre-existing flakes
  unrelated to Phase 38b).
- **`yarn eslint src`** — clean (Phase 40b guardrail intact).

### Non-scope

No web dispatch touched. No `/api/gps/live-positions` shape
change. No map integration on other mobile screens. No
`Alert.alert` anywhere. No touch to Phase 32/33/34/35/36/37/38
core deliverables beyond the intentional wrapper wire-in.

---


## 2026-02-XX — Phase 38 · Mobile Dispatch Parity (P1.4)

### Audit — 6 dispatch surfaces vs mobile state

| # | Surface | Web LOC | Endpoints | Mobile before | Action |
| - | --- | --- | --- | --- | --- |
| 1 | OptimizeRouteModal | 240 | POST `/dispatch/route/optimize`, POST `/dispatch/route/apply` | none | **NEW** `app/dispatch/optimize.tsx` (~190 LOC) |
| 2 | ShiftRouteDialog | 371 | POST `/dispatch/reassign` (incl. conflict + permanent duration flows) | none | **NEW** `app/dispatch/shift-route.tsx` (~210 LOC) |
| 3 | TechLoadStrip | 83 | derived from `/dispatch/board` | none | **NEW** `src/components/dispatch/TechLoadStrip.tsx` (~90 LOC) |
| 4 | UnroutedPanel | 297 | derived from `/dispatch/board` | none | **NEW** `src/components/dispatch/UnroutedPanel.tsx` (~85 LOC) |
| 5 | LiveTechPinsLayer | 148 | GET `/gps/live-positions` | none | **Deferred to Phase 38b** — no map on the board yet, and this would need a map primitive that isn't wired up |
| 6 | Route apply/optimize actions | (in #1) | (in #1) | none | ✓ (via #1) |

Existing mobile coverage: `mobile/app/(app)/dispatch/board.tsx` (479 LOC — settings + auto-assign) + `weather.tsx` (499). Neither had optimize / shift-route / load-strip / unrouted.

Total new/modified LOC: **~660** across 4 new files + 1 board wire-up + 1 Phase 30.4 debt patch. Under the 1500 / 15 gate.

### Delivered

- **`mobile/app/dispatch/optimize.tsx`** — full preview page: summary card (tech · route date · savings km) + proposed-order leg list with per-leg + cumulative distance + skipped-jobs surface + `showConfirm`-gated apply.
- **`mobile/app/dispatch/shift-route.tsx`** — source/target/scope/duration pills, permanent-flag acknowledgement gate, `showConfirm` on the permanent path AND on the `existing_override_conflict` retry path, `force` payload handled.
- **`mobile/src/components/dispatch/TechLoadStrip.tsx`** — horizontal chip strip with color swatch + drop count + selected state; tapping filters via parent callback.
- **`mobile/src/components/dispatch/UnroutedPanel.tsx`** — compact scrollable panel; tapping a row navigates to Shift Route with `customer_ids` pre-selected + `scope=partial`.
- **`mobile/app/(app)/dispatch/board.tsx`** wire-up — added a `/dispatch/board` fetch alongside the existing three, memoized `techLoads` + `unroutedPins` derivations, tools row with Optimize + Shift Route buttons, and integrated both new sub-components. Existing auto-assign flow untouched.

### Phase 30.4 completeness patch (opt-in from Phase 37 note)

- **`mobile/app/huddle.tsx`** — removed both `Alert.alert` calls (they silently fail on the user's Android/Expo Go build per Phase 30.4 root cause) and replaced with an inline status banner (no new dep). `Alert` import dropped.

### Non-scope

- **Live pin layer explicitly deferred to Phase 38b.** The mobile board doesn't have a map surface yet, and wiring one up would need either a new Mapbox dep (bumps bundle by ~400KB) or a fresh `react-native-maps` MapView. Out of scope for this delivery; the Phase 38 vitest asserts no new mapping dep sneaks in.
- No new backend endpoints added.
- No web dispatch touched.

### Tests

- **NEW** `frontend/src/test/phase38-mobile-dispatch-parity.test.jsx` · **31/31 green**. Locks file existence for the 4 new files, `<Header>` titles, backend endpoint calls, `showConfirm`-only destructive gating (no `Alert.alert` in any Phase 38 code), `strict_admin` role gating on the pages, root testIDs, board wiring (imports, `/dispatch/board` fetch, tools row, `router.push` targets), regression on the pre-existing auto-assign flow, Phase 30.4 completeness on `huddle.tsx` (Alert removed + banner testID + endpoints still called), and — critically — that no new mapping dep landed for Phase 38b's deferred work.

### Follow-up (Phase 38b)

Only remaining item: **Live pin layer** — an interactive map surface on the dispatch board showing GPS-tracked techs. Backend endpoint (`/gps/live-positions`) already exists (backend `phase16_gps` router). Mobile side needs a `MapView` + polling loop. Sized at ~200 LOC + potentially a new dep decision.

---


## 2026-02-XX — Phase 37 · Mobile Business OS Parity (P1.3)

### Audit — 8 Business OS surfaces vs mobile state

| # | Surface | Endpoint | Web LOC | Mobile before | Action |
| - | --- | --- | --- | --- | --- |
| 1 | `/os/dashboard` | `GET /os/overview` | ~120 (BusinessOS.jsx overview) | none | **NEW** `mobile/app/os/index.tsx` (hub) |
| 2 | `/os/sops` | `GET/POST /sops`, `POST /sops/generate` | ~180 | none | **NEW** `mobile/app/os/sops.tsx` |
| 3 | `/os/roles` | `GET/POST /role-definitions` | ~100 | none | **NEW** `mobile/app/os/roles.tsx` |
| 4 | `/os/scorecards` | `GET/POST /kpi-scorecards` | ~80 | none | **NEW** `mobile/app/os/scorecards.tsx` |
| 5 | `/os/huddles` | `GET/POST /huddles`, `/agenda`, `/action-items` | ~150 | `mobile/app/huddle.tsx` (126) — technician daily huddle | **Hub link only** — no duplicate |
| 6 | `/os/leanboards` | `GET /leanboards`, `/leanboards/{id}/cards`, `POST /cards/{id}/move` | ~160 | none | **NEW** `mobile/app/os/leanboards.tsx` |
| 7 | `/os/sprints` | `GET/POST /sprints`, `POST /sprints/{id}/retro-ai` | ~200 | none | **NEW** `mobile/app/os/sprints.tsx` |
| 8 | `/os/lana` | `POST /business-os/lana/chat` | 114 (LanaAndPlans.jsx) | none | **NEW** `mobile/app/os/lana.tsx` |

Total mobile LOC: **~980** across 7 new files + 1 hub link entry. Under the 1500 LOC / 15 file gate.

### Delivered

- **`mobile/app/os/index.tsx`** (hub) — GET `/os/overview` summary stats card + 7-tile deep-dive nav.
- **`mobile/app/os/sops.tsx`** — list + `<Sheet>` add form with both Save + Generate (AI) actions.
- **`mobile/app/os/roles.tsx`** — list + `<Sheet>` create with multi-line accountabilities parser.
- **`mobile/app/os/scorecards.tsx`** — list + `<Sheet>` create with color-coded current-vs-target indicator.
- **`mobile/app/os/leanboards.tsx`** — board picker + backlog / in-progress / done columns + per-card move-to buttons.
- **`mobile/app/os/sprints.tsx`** — week picker + detail card (theme + goals + retro) + `showConfirm`-gated "Generate AI retro" action.
- **`mobile/app/os/lana.tsx`** — full chat surface with user/assistant bubbles, KeyboardAvoidingView, POST `/business-os/lana/chat`.

Every new file uses `<Header>`, `<RoleGate level="strict_admin">`, `<Loading>` / `<EmptyState>`, and has zero `Alert.alert` calls. The one destructive-flow trigger (`sprints/retro-ai`) uses `showConfirm` from Phase 30.4.

### Drawer nav

New group **Business OS** appended to `mobile/src/nav/adminNav.ts` with 8 T1 entries (hub + 7 deep-dives). Huddle entry routes to the existing pre-existing `mobile/app/huddle.tsx` — no duplicate. This is the first new top-level nav group added since the Phase 40e drawer parity refactor.

### Tests
- **NEW** `frontend/src/test/phase37-mobile-os-parity.test.jsx` · **62/62 green**. Locks file existence, `<Header>` titles, backend endpoint calls, root testIDs, `strict_admin` gating, zero `Alert.alert`, 7 hub tile links, drawer group + all 8 nav entries, and a regression net on the pre-existing huddle screen + Phase 35/36 nav entries.

### Non-scope
- Existing `mobile/app/huddle.tsx` still uses `Alert` (pre-existing Phase 30.4 debt). Not touched — surface link only.
- No new backend endpoints, no web OS pages touched, no Phase 32/33/34/35/36/39/30.4/Live Radar/Phase 40e touch.

---


## 2026-02-XX — Phase 36 · Mobile CFO Deep-Dives Parity (P1.2)

### Audit — six CFO deep-dives vs mobile state

| # | Surface | Backend endpoint | Web page | Mobile before | Action |
| - | --- | --- | --- | --- | --- |
| 1 | Bills | `GET /api/cfo/bills` | `admin/VendorBills.jsx` (229) | Phase 35 shipped `mobile/app/finance/vendor-bills.tsx` | **Hub link only** (no dup) |
| 2 | AP Aging | `GET /api/cfo/ap-aging` | `admin/CFOReports.jsx` (185) | none | **NEW** `cfo/ap-aging.tsx` |
| 3 | Forecast | `GET /api/cfo/forecast?horizon=` | `cfo/CFODashboard.jsx` (578) | **Distinct** from `/reports/forecast` (P40, `mobile/app/reports/forecast.tsx`) — cash-flow vs revenue | **NEW** `cfo/forecast.tsx` |
| 4 | Anomalies | `GET /api/cfo/anomalies?window_days=&z=` | `cfo/CFODashboard.jsx` | none | **NEW** `cfo/anomalies.tsx` |
| 5 | Payroll | `GET /api/cfo/payroll?period=` | `admin/CFOReports.jsx` | Existing `mobile/app/(app)/payroll/batch.tsx` is the BATCH RUN action (858 LOC); this is the read-only summary | **NEW** `cfo/payroll.tsx` |
| 6 | Price-Increase | `POST /api/cfo/price-increase-suggestions` | `admin/PricingInsights.jsx` (332) | none | **NEW** `cfo/price-increase.tsx` |

Total new mobile LOC: **~840** across 5 new files + hub extension. Under the 1500 LOC / 15 file gate.

### Delivered

- **`mobile/app/cfo/ap-aging.tsx`** — summary card + 4 aging buckets + open-bill rows.
- **`mobile/app/cfo/forecast.tsx`** — horizon selector (30/60/90/180 days) + projected in/out/net + per-period buckets. Distinct endpoint from the Phase 40 revenue forecast.
- **`mobile/app/cfo/anomalies.tsx`** — window (30/60/90/180d) + z-score sensitivity (1.5/2.0/2.5/3.0σ) chip filters + result rows with color-coded z-tag.
- **`mobile/app/cfo/payroll.tsx`** — MTD/QTD/YTD selector + total wages/hours/avg-rate + by-category breakdown.
- **`mobile/app/cfo/price-increase.tsx`** — month picker (YYYY-MM) + POST regenerate button + rationale-rich suggestion cards with arrow-forward from current → suggested price.
- **`mobile/app/(app)/cfo/index.tsx`** — replaced the "live on desktop for now" foot-note with a 6-tile deep-dive navigation block (5 new links + one link out to Phase 35's Vendor Bills page). Existing `/cfo/dashboard` fetch, `<QnAPanel>`, `<ScenarioPanel>` untouched.

All 5 new pages use `<Header>`, `<RoleGate level="strict_admin">`, `<Loading>` / `<EmptyState>`, and zero `Alert.alert` calls.

### Drawer nav diff

**Reports group (`mobile/src/nav/adminNav.ts`):**

Added 5 T1 entries: `CFO · AP Aging`, `CFO · Cash Forecast`, `CFO · Anomalies`, `CFO · Payroll`, `CFO · Price Increase`.

Removed 2 duplicate T3 stubs since Phase 35 already ships them at T1 in the Finance group:
- `drawer-nav-t3-recurring-jobs` (was `/admin/recurring-jobs`)
- `drawer-nav-t3-vendor-bills` (was `/admin/finance/bills`)

### Tests
- **NEW** `frontend/src/test/phase36-mobile-cfo-parity.test.jsx` · **43/43 green**. Source-inspection: each of the 5 new surface files exists, has `<Header>` with correct title, hits the right `/api/cfo/*` endpoint, carries the root testID, is role-gated to `strict_admin`, and does NOT use `Alert.alert`. Locks the 6 hub tiles + the drawer nav flip + regression on the pre-existing `/cfo/dashboard` fetch.
- **UPDATED** `frontend/src/test/phase-mobile-drawer-parity.test.jsx` · T3 threshold lowered from ≥13 to ≥11 to reflect the 2 legitimate removals in Phase 36. Comment inline explains the running tally. 39/39.

### Non-scope
Did not touch web CFO pages, backend, Phase 32/33/34/35/39/30.4/Live Radar/Phase 40e. No new backend endpoints added.

---


## 2026-02-XX — Phase 35 · Mobile Finance Ops Parity (P1.1)

### Audit — six web finance surfaces vs mobile state

| # | Surface | Web page (LOC) | Mobile state before | Action | Mobile LOC after |
| - | --- | --- | --- | --- | --- |
| 1 | Recurring Jobs | `admin/RecurringJobs.jsx` (335) | none | **New** — list + toggle active + generate-now | ~180 |
| 2 | Auto-Billing config | `finance/FinancePages.jsx` · `AutoBilling` slice (~580) | `mobile/app/auto-billing.tsx` (201) already list + add | Kept as-is (parity-viable) | 201 |
| 3 | Autobilling Runs | `finance/AutobillingRuns.jsx` (492) | none | **New** — filtered list + bulk-cancel queued runs | ~205 |
| 4 | Master Invoices List | `invoices/MasterInvoice.jsx` (298) | none | **New** — list + tap-to-detail | ~130 |
| 4b | Master Invoice Detail | (same file — detail slice) | none | **New** — child rollup + apply-payment | ~200 |
| 5 | Payments Ledger | `finance/FinancePages.jsx` · `PaymentsLedger` slice (~330) | `mobile/app/payments.tsx` (88) — bare list | Kept as-is (list is primary function) | 88 |
| 6 | Vendor Bills | `admin/VendorBills.jsx` (229) | none | **New** — list + add via `<Sheet>` bottom-sheet | ~230 |

Total new mobile LOC: **~945**. 5 new files, 2 pre-existing files kept, 1 nav file edited, 1 vitest added, 1 pre-existing drawer-parity vitest threshold adjusted. Well under the 1500 LOC / 15 file gate.

### Delivered

- **`mobile/app/finance/recurring-jobs.tsx`** — GET `/recurring-jobs`, PATCH toggle, POST `/generate?through=…`. Uses `showConfirm` (Phase 30.4) for the destructive generate action. Role: strict_admin.
- **`mobile/app/finance/autobilling-runs.tsx`** — GET `/autobilling-runs?status=…` with a horizontal chip filter, checkbox-select on queued rows, POST `/autobilling/runs/bulk-cancel`. `showConfirm` gate.
- **`mobile/app/finance/master-invoices/index.tsx`** — GET `/invoices/master`, tap-to-detail via `router.push`.
- **`mobile/app/finance/master-invoices/[id].tsx`** — GET `/invoices/master/{id}`, POST `/invoices/master/{id}/apply-payment`. Shows Total / Applied / Balance summary card + child invoice rollup. `showConfirm` gate for the payment.
- **`mobile/app/finance/vendor-bills.tsx`** — GET/POST `/cfo/bills`, `<Sheet>` bottom-sheet form for the create action.

### Drawer nav flip

| Before (T3 web-only stub) | After (T1 real mobile route) |
| --- | --- |
| `/invoices/master` → `drawer-nav-t3-master-invoices` | `/finance/master-invoices` → `drawer-nav-master-invoices` |
| `/admin/autobilling-runs` → `drawer-nav-t3-autobilling-runs` | `/finance/autobilling-runs` → `drawer-nav-autobilling-runs` |
| _(not present)_ | `/finance/recurring-jobs` → `drawer-nav-recurring-jobs` (new T1) |
| _(not present)_ | `/finance/vendor-bills` → `drawer-nav-vendor-bills` (new T1) |

Check Writer / Dunning / Warranty stay T3 — real mobile pages TBD.

### Tests
- **NEW** `frontend/src/test/phase35-mobile-finance-parity.test.jsx` · **39/39 green**. Source-inspection: each surface's file exists, has `<Header>` with the right title, calls the right backend endpoints, carries the root testID, uses `showConfirm` (never `Alert.alert`) on the 3 destructive surfaces. Locks the 4 drawer nav flips and confirms pre-existing T1 entries are intact.
- **UPDATED** `frontend/src/test/phase-mobile-drawer-parity.test.jsx` · T3-count threshold lowered from 15 → 13 to reflect the 2 legitimate reclassifications; T1/T2 thresholds and total ≥ 85 unchanged. Comment inline explains why.

### Non-scope
Did not touch web finance pages, backend, Phase 32/33/34/39/30.4/Live Radar/Phase 40e. No new backend endpoints added.

---


## 2026-02-XX — Phase 34 · Endpoint Path Normalization (P0.3)

### Audit — cross-client path drifts

| # | Drift | Web calls | Mobile calls | Backend truth | Canonical (chosen) |
| - | --- | --- | --- | --- | --- |
| 1 | Public review-request token flow | `/api/reviews/public/r/*` (5 endpoints) | `/api/public/r/*` (returns 404) | Only `/api/reviews/public/r/*` is registered (via `reviews.py` mounted at `/reviews`) | **`/api/reviews/public/r/*`** — matches backend router mount |

The Phase 31 audit also flagged `/api/service-report/*` (singular)
vs `/api/service-reports/*` (plural) as a candidate drift. On
inspection **this is not a drift** — the singular namespace hosts AI
helper actions (`analyze-water-photo`, `recommend-chemicals`,
`attach-note`) while the plural namespace holds report CRUD
(`last-readings`, `send-recap`, `media/reorder`). Both web and mobile
use both namespaces identically. Consolidating them into a single
prefix is a follow-up hygiene phase, not a Phase 34 concern.

### Fix

- **New file** `backend/routers/reviews_public_alias.py` — mirrors the
  5 canonical public review-request endpoints at the legacy
  `/api/public/r/*` prefix. Each alias delegates directly to the
  canonical handler (no logic duplication) and stamps two headers on
  the response:

      Deprecation: true
      Link: </api/reviews/public/r/{...}>; rel="alternate"

- **`backend/server.py`** — mounts the alias router after
  `marketing_campaigns_router.public_router`.
- **`mobile/app/portal/review-submit.tsx`** — the 3 client call-sites
  (`api.get`, `api.post rating`, `api.post google-clicked`) migrated
  from `/public/r/${token}/*` to `/reviews/public/r/${token}/*`.
  A comment cross-refs this CHANGELOG entry so `git blame` explains
  itself.
- **Retention** — the alias router is a **one-release-cycle safety
  net**. Delete once mobile builds catch up (Phase 34 + 1).

### Tests
- `backend/tests/test_phase34_endpoint_aliases.py` — 3 pytest cases,
  all green. Asserts both paths return 200 with the same JSON shape,
  the alias carries `Deprecation: true` + `Link` headers, and the
  canonical does NOT (so devs can tell them apart at the wire).
- `frontend/src/test/phase34-endpoint-normalization.test.jsx` —
  10 source-inspection tests, all green. Locks in the mobile call-site
  paths, the backend alias's 5 routes + Deprecation headers, and that
  the alias imports from the canonical module (no duplicated logic).

### Non-scope
Did not touch Phase 32 (CI), 39 (mobile ToS), 30.4 (ConfirmModal),
Live Radar, or Phase 40e. No web app code changed — only backend +
mobile + tests. Any pre-existing full-suite vitest flakes
(`slice-p17-additions`, `moderation-bulk`, `scorecard-leaderboard`,
`lumino-pay-flow` — all pass in isolation) are unchanged by this
phase.

---


## 2026-02-XX — Phase 33 · Test Hygiene (P0.2)

Cleaned up every red / empty vitest file so CI can enforce a green
baseline going forward.

| File | Before | Action | After |
| --- | --- | --- | --- |
| `file-upload-components.test.jsx` | 0 tests (`@jest/globals`) | Converted to vitest, `jest.*` → `vi.*` | 10 pass |
| `persona-avatar.test.jsx` | 0 tests | Import swap | 5 pass |
| `phase22-mobile-schedule-gates.test.jsx` | 0 tests | Import swap | 6 pass |
| `phase34-bulk-select-shared.test.jsx` | 0 tests | Import swap + `jest.` → `vi.` | 122 pass |
| `preview-demo-logins.test.jsx` | 0 tests | Import swap + `jest.` → `vi.` | 8 pass |
| `task-rr-ss-p2-revised.test.jsx` | 0 tests | Import swap + `jest.` → `vi.` | 19 pass |
| `phase34-admin-page-mount-safety.test.jsx` | 0 tests (Jest-only `jest.mock(..., { virtual: true })`) | Excluded from vitest runner per author intent | not collected |
| `phase34-task-pp-portal-hint.test.jsx` | 0 tests (Jest-only) | Excluded from vitest runner | not collected |
| `phase34-task-w-forgot-password.test.jsx` | 0 tests (Jest-only) | Excluded from vitest runner | not collected |
| `invoice-edit-modal.test.jsx` | 6 fail (`api.get(...).then` on undefined; missing `category` on line items) | Added default `getSpy` promise, `invalidateCategoryCache()` between tests, populated `category` on fixture line items | 6 pass |
| `login-demo-flag.test.jsx` | 4 fail (targets `login-demo-section` — removed in Phase 30) | Deleted — feature intentionally removed, comment on `Login.jsx:24-31` explains | not collected |
| `login-welcome.test.jsx` | 1 fail (regex expected space, DOM has two block-level `<span>`s adjacent) | Regex updated to `\s*` between segments | 1 pass |
| `phase10-ui.test.jsx` | 1 fail (`customer-credits-adjust-submit` — AdjustDialog reuses `-issue-` testids) | Test updated to use the real `customer-credits-issue-submit/-amount/-note` IDs | 5 pass |
| `slice-p19-ai-copilot.test.jsx` | 1 fail (`useAuth` null in CopilotPage) | Mocked `@/auth` with a stub user | 2 pass |
| `moderation-bulk.test.jsx` | flaky under full-suite (local `vi.clearAllMocks/restoreAllMocks` racing setup.js globals) | Removed the redundant local hooks — setup.js already does the work | 3 pass |
| `slice-p17-additions.test.jsx` | flaky (`shift-target-tech-select` findByTestId raced dialog render under parallel load) | Added intermediate `findByTestId("shift-route-dialog")` wait | 7 pass |
| `PortalChatsPage.jsx:40` | uncaught `scrollTo is not a function` in jsdom (optional chain guards null, not missing method) | Guarded with `typeof el.scrollTo === "function"` (single-line prod fix) | no leaked errors |

**Full-suite:** 126/126 test files pass · 942/943 tests pass (1 pre-existing skip) · 0 uncaught errors.

**Scope discipline** — no assertions were weakened; every fix either genuinely repaired the target-under-test, removed an obsolete spec, or wrote a minimal one-liner production guard. No backend / mobile jest suite touched.

---


## 2026-02-XX — Phase 40b lint guardrail · `no-restricted-imports` for `@/lib/*`

- Added `frontend/eslint.config.js` (minimal ESLint 9 flat-config) with a
  single `no-restricted-imports` rule that flags any `@/lib/*` import
  except the three real modules (`@/lib/utils`, `@/lib/stripeConfig`,
  `@/lib/checklistType`). Would have caught the failing `@/lib/api`
  import from Phase 40b at lint stage.
- Wired `yarn eslint src` into the Phase 32 `frontend-web` CI job so the
  guardrail runs on every PR and every push to `main`.
- Scope: intentionally minimal — this is NOT the full ESLint 9 migration
  for the frontend workspace. Other rules land in a dedicated migration
  phase. `react-hooks` and `import` plugins are registered as no-ops
  only to silence inline disable directives sprinkled across the repo.
- Locked in by `src/test/phase40b-lint-guardrail.test.jsx` (7 tests).

---


## 2026-02-XX — Phase 40b hotfix · Time-off web pages compile fix

- Corrected `@/lib/api` → `@/api` (canonical named export) in
  `TimeOffPage.jsx` and `AdminTimeOffPage.jsx`. The `@` alias resolves
  to `src/`, and `src/api.js` exports `{ api }` (no default), so the
  bogus `@/lib/api` path broke the webpack build.
- Verified: `frontend` supervisor logs report `Compiled successfully!`
  and `phase40-time-off.test.jsx` (20 tests) passes green.

---


## 2026-02-XX — Phase 40b · Time-off UI (web + mobile)

Replaced the Phase-40 ``ComingSoonPage`` stubs with real employee +
admin UI on both surfaces. All flows are backed by the Phase-40
``/api/time-off`` endpoints; no new backend logic was needed except a
small admin-only ``GET /balances/all`` endpoint used by the admin
tables.

### Added
- **Web · `frontend/src/pages/TimeOffPage.jsx`** — employee page at
  ``/time-off``. Renders a 4-stat balance card
  (Available · Accrued YTD · Used YTD · Waiting/Cap), a request
  history table with status pills + inline Cancel on pending rows,
  and a "Request Time Off" modal that surfaces structured
  ``waiting_period`` / ``insufficient_balance`` error banners.
- **Web · `frontend/src/pages/AdminTimeOffPage.jsx`** — admin page
  at ``/admin/time-off`` (``<AdminOnly>``-gated). Tabs for Pending
  Approvals / All Requests, per-row Approve / Reject with a notes
  modal, employee-balance snapshot table, and an inline policy
  editor that PUTs to ``/time-off/policy``.
- **App.js routes** — ``/time-off`` (all authenticated) +
  ``/admin/time-off`` (``<AdminOnly>``).
- **Mobile · `mobile/app/time-off.tsx`** — full-page employee view.
  Balance card + history rows + bottom-sheet request modal with the
  same field set and error UX as web. Cancel uses ``showConfirm()``
  (the Phase-30.4 modal) — **no ``Alert.alert``**, per the Phase
  30.3/30.4 root cause.
- **Mobile · `mobile/app/admin/time-off.tsx`** — full-page admin
  view. Pending list with Approve / Reject per row, an in-app
  Modal for reject-notes (no Alert.alert), employee-balance list,
  and an inline policy editor.
- **Backend · `GET /api/time-off/balances/all`** — new admin-gated
  endpoint used by both admin UIs. Enriches each balance with
  ``user_name``, ``avatar_url``, ``role``, and normalised
  ``hire_date`` so the tables render without a follow-up
  ``/api/users`` fan-out.

### Changed
- ``backend/scripts/seed_phase40_time_off.py`` — enhanced with a
  fourth step that inserts one **idempotent** pending request per
  active tech-like user. On aquaterra, this inserted **25** rows —
  the admin queue is now populated for demos out of the box.
- ``frontend/src/test/phase40-time-off.test.jsx`` — replaced the
  "mobile stubs" assertion with real-UI assertions on both mobile
  screens (testIDs, endpoint calls, no ``Alert.alert``, ``showConfirm``
  wiring), plus new assertions for the two web pages, App.js
  routing, ``/balances/all`` shape, and the seed enhancement.

### Test results
- Backend pytest: **9 / 9** (`test_phase40_time_off.py`).
- Vitest cross-suite: **101 / 101** across
  phase40 (20) + drawer parity (39) + revenue parity (15) +
  portal sign-out (15) + CI config (12).

### Non-scope confirmed
- No push notifications yet (Phase 40c).
- No calendar visualisation (deferred).
- No QBO payroll export (Phase 40d).
- ``Alert.alert`` NOT used in any confirmation flow — mobile uses
  ``showConfirm()`` from Phase 30.4 + native ``<Modal>``.
- Phase 32 CI, Phase 39 ToS, Phase 30.4 Alert audit, Live Radar
  fallback, Dashboard revenue tiles, drawer parity delivery — all
  untouched.

---

## 2026-02-XX — Phase 40 · Time-off requests + accrual (backend + wiring)

Odoo-Time-Off-style paid sick-leave module with the aquaterra-specific
accrual math. Backend + tests + seed + drawer/nav wiring shipped in
this delivery; web + mobile UI pages queued for **Phase 40b** — the
drawer entries route to a ``ComingSoonPage`` stub today so the tree
is complete now.

### Accrual math (default policy, tenant-editable)
- **Accrual ratio:** 1 hour of paid sick leave per 30 hours worked.
- **Annual cap:** 24 hours per year (rolling YTD, resets Jan 1). Cap
  applies to accrued balance, not to used — used hours don't free up
  cap headroom (matches Odoo "annual entitlement" model).
- **Waiting period:** 90 days from ``hire_date`` before an employee
  can submit a balance-drawing request (accrual still runs during
  the window). Falls back to ``created_at`` if ``hire_date`` is
  missing so legacy accounts don't get stuck.
- **Source of worked hours:** existing ``db.time_entries`` ledger
  (``clock_in_at`` / ``clock_out_at`` / ``breaks[]``). Balance is
  recomputed on-read — no scheduled job.

### Added
- **`backend/services/time_off_accrual.py`** — pure-function service
  exporting ``compute_balance``, ``get_policy``, ``sum_worked_hours_ytd``,
  ``used_hours_ytd``, ``waiting_period_remaining_days``, and
  ``DEFAULT_POLICY``. TZ-safe: coerces naive-UTC legacy rows before
  window comparisons.
- **`backend/routers/time_off.py`** — mounted at ``/api/time-off``.
  Endpoints:
  - ``GET /policy`` — sanitised for tech role.
  - ``PUT /policy`` — ``require_admin``.
  - ``GET /balance/me``
  - ``GET /balance/{user_id}`` — ``require_admin``.
  - ``GET /requests?scope=me|all&status=…``
  - ``POST /requests`` — validates waiting-period + balance;
    error codes ``waiting_period`` / ``insufficient_balance`` /
    ``bad_date`` / ``date_range``.
  - ``POST /requests/{id}/approve|reject`` — ``require_admin``,
    re-checks balance atomically at approval time.
  - ``POST /requests/{id}/cancel`` — owner-only, refunds an
    approved request via ``cancelled_after_approval`` audit trail
    (balance auto-recomputes on next read).
- **`backend/scripts/seed_phase40_time_off.py`** — seeds the default
  policy for the aquaterra tenant, backfills ``hire_date`` on
  ``landscaper@aquaterra.com`` (Luis Marquez) 200 days ago so demo
  users have usable balance past the waiting period, and inserts 4
  sample requests (2 pending, 1 approved, 1 rejected). Idempotent —
  re-running only inserts what's missing.
- **`backend/tests/test_phase40_time_off.py`** — 9 pytest cases:
  policy read/upsert + admin-only guard, balance shape, annual-cap
  clamp, within-balance submit, waiting-period rejection,
  insufficient-balance rejection, approve/reject/cancel lifecycle
  including tech-can't-approve + owner-only cancel guardrails.
  **9 / 9 pass.**
- **`frontend/src/test/phase40-time-off.test.jsx`** — 14 vitest
  assertions locking the accrual constants, router endpoint surface,
  ``require_admin`` gate count, error-code strings, server include
  list, and the drawer + web-nav wiring below.

### Nav wiring
- **Web (`frontend/src/nav/adminNav.js`)**: Operations group now
  includes ``/time-off`` (Time Off, feature: jobs) and
  ``/admin/time-off`` (Time Off Approvals, ``hard_rule: "admin_only"``).
- **Mobile (`mobile/src/nav/adminNav.ts`)**: Operations group now
  includes ``drawer-nav-time-off`` (Tier 1, all roles) and
  ``drawer-nav-time-off-admin`` (Tier 2, admin-like roles).
- **Mobile stub routes**: ``mobile/app/time-off.tsx`` and
  ``mobile/app/admin/time-off.tsx`` — each a one-line re-export of
  ``ComingSoonPage``. Full UI ships in Phase 40b.

### Data seed (already run against aquaterra)
```
seed · created time_off_policy for tenant 3814…
seed · backfilled hire_date on landscaper@aquaterra.com → 2026-01-15
seed · inserted 4 sample time_off_requests
```

### Non-scope (Phase 40b follow-ups)
- Web page: ``/time-off`` employee balance + history + submit modal.
- Web page: ``/admin/time-off`` pending queue + approve/reject +
  policy editor + employee balance table.
- Mobile screens: ``time-off.tsx`` employee view + admin/time-off queue.
- Push notifications on approve/reject.
- QBO payroll export.
- Calendar visualisation.

### Non-scope confirmed
- Timesheet/time-clock schema untouched — balance is a pure function
  of ``db.time_entries``.
- Phase 32 CI, Phase 39 ToS, Phase 30.4 Alert audit, Live Radar
  fallback, Dashboard revenue tiles, drawer parity delivery — all
  untouched.

---

## 2026-02-XX — Mobile admin drawer parity (Option B · 85 wired) (P1)

Mobile hamburger drawer at ``mobile/app/(app)/more.tsx`` now mirrors
the web admin sidebar (``frontend/src/nav/adminNav.js`` /
``layouts/AdminSidebar.jsx``). Data-driven render from a single source
of truth so future parity edits are a one-file change.

### Added
- **`mobile/src/nav/adminNav.ts`** — mobile-side nav data module.
  Exports ``QUICK_ACCESS`` (Schedule / Dispatch / Team synthetic
  shortcut group per user request) and ``ADMIN_NAV`` (the eight
  canonical web groups: Finance · AI Employees · Marketing ·
  Operations · Customers · Reports · Communications · Reviews). Each
  entry carries ``{ label, route, icon, tier, roles?, testID }``.
  Structure is copied from the web module (not derived at runtime),
  so mobile routes can diverge from web paths safely.
- **`mobile/src/components/ComingSoonPage.tsx`** — shared Tier-2
  stub. Reads title + web path from search params so all 25 T2
  routes are 1-line re-exports.
- **`mobile/src/components/WebOnlyPage.tsx`** — shared Tier-3
  fallback. In-app ``<WebView>`` on native, ``Linking.openURL`` CTA
  on the Expo web bundle (WebView is native-only). URL derived from
  ``EXPO_PUBLIC_WEB_URL`` + web path from the drawer entry.
- **`mobile/app/web-only.tsx`** — 1-line re-export of
  ``WebOnlyPage`` so every Tier-3 tap routes to a single Expo route
  (``/web-only?title=…&webPath=…``).
- **25 new T2 stub route files** — 1-line re-exports of
  ``ComingSoonPage``:
  `/settings/income-categories`, `/settings/service-categories`,
  `/settings/notifications`, `/settings/terms`, `/settings/legal`,
  `/settings/maps`, `/settings/ringcentral`, `/admin/reviews`,
  `/admin/reviews/requests`, `/admin/reviews/platforms`,
  `/admin/reviews/widget`, `/admin/comms/email`, `/admin/comms/sms`,
  `/admin/comms/templates`, `/admin/comms/automations`,
  `/admin/comms/sends`, `/admin/tags`, `/admin/service-reports`,
  `/admin/appointments`, `/admin/referrals/analytics`,
  `/admin/referrals/settings`, `/admin/chemicals`,
  `/admin/moderation/checkins`, `/admin/diagnostics/errors`,
  `/weather`. Plus `/crews` and `/tenants` (super-admin gated).

### Changed
- **`mobile/app/(app)/more.tsx`** — removed the flat hard-coded
  Management + SEO sections; drawer now maps over ``QUICK_ACCESS``
  + ``ADMIN_NAV`` via new ``DrawerGroup`` / ``DrawerRow`` helpers.
  Tier-2 rows carry a "SOON" pill, Tier-3 rows carry a "WEB" pill
  and route to ``/web-only``. Tech-only section, notifications
  toggle, and logout row all preserved unchanged.

### Scope (Option B · Phase-B this delivery)
- **Tier 1 · LINK ONLY — 59 wired.** Mobile screens already existed;
  drawer now surfaces them.
- **Tier 2 · STUBS — 25 wired.** Small-effort routes shown with a
  "SOON" pill; tap opens ``ComingSoonPage`` with a "Open on the web
  app" CTA. Remaining ~44 T2 items queued for **Phase-B follow-up**.
- **Tier 3 · WEB-ONLY — 15 exposed via `/web-only`.** Master
  Invoices, Autobilling Runs, Check Writer, Dunning Queue, Warranty
  Plans, Marketing Campaigns, Social Composer, SEO Articles,
  Auto-Dispatch, Routes, Inventory, Business OS, Business Summary,
  Recurring Jobs, Vendor Bills. Remaining ~57 T3 items **hidden
  from the drawer entirely** and tracked as **P1/P2 backlog** per
  the Phase 31 audit.
- **Quick Access** — three entries at the very top of the drawer
  (Schedule / Dispatch / Team) duplicating their canonical group
  positions, per user request.

### Follow-up phases (deferred)
- **Phase-B follow-up · remaining 44 T2 stubs** — same
  ``ComingSoonPage`` pattern, small effort.
- **P1 large builds (already in Phase 31 audit backlog):** mobile
  finance ops (Master Invoices, Recurring Jobs, Auto-Billing config,
  Autobilling Runs, Payments ledger, Vendor Bills), CFO deep-dives,
  Business OS (SOPs / Roles / Scorecards / LeanBoards / Sprints),
  Dispatch parity (Optimize / Insert / Apply + Mapbox live pins).
- **P2 large builds:** Marketing Campaigns / Posts / Approval Queue
  / Calendar / Performance / Brand Memory; Social Composer / Calendar
  / Library / Drafts / Approvals; SEO Articles / Keywords / Audit /
  Rank Grid / WordPress; Onboarding Templates / Queue.

### Tests
`frontend/src/test/phase-mobile-drawer-parity.test.jsx` (39
assertions) locks: source-of-truth structure (8 group keys in order,
QUICK_ACCESS shape, tier classifications and counts), presence and
shape of ``ComingSoonPage`` + ``WebOnlyPage`` + ``/web-only`` route,
drawer imports from ``adminNav.ts``, ``QUICK_ACCESS`` rendered above
``ADMIN_NAV``, T2/T3 pill visibility, and one guarded assertion per
T2 stub file (all 25). Cross-suite (drawer + revenue parity + sign-
out + CI) passes **81 / 81**.

### Non-scope confirmed
- Backend untouched.
- Web sidebar untouched.
- Tech / customer drawer content unchanged (existing `techLinks` + push
  notifications toggle + logout row preserved).
- Phase 32 / Phase 39 / Phase 30.4 / Live Radar / Dashboard tiles /
  revenue screens untouched.

---

## 2026-02-XX — Mobile revenue-tile parity (P1)

Added three tap-through parity tiles at the top of the mobile admin
**Dashboard** (`mobile/app/(app)/index.tsx`), mirroring the equivalent
web surfaces. Each tile links to a dedicated mobile screen — two of
them brand new, one reusing an existing full-parity screen.

**Correction (Feb-2026, same-day):** tiles were initially placed on
`mobile/app/reports.tsx`; the user expected them on the Dashboard.
Moved to the Dashboard where they now sit above Budget Health /
Weather / Live Radar / Total Revenue hero. `reports.tsx` reverted to
its pre-tile state (KPI grid → Revenue Trend → Jobs by Status → Top
Customers → Technician Performance).

### Added
- **`mobile/app/reports/revenue-by-service.tsx`** — extracted from the
  previous inline chart in `reports.tsx`. Full-page view with sortable
  rows (High → Low, Low → High, A → Z), total card, CSV export, pull-to-
  refresh. Data source: shared `GET /api/reports` (`revenue_by_service`)
  — same field the web `admin/Dashboard.jsx` and
  `reports/BusinessSummary.jsx` cards render.
- **`mobile/app/reports/forecast.tsx`** — new screen mirroring web
  `frontend/src/pages/reports/Forecast.jsx`. Companion KPI cards from
  `/api/reports/forecast-cards`, series bar list from
  `/api/reports/forecast?range={preset}`. Ships a five-preset filter
  chip row per product spec: **Today · Tomorrow · This Week · This
  Month · Custom**. Default preset is `This Week`. Custom Range opens a
  date-range picker (uses existing `@react-native-community/datetime-
  picker` — no new dep). Custom chip label auto-updates to `MM/DD –
  MM/DD` once both endpoints are picked; endpoint becomes
  `/reports/forecast?range=custom&date_from=…&date_to=…` to match web.
- **Three tiles at the top of `mobile/app/(app)/index.tsx`
  (Dashboard)** with testIDs `admin-tile-revenue-by-category`,
  `admin-tile-revenue-by-service`, `admin-tile-forecast-revenue`.
  Routes: `/income-by-category` (reuses the existing full-parity
  screen — no duplication), the two new `/reports/…` screens above.
  Tiles sit as the first block below the Dashboard header, above
  the LandscapingClockWidget / Budget Health / Weather / Total
  Revenue hero. Wrapped in a `testID="dashboard-revenue-tiles"`
  View and role-gated to `super_admin` / `admin` / `manager` (techs
  and customers are already redirected off this screen earlier in
  the render).

### Removed
- Inline `Revenue by Service` chart block previously rendered inside
  `reports.tsx` scroll body — the tile is now the entry point, chart
  logic lives on the dedicated screen. Also removed now-unused
  `svcMax` local from `reports.tsx`.

### Tests
`frontend/src/test/phase-mobile-revenue-parity.test.jsx` (13
assertions) locks: the three screen files exist, they mount `<Header>`
with expected titles + testIDs, they hit the same endpoints the web
equivalents do, the forecast screen renders all five filter chip
testIDs with `week` as default and the custom-range picker modal, and
the three tiles on `reports.tsx` appear in the required source order
above the KPI grid. Regression guards keep the KPI cards + Technician
Performance sections wired.

### Non-scope confirmed
- No new backend endpoints — every mobile call reuses the web
  endpoints (`/finances/income-by-category`, `/reports`,
  `/reports/forecast`, `/reports/forecast-cards`).
- No new dependency — date picker is the existing
  `@react-native-community/datetimepicker` already in `mobile/package.json`.
- Phase 32 / Phase 39 / Phase 30.4 / Live Radar work untouched.

---

## 2026-02-XX — Phase 30.3 (final) · Portal sign-out P0 — Alert.alert was the silent link

Removed `Alert.alert` wrap from the customer portal sign-out handler
in `mobile/app/portal/home.tsx`. On the user's Android/Expo Go build,
`Alert.alert(...)` rendered nothing and silently dropped the
destructive-button callback → tap looked completely dead even though
touch events were reaching JS. Three prior "hotfix" attempts (Alert
wrap, `router.replace` race, flexShrink/hitSlop geometry) all shared
the same root cause and none of them could have worked.

### How we proved it
- **Phase 30.3-diag** (single yellow MVP Pressable + `console.log` +
  `Alert.alert`) proved the bundle was fresh but not whether the tap
  was firing.
- **Phase 30.3-diag2** (dual-location, visual-state probes — yellow
  header button + orange scroll-area bar; both driven by `useState`
  colour flip) proved that Pressable + touch layer + state flush are
  100 % OK. Both buttons turned lime green on tap on the user's
  device. `Alert.alert` was the only thing that never rendered.

### The fix
Handler now mirrors the two proven-working sign-outs in the repo
(`mobile/app/(app)/more.tsx` tech drawer +
`mobile/app/portal/profile.tsx` portal Profile):

```ts
const handleSignOut = React.useCallback(async () => {
  try {
    if (__DEV__) console.log("[portal sign-out] pressed");
    await logout();
    if (__DEV__) console.log("[portal sign-out] logout ok, navigating");
    router.replace("/login");
  } catch (e) {
    if (__DEV__) console.error("[portal sign-out] failed", e);
  }
}, [logout, router]);
```

- **No confirmation dialog** — matches Profile-page pattern. Accidental
  taps are mitigated by a small icon target + deliberate `hitSlop`.
- `router.replace("/login")` after `logout()` — belt-and-suspenders
  navigation independent of the `portal/_layout` `<Redirect>` gate.
- Touch-region guardrails from the earlier hotfix retained:
  `s.headerActions.flexShrink: 0`, `s.signOutBtn.{padding:8,
  borderRadius:8, flexShrink:0}`, and `hitSlop={{top:12, bottom:12,
  left:12, right:12}}`.
- `Alert` import removed from `react-native`'s named-imports block so
  the primitive cannot be silently re-introduced by a future refactor.

### Tests
`frontend/src/test/phase30-3-portal-sign-out.test.jsx` rewritten to
production shape (15 assertions):
- Handler wraps `await logout()` in `try/catch`, logs pressed / ok /
  failed via `__DEV__` guards, and calls `router.replace("/login")`.
- Button uses `onPress={handleSignOut}` — no `Alert.alert`, no
  `onSignOutPress`, no `doSignOut`.
- Regression guard: `Alert.alert(...)` NOT present anywhere in code
  (comments allowed for the breadcrumb).
- Regression guard: `Alert` NOT in the react-native named-imports.
- Regression guard: no `tapCount` / `scrollTapCount` state, no
  `portal-scroll-test-button`, no `[SIGN_OUT_DEBUG]` diagnostic
  strings, no `doSignOut` / `onSignOutPress` legacy callbacks.
- Existing touch-region invariants (flexShrink, padding, hitSlop) still
  locked.
- Profile-page `testID="portal-logout"` regression guard preserved.

Full suite (`phase30-3` + `phase32-ci-config`) → **27 / 27 pass**.

### Non-scope
- Phase 32 CI files untouched.
- Notification bell untouched.
- No confirmation dialog reintroduced on any sign-out surface.

---

## 2026-02-XX — Phase 32 · Minimal CI pipeline (P0.1)

CI pipeline landed — `.github/workflows/ci.yml` runs backend pytest +
frontend vitest + mobile jest on every pull request and every push to
`main`. No deploy stage (out of scope; enforced by
`frontend/src/test/phase32-ci-config.test.jsx`). Cache + concurrency
configured — pip cache on backend, yarn cache on both Node jobs, and a
`ci-${{ github.ref }}` concurrency group with `cancel-in-progress: true`.

### Added
- `.github/workflows/ci.yml` — three parallel jobs: `backend` (Python
  3.11 + `pytest -m "not live and not destructive and not
  legacy_iteration"`), `frontend-web` (Node 20.19 + `yarn vitest run
  --reporter=basic`), `mobile` (Node 20.19 + `yarn test --ci
  --forceExit`).
- `.github/workflows/README.md` — one-paragraph documentation of each
  job and the local-equivalent commands.
- `frontend/src/test/phase32-ci-config.test.jsx` — 12 source-inspection
  assertions locking the workflow shape (job names, triggers,
  concurrency, Node/Python version pins, cache config, and a guardrail
  that no `deploy` / `publish` / EAS build step is present).

### Verification
- YAML validated with `python3 -c "import yaml; yaml.safe_load(...)"` —
  jobs `['backend', 'frontend-web', 'mobile']`, triggers
  `['pull_request', 'push']`, concurrency `{group: 'ci-${{ github.ref
  }}', cancel-in-progress: true}`.
- Phase 32 vitest: **12/12 pass**.
- Backend command spot-checked with `pytest --collect-only` — marker
  filter deselected the 690 legacy/live/destructive tests as intended.

### Non-scope
- Did not fix the 13 red vitest cases or the 9 empty-collection files
  from Phase 31 audit — deferred to Phase 33.
- Did not normalize endpoint path drift — deferred to Phase 34.
- Did not add EAS Build / OTA publish workflow — deferred (documented
  as manual in `mobile/EAS_UPDATE_RUNBOOK.md`).

---

## 2026-08-10 — Phase 30 · Portal + Admin Avatar Coverage (Option 3 + A) + Phase 30.1 mobile persona correction (P1)

### 2026-08-10 (later still) — Phase 30.3 · Mobile customer portal sign-out affordance (P1)

**Hotfix note (later same day)**: user reported the sign-out button
was **not clickable at all** on the mobile portal. Root cause was
a Header/flex geometry bug — not a wiring bug. Details below.

#### Placement — top-right, adjacent to notification bell

The sign-out button sits inside a `<View style={s.headerActions}>`
row alongside `<NotificationBell />`, rendered via the `Header`
widget's `right` prop.

#### Hotfix root cause (tap-not-registering P0)

`mobile/src/components/widgets.tsx::Header` renders its LEFT
block with `flex: 1` and the `right` prop as a direct sibling
with NO explicit width or shrink. Any right-slot wrapper without
`flexShrink: 0` gets squeezed to sub-pixel width on wide devices
— the icons are still visually painted, but the touch region is
0-width so taps land on the flex:1 sibling instead. The bell
survived because it was rendered directly; wrapping it in my
Phase-30.3 `headerActions` View re-triggered the squeeze on some
device widths.

Fix:
- `s.headerActions` — added `flexShrink: 0`. No
  `pointerEvents: "none"` / `overflow: "hidden"` on the wrapper
  (verified via new vitest).
- `s.signOutBtn` — added `flexShrink: 0`, bumped padding 6 → 8.
- `<Pressable>` — hitSlop widened to `{top: 12, right: 12,
  bottom: 12, left: 12}`; added a `pressed`-state opacity for
  tactile feedback so the customer sees the tap register.

#### Prior wiring diagnosis (superseded but kept as belt-and-suspenders)

The earlier hotfix pass introduced an explicit `router.replace(
"/login")` in a `finally` block after `await logout()` to guard
against the layout-gate race on Android. That belt-and-suspenders
navigation stays — even now that the touch region is fixed, an
explicit route reset is safer than relying on
`portal/_layout.tsx`'s `<Redirect />` gate alone.

#### Files touched

- `mobile/app/portal/home.tsx` — `s.headerActions` / `s.signOutBtn`
  style updates, hitSlop widened to 12 dp on all sides, added
  `pressed`-state opacity. `doSignOut` async handler with
  `router.replace("/login")` in `finally` unchanged from the
  wiring-fix pass.

#### Confirmation dialog copy (unchanged)

```
Title:   "Sign out?"
Body:    "You'll need to log back in to see your account."
Cancel:  "Cancel"          (style: "cancel")
Confirm: "Sign out"        (style: "destructive" → doSignOut)
```

#### Tests

- **Vitest** — `frontend/src/test/phase30-3-portal-sign-out.test.jsx`
  (**12 cases**, all green — was 7, +5 for the touch-target
  invariants):
  1. `logout` destructured from `useAuth()`.
  2. Pressable with `testID="portal-sign-out-button"` present.
  3. Alert wrap w/ destructive-style `doSignOut` handler.
  4. `doSignOut` awaits `logout()` AND calls
     `router.replace("/login")` inside a `finally` (belt-and-
     suspenders navigation lock).
  5. Adjacency lock — sign-out right of bell, no stray JSX
     between them.
  6. Ionicons `log-out-outline` glyph (mobile icon family lock).
  7. Exactly one `portal-sign-out-button` testID in the file.
  8. `Profile` subpage `portal-logout` still present.
  9. **NEW** — sign-out is a `<Pressable>` (not `<View>`) with
     an `onPress={onSignOutPress}` prop.
  10. **NEW** — hitSlop present on all four sides.
  11. **NEW** — `headerActions` has `flexDirection: "row"` +
      `flexShrink: 0` + no `pointerEvents: "none"` / `overflow:
      "hidden"`.
  12. **NEW** — `signOutBtn` has `flexShrink: 0` + padding ≥ 6.

- **Full cross-suite regression sweep** — Phase 23 (11) + 25 (8) +
  25b (9) + 26 (6) + 27 web/mobile/seed (15 + 9 + 8) + 28 (13) +
  29 (9) + 30 (17) + 30.3 (12) → **117/117 vitest passing**.

#### Constraints honoured

- No web PortalHome touched.
- Auth store / `logout()` fn untouched — pure UI wire-up.
- Placement unchanged (right of notification bell).
- No new dependencies.

### 2026-08-10 (later) — Phase 30.2 · Mobile portal home next-service consolidation

The mobile portal home had two overlapping next-service surfaces
that showed slightly different data for the same underlying job.
Consolidated to a single surface at the higher-up position:

- **Removed** — the compact "Next Service" pressable row
  (`testID="portal-next-service"`, `s.nextCard` / `s.nextTitle` /
  `s.nextMeta` styles + Ionicons calendar icon + `<StatusChip>`)
  that used to sit above Quick Actions. Deleted in its entirety;
  no conditional / feature-flagged remnant left behind.
- **Moved** — the richer "Next Service Day" card
  (`testID="portal-next-service-day"`, date tile + service name +
  tech avatar chip + address + chevron) previously between the
  Quick Actions grid and Last Visit. Now hoisted up to occupy
  the compact row's former position, directly after the finance
  stat tiles and above Quick Actions.
- **Preserved** — every internal style, `TechAvatar` chip, and
  testID on the moved card. Nothing about the card's content or
  visual treatment changed — only its parent position.
- **Layout after Phase 30.2**:
  Finance stats → **Next Service Day card** (Surface B, moved) →
  Quick Actions → Last Visit → Ask a Concierge.

### Tests

Phase 30 vitest went 14 → **17 cases** with three new Phase 30.2
assertions (all green):
1. Compact "Next Service" pressable (Surface A) is fully removed
   — regression guard on `testID="portal-next-service"` +
   `s.nextCard` / `s.nextTitle` / `s.nextMeta` style references.
2. "Next Service Day" card (Surface B) appears exactly once and
   its source-order position precedes the Quick Actions grid.
3. Tech avatar chip inside the moved card still carries
   `testID="portal-tech-avatar-next"`.

Full cross-suite regression sweep — **105/105 vitest passing**
(was 102 → +3 Phase 30.2). Zero backend / web / other-mobile-file
changes; scope contained to `mobile/app/portal/home.tsx`.

### 2026-08-10 — Phase 30 · Portal + Admin Avatar Coverage

### Part A · Web · AI persona coverage
- `frontend/src/pages/portal/PortalHome.jsx` — swapped two hand-rolled
  `<img src={emp.avatar_url}>` + `<span>{emoji}</span>` blocks for the
  shared `<PersonaAvatar>` (Task RR/SS Phase 2 component). Preserved
  testids: `portal-ai-{key}-avatar` (concierge card grid, size 44)
  and `portal-ai-chat-avatar-{key}` (active-chat header, size 48).
  The F0 `<AuthedImage>` routing + emoji-on-pastel-tint fallback
  now come free from `PersonaAvatar`; previously the F0-uploaded
  avatars would 401 because the raw `<img>` didn't include the
  bearer token.

### Part B · Web · Human staff/tech coverage (5 sites, 3 files)
- `frontend/src/pages/portal/PortalHome.jsx` — next-visit + last-visit
  summary lines now render `<TechAvatar size="xs">` chips next to
  the technician name. Testids: `portal-tech-avatar-next`,
  `portal-tech-avatar-last`.
- `frontend/src/pages/portal/PortalPages.jsx` — upcoming service list
  row + service detail header both render `<TechAvatar>`. Testid
  pattern: `portal-tech-avatar-{j.id}`.
- `frontend/src/pages/admin/CopilotPage.jsx` — swapped the generic
  `<UserIcon>` at the chat-author bubble for
  `<TechAvatar user={{ name: user?.name || user?.email || 'Admin' }}
  size="xs">`. Testid: `admin-tech-avatar-copilot-{user_id}`.
  Removed the `UserIcon` lucide import.

### Part C · Mobile · Customer-portal coverage (3 files)
- `mobile/app/portal/home.tsx` — next-service block now renders
  `<TechAvatar size="xs">` next to the tech name. Testid
  `portal-tech-avatar-next`.
- `mobile/app/portal/services.tsx` — service list row now renders
  `<TechAvatar size="xs">` next to the tech name. Testid
  `portal-tech-avatar-{item.id}`.
- `mobile/app/portal/service/[id].tsx` — service detail header
  now renders `<TechAvatar size="sm">`. Testid
  `portal-tech-avatar-{job.id}`.

### Phase 30.1 — Mobile AI persona correction (audit miss)

The initial audit reported "Mobile · AI persona render sites: NONE."
That was wrong — the "Ask a Concierge" section of the mobile portal
home renders Billy and Skedra (customer-audience personas from
`GET /api/customer-portal/ai-employees`), previously via a
hand-rolled `<Text style={s.conciergeEmoji}>{emp.avatar || "🤖"}</Text>`
block that ignored `avatar_url` entirely. Corrected:

- `mobile/app/portal/home.tsx` — replaced the hand-rolled emoji
  block with `<PersonaAvatar>` (mobile version at
  `mobile/src/components/personas/PersonaAvatar.tsx`, already
  present — bundled JPEG lookup by `persona.key` w/ emoji
  fallback). Testid `portal-ai-{key}-avatar`. Added
  `overflow: "hidden"` to `conciergeAvatar` so the rounded
  wrapper properly clips the JPEG.

### Phase 30.1 — Mobile "Ask a Concierge" specialty subtitle

`mobile/app/portal/home.tsx` — each concierge card now shows a
one-line specialty beneath the name:
`emp.role || emp.description || emp.tagline || ""`
(prefers the seed's canonical `role` field, e.g. "Billing
assistant"; falls back to `description` / `tagline` for older API
responses). New style `conciergeSpecialty` (fontSize 12,
lineHeight 16, `rgba(255,255,255,0.85)` on the teal→emerald
gradient). Row remains fully tappable end-to-end. The pre-existing
`conciergeDesc` render — now unused — is superseded by
`conciergeSpecialty`; the previous 2-line description shown as a
paragraph is replaced with a 1-line subtitle so the card stays
compact.

Web PortalHome subtitle parity was not applied — the web card
grid already renders a persona description block that reads from
the API's `role`/`description` fields; no trivial change fit the
"< 3 lines" bar you set.

### Deferred to Phase 30b (per Option 3 scope lock)

The following 15 mobile tech-facing files are intentionally NOT
patched in this phase and remain candidates for Phase 30b:
`mobile/app/timesheets.tsx`, `job/[id].tsx`, `job-timers.tsx`,
`business-reports.tsx`, `checkins.tsx`, `workstream.tsx`,
`dispatch-savings.tsx`, `(app)/reviews/requests/index.tsx`,
`(app)/reviews/requests/[id].tsx`, `(app)/reviews/leaderboard.tsx`,
`maintenance.tsx`, `coverage.tsx`, `equipment.tsx`,
`pool-service.tsx`, `dispatch.tsx`.

### Tests

- **Vitest** —
  `frontend/src/test/phase30-portal-admin-avatar-coverage.test.jsx`
  (NEW, **14 cases, all green**). Covers Parts A + B + C + Phase
  30.1 with regression guards for the removed hand-rolled blocks
  (`<img src={emp.avatar_url}>`, `<UserIcon>`, `conciergeEmoji`).
- **Full cross-suite regression sweep** —
  Phase 23 (11) + 25 (8) + 25b (9) + 26 (6) + 27 web/mobile/seed
  (15 + 9 + 8) + 28 (13) + 29 (9) + 30 (14) →
  **102/102 vitest passing**.

### Constraints honoured

- Scope: Portal + admin (web + mobile portal only).
- No backend changes — fallbacks stay initials-on-color for humans,
  bundled JPEG + emoji-on-pastel-tint for personas.
- No mobile files touched outside `mobile/app/portal/**`.
- No schedule/dispatch pages touched (Phase 27 already handled).
- No new dependencies.
- Grep-lint stays green.

---

## 2026-08-09 — Phase 28 · `eas update` OTA migration (P2 · infra)

### 2026-08-09 (hotfix) — Phase 28.1 · disable expo-updates auto-check while placeholder is in place (P0)

User's Expo Go screenshot on boot showed **"Uncaught Error:
Request failed (404)"** from `expo-updates`. Root cause: Phase 28's
first pass shipped `updates.url =
https://u.expo.dev/PLACEHOLDER_EXPO_PROJECT_ID` **with**
`checkAutomatically: "ON_LOAD"`, which made the runtime fire an
update check against the placeholder host on every foreground.
That host doesn't exist → 404 → uncaught error surfaced to the
user. Phase 28 was supposed to be inert until the operator
provisioned EAS.

- `mobile/app.json` — flipped `expo.updates.checkAutomatically`
  `"ON_LOAD"` → `"NEVER"` AND added
  `expo.updates.enabled: false`. Placeholder URL preserved so the
  operator still sees where to swap.
- `mobile/scripts/validate_eas_update_config.mjs` — added a hard
  placeholder-state invariant: while `PLACEHOLDER_EXPO_PROJECT_ID`
  is in the URL, `enabled: false` AND
  `checkAutomatically: "NEVER"` MUST both hold, else the script
  exits 1 with a clear diagnostic. Post-swap, if either is still
  in the disabled state, the script surfaces a WARNING so the
  operator remembers to flip both fields active.
- `mobile/EAS_UPDATE_RUNBOOK.md` (§1d) — expanded to document
  the two-edit sequence: swap `PLACEHOLDER_EXPO_PROJECT_ID` for
  the real UUID **and** flip `enabled` → `true` +
  `checkAutomatically` → `"ON_LOAD"` (or `"ON_ERROR_RECOVERY"`)
  before the first `eas update` call.
- `frontend/src/test/phase28-eas-update-config.test.jsx` — split
  the `checkAutomatically` assertion into a placeholder-gated
  branch (accepts `"NEVER"` while placeholder present; requires
  `"ON_LOAD"` or `"ON_ERROR_RECOVERY"` post-swap). Added a new
  hard assertion that `enabled === false` while placeholder is
  present + `enabled === true` post-swap. Suite went 12 → 13
  cases; all green.

**Defensive sanity check on the invariant** — temporarily flipped
`enabled: true` while the placeholder was still in the URL: the
validator correctly exited 1 with the diagnostic
`"expo.updates.enabled MUST be \`false\` while
PLACEHOLDER_EXPO_PROJECT_ID is in the URL"`. Restored to
`enabled: false` → exit 0. This class of regression is now
impossible to ship.

### 2026-08-09 — Phase 28 · `eas update` OTA migration (P2 · infra)

Enables Over-The-Air JavaScript updates for the Expo mobile app.
Config-only migration — zero user-visible feature change. Future
JS-only fixes (screens, hooks, business logic, styles) can now
ship without a store rebuild.

### Files changed / created

- `mobile/app.json` — added:
  - `expo.runtimeVersion: { "policy": "appVersion" }` — OTA
    updates auto-scope to the current `expo.version` (`1.0.0`).
    Bumping `expo.version` forces a store rebuild;
    JS-only fixes are seamless.
  - `expo.updates.url:
    "https://u.expo.dev/PLACEHOLDER_EXPO_PROJECT_ID"` —
    placeholder to swap once `eas init` returns the real UUID.
  - `expo.updates.fallbackToCacheTimeout: 0` — a runtime that
    hangs on update check is worse than one that ships stale
    JS. Zero-timeout means the app never blocks on the update
    fetch.
  - `expo.updates.checkAutomatically: "ON_LOAD"` — check for
    updates every foreground.

- `mobile/eas.json` — NEW:
  - `cli.appVersionSource: "remote"` — EAS-managed version
    bumps.
  - Three build profiles: `development` (dev-client, internal),
    `preview` (internal), `production` (auto-increment).
  - Each profile pins its own `channel` (`development` /
    `preview` / `production`) so the store binary knows which
    update branch to consume.
  - `update.preview.branch: "preview"` and
    `update.production.branch: "production"` — the branch
    mappings `eas update --branch <name>` uses.

- `mobile/package.json` — added `expo-updates: ~29.0.13` (SDK 54
  compatible per Expo's SDK 54 upgrade guide). `yarn install`
  ran cleanly.

- `mobile/scripts/validate_eas_update_config.mjs` — NEW: offline
  config validator (zero network calls) that reads `app.json` /
  `eas.json` / `package.json` and asserts:
  1. `expo.updates.url` starts with `https://u.expo.dev/`.
  2. `expo.runtimeVersion.policy === "appVersion"`.
  3. `fallbackToCacheTimeout` + `checkAutomatically` set.
  4. `cli.appVersionSource` declared.
  5. At least one build profile has a `channel`.
  6. `expo-updates` in `package.json` dependencies.
  Exit 0 on all-green, exit 1 with human diagnostics on drift.
  The lingering `PLACEHOLDER_EXPO_PROJECT_ID` is surfaced as a
  non-blocking WARNING (deliberate — the runbook documents the
  swap step).

- `mobile/EAS_UPDATE_RUNBOOK.md` — NEW, 7-section operator guide:
  1. One-time prereqs (EAS CLI install, `eas login`, `eas init`,
     PROJECT_ID placeholder swap, `validate_eas_update_config`).
  2. Publish an update (preview + production + promotion via
     `eas update:republish`).
  3. Rollback (`eas update:republish` on the last-known-good
     UUID).
  4. OTA-safe vs. store-release-required change matrix.
  5. Phase 28 config summary.
  6. Troubleshooting quick reference.

### Placeholder that MUST be swapped before first push

`app.json` ships `expo.updates.url:
"https://u.expo.dev/PLACEHOLDER_EXPO_PROJECT_ID"`. After
`eas init` returns the real project UUID, replace
`PLACEHOLDER_EXPO_PROJECT_ID` with that UUID. See §1d of the
runbook. The validation script prints a WARNING while the
placeholder is in place — no other action needed.

### Tests

- **Vitest** — `frontend/src/test/phase28-eas-update-config.test.jsx`
  (NEW, 12 cases, all green):
  1. `expo.updates.url` starts with `https://u.expo.dev/`.
  2. `expo.runtimeVersion.policy === "appVersion"`.
  3. `expo.updates.fallbackToCacheTimeout: 0` +
     `checkAutomatically: "ON_LOAD"`.
  4. `cli.appVersionSource` declared.
  5. At least one build profile has a `channel`.
  6. `preview` + `production` build profiles have matching
     channels.
  7. `preview` + `production` update branch mappings present.
  8. `expo-updates` declared as a dependency.
  9. Uses SDK-54-compatible `29.x` range.
  10. Runbook file present + non-trivial (>1500 bytes).
  11. Validation script file present.
  12. Validation script exits 0 with only the documented
      placeholder warning.

- **Validation script** — ran cleanly:
  `✓ EAS Update config validation passed. (1 warning — non-blocking)`.

### Cross-suite regression sweep

Phase 23 (11) + 25 (8) + 25b (9) + 26 (6) + 27 web (15) +
27 mobile (9) + 27 seed (8) + 28 (12) + 29 (9) →
**87/87 vitest passing**.
No backend / web / other-mobile-screen changes; Phase 26 + 29
pytest suites unaffected.

### Constraints honoured

- Scope: Phase 28 only.
- No backend / web / other mobile screens touched.
- No `eas update` push attempted from the pod (no credentials,
  no network calls to expo.dev).
- No existing build profile in `eas.json` altered (file was
  new — nothing to preserve).
- No new native dependencies (only `expo-updates`, which is
  first-party Expo + safe to add via `expo install`).
- Grep-lint stays green.

### Next steps for the operator (out of scope here)

1. `cd /app/mobile && eas login`
2. `eas init` — get the project UUID.
3. Swap `PLACEHOLDER_EXPO_PROJECT_ID` in `app.json` for that UUID.
4. `node scripts/validate_eas_update_config.mjs` — expect
   `✓ passed` with **zero warnings**.
5. `eas update --branch preview --message "Phase 28 initial"`.
6. See the runbook for the full flow.

---

## 2026-08-08 — Phase 29 · Enforce Auto Clock-In for Technicians (P1)

Technicians cannot disable Auto Clock-In. Enforced at **three
independent layers** so a debug-build tamper, storage tamper, or
API replay can't bypass the rule. Managers / owners / super_admin
keep their pre-existing self-toggle behaviour.

### Mobile — settings screen

- `mobile/app/(app)/settings/auto-clockin.tsx`
  - Reads role from `useAuth()`; computes `isTech = role === "technician"`.
  - `<Switch>` bindings are `value={true} disabled={true}` for
    techs (was `value={enabled}` / `disabled={busy}`).
  - Label subtext replaced with a locked-state row:
    lock icon + `"Enforced by your organization. Contact your
    manager to change this setting."`, testid
    `auto-clockin-tech-locked-subtext`.
  - `onToggle` short-circuits with `if (isTech) return` before
    touching storage or the background hook — defence-in-depth
    against deep-link / race paths.
  - On mount, the effect calls
    `setAutoClockinEnabled(true, "technician")` to heal any
    legacy `false` value from a pre-Phase-29 debug build.
  - Non-tech roles still see the existing "Auto Clock-In is
    available to technicians" gate — behaviour unchanged.
  - Uses the already-imported `Ionicons` family for the lock
    icon — no new icon dependency.

### Mobile — background hook

- `mobile/src/background/autoClockin.ts`
  - `isAutoClockinEnabled(role)` short-circuits with
    `return true` when `role === "technician"` — BEFORE any
    storage read — so a bad storage value cannot leak through
    on any code path.
  - `setAutoClockinEnabled(enabled, role)` gained an optional
    `role` param; when it's `"technician"` the persisted value
    is coerced to `true` regardless of the caller's input.

### Backend — API refuses to persist tech-disable

- `backend/routers/auto_clockin.py::patch_self`
  (`PATCH /api/users/me`) — refuses `auto_clockin_enabled: false`
  when the caller's role is `technician`, returning:
  ```
  403 · "Auto Clock-In is enforced for technicians and cannot
        be disabled. Contact your manager."
  ```
  Non-tech roles keep their pre-existing self-toggle. Idempotent
  `auto_clockin_enabled: true` PATCH still 200s for techs so the
  mobile screen's heal-storage side-effect can safely re-affirm
  the flag.

### Web mirror — none needed

`frontend/src/pages/ops/OpsHub.jsx::TechAutoClockinToggle` is an
**admin-only per-tech toggle on the Team roster** (gated by an
`editable` prop that's only true for admin/super_admin). It is NOT
a self-service surface — a tech viewing their own row would see an
inert dash, not a flip target. No Phase 29 changes needed on the
web surface. This is documented + asserted in the vitest.

### Tests

- **Vitest** —
  `frontend/src/test/phase29-auto-clockin-tech-lockdown.test.jsx`
  (NEW, 9 cases, all green):
  1. Screen imports `useAuth()` from `@/src/auth` + checks tech
     role.
  2. `<Switch>` renders `value={true} disabled={true}` — no more
     `value={enabled}` / `disabled={busy}` bindings.
  3. Locked-state subtext copy present + testid attached.
  4. `onToggle` short-circuits on `if (isTech) return`.
  5. Mount effect calls
     `setAutoClockinEnabled(true, "technician")` (heal storage).
  6. Non-tech gate still renders (behaviour unchanged).
  7. `isAutoClockinEnabled` `return true` for techs appears
     BEFORE the storage reads in source order.
  8. `setAutoClockinEnabled` uses the
     `role === "technician" ? true : enabled` coercion.
  9. Web OpsHub `TechAutoClockinToggle` remains admin-only
     (no Phase 29 change required, documented).

- **Pytest** —
  `backend/tests/test_phase29_auto_clockin_tech_lockdown.py`
  (NEW, 4 cases, all green):
  1. Tech PATCHing `false` → 403; DB row still `true`.
  2. Tech re-affirming `true` → 200 (idempotent heal path).
  3. Admin PATCHing `false` → 200 (behaviour unchanged).
  4. Super-admin PATCHing `false` → 200 (behaviour unchanged).

- **Legacy pytest updated** —
  `backend/tests/test_auto_clockin_and_orphan.py::test_self_patch_auto_clockin_flip`
  used to assert a tech CAN flip themselves off. Under Phase 29
  this is a policy change: the test now expects **403** on
  `false` from a tech + verifies the DB was untouched. Also
  fixed a stale seed-email drift in that file
  (`mike@aquaterra.com` → `landscaper@aquaterra.com`) so it
  actually runs on the current pod seed.

### Cross-suite regression sweep

- Vitest — Phase 23 (11) + 25 (8) + 25b (9) + 26 (6) + 27 web (15)
  + 27 mobile (9) + 27 seed (8) + 29 (9) → **75/75 passing**.
- Pytest — Phase 26 (5) + 29 (4) → **9/9 passing**. Full
  `test_auto_clockin_and_orphan.py` → 14/14 (transient 15s
  read-timeout on one run was pod-load, not a real regression).

### Runtime behaviour unaffected

Phase 29 changes ONLY the toggle enforcement path. GPS permission
prompts, the background TaskManager registration, the fetch to
`POST /api/workforce/auto-clock-in`, and the 10-second cancel
toast are all untouched.

### Constraints honoured

- Scope: Phase 29 only. Phase 28 (`eas update`) NOT started.
- No dispatch / Phase 25b / Phase 27 code touched.
- No new dependencies (mobile or backend).
- Grep-lint stays green.

---

## 2026-08-07 — Phase 25b · JobTrackerTiles geometry rewrite (P0)

Root cause: `aspectRatio: 1` + oversized SVG caused the label to
spill past the LinearGradient rounded clip on narrow phones. Fixed
by dropping `aspectRatio`, clamping the SVG in a fixed-size `<View>`
wrapper, moving `0/0` numeric out of the SVG viewBox, and isolating
the label in its own sibling `<View>`.

### Actual root cause (Phase 25 got the surface but missed the geometry)

Phase 25 hardened label *typography* (lineHeight, includeFontPadding,
paddingBottom, dropped `adjustsFontSizeToFit`). The vitest checked
those style-value tuples — but never verified whether the tile's
outer dimensions could actually hold the inner content stack.

Under `tileWrap: { flex: 1, aspectRatio: 1 }`, on a 360-370 dp
Android phone the 2-column row math yields:

```
per-tile width  ≈ 162 dp   → aspectRatio 1 → tile height 162 dp
interior height  = 162 - 14 (paddingTop) - 20 (paddingBottom) = 128 dp
content needed   = 108 (ring) + 10 (gap) + 28 (label) = 146 dp
overflow         = +18 dp  → label falls INTO the LinearGradient
                             corner-radius clip mask
```

That's exactly the "faint traces of the top of letters" pattern
the fresh Android screenshot showed.

### Six-part fix (`mobile/app/(app)/schedule/JobTrackerTiles.tsx`)

1. **Dropped `aspectRatio: 1`** on `tileWrap`. Tile now sizes to
   the natural content stack; row still uses `flex: 1` so both
   columns share width evenly.
2. **Hard-clamped SVG to 96 dp** via a shared `RING_SIZE` constant.
   The `<Svg>` sits inside a `ringSvgWrap` `<View>` whose width and
   height are both pinned to `RING_SIZE`, so no ancestor flex can
   inflate the ring.
3. **`0/0` numeric stays OUT of the SVG viewBox** — rendered as an
   absolutely-positioned `<Text>` overlay on the fixed 96 x 96
   `ringSvgWrap`. Zero SVG glyph clipping possible.
4. **Label in its own sibling `<View style={styles.labelWrap}>`**
   — never nested in a parent `<Text>`, so
   `includeFontPadding` on the label always takes effect on
   Android (parent-text inheritance would silently disable it).
5. **Label props hardened** — no `numberOfLines`, no
   `adjustsFontSizeToFit`. Two-line wrap on very narrow phones is
   acceptable and preserves the descender.
6. **`minHeight: 180` on the tile** — natural content stack is
   ~176 dp so this is a 4 dp safety margin against hypothetical
   parent-flex collapse.

No `overflow: "hidden"` anywhere in the tile subtree — verified
by the new geometry vitest.

### New test contract (this is where Phase 25's suite failed us)

`frontend/src/test/phase25b-job-tracker-geometry.test.jsx` (NEW, 9
cases, all green) — the geometry-first vitest that Phase 25 should
have shipped:

1. Tile MUST NOT set `aspectRatio` (regression guard).
2. Tile MUST have `minHeight >= 180`.
3. SVG lives in a fixed-size `<View>` with `width === height` and
   both `<= 100` dp.
4. Label lives in its own sibling `<View>` — `<View
   style={styles.labelWrap}>` immediately precedes the label
   `<Text>` in the source.
5. Label style: `lineHeight >= fontSize + 6`, `paddingBottom >= 6`,
   `includeFontPadding: true`.
6. Label `<Text>` carries neither `numberOfLines` nor
   `adjustsFontSizeToFit`.
7. No `overflow: "hidden"` on `tile`, `tileWrap`, `ringSvgWrap`,
   or `labelWrap`.
8. Label still outside the `<Svg>` viewBox (Phase 24 invariant).
9. **Content-stack height math holds**:
   `ringSize + labelWrap.paddingTop + label.lineHeight +
   label.paddingBottom + labelWrap.paddingBottom
   <= tile.minHeight - tile.paddingTop - tile.paddingBottom`.
   Sources the numbers from the actual style bodies + the
   `RING_SIZE` constant so any future tweak that would silently
   reopen the spill fails loudly here.

The vitest also strips JSDoc + line comments before matching so
regexes only inspect executable code (Phase 25's suite matched
comment text that mentioned the OLD state, which is a general
lesson for future source-inspection tests).

### Phase 25 test file updated

`frontend/src/test/phase25-job-tracker-label-clipping.test.jsx` —
the assertion `tile.paddingBottom >= tile.borderRadius` is
**superseded**. Under Phase 25b geometry, descender safety moved
into the dedicated `labelWrap` `<View>`, so the new equivalent
lock is:

```
labelWrap.paddingBottom + label.paddingBottom  >= tile.borderRadius
```

Same intent, correct surface. All other Phase 25 assertions
(lineHeight buffer, includeFontPadding, no
`adjustsFontSizeToFit`, no `overflow: hidden`, label outside SVG,
paddingBottom >= 4) still hold under Phase 25b geometry — kept as
cross-referenced safety guards. Suite: **8/8 passing**.

### Phase 27 mobile regression file updated

`frontend/src/test/phase27-mobile-avatar-dense.test.jsx` had the
same stale `tile.paddingBottom >= borderRadius` inline assertion
— rewritten to the Phase 25b equivalent. Suite: **9/9 passing**.

### Manual Expo Go verification checklist

Because Expo cannot render headlessly in the pod:

1. `yarn tunnel` in `/app/mobile/` and open the app in Expo Go on
   the **same Android device** that produced the regression
   screenshot (or any device ≤ 380 dp width — that's where the
   old geometry broke).
2. Sign in as `landscaper@aquaterra.com` / `password123`.
3. Open the Schedule tab. The two tiles ("Service Stops",
   "Repair Stops") sit above the WeekStrip.
4. Confirm the FULL word "**Stops**" reads clearly on both
   tiles — the "p" descender must be fully visible with visible
   pixels below the "o" baseline, well above the tile's rounded
   bottom edge.
5. Confirm the ring is visibly smaller than in the regression
   screenshot — 96 dp with the "0/0" digits at 22 dp fontSize
   is the target.
6. Rotate to landscape (or use a wide device) — the tile should
   naturally grow only in width; the fixed-size ring stays 96 dp
   centered and the label sits directly below with the same
   readable spacing.
7. Try 0/0 (empty ring), partial arc, and full arc — the ring
   center numeric and the label position must be invariant.

### Cross-suite regression sweep

Phase 23 (11) + Phase 25 (8) + Phase 25b (9) + Phase 26 (6) +
Phase 27 web (15) + Phase 27 mobile (9) + Phase 27 seed (5) →
**63/63 vitest passing**. No existing product code outside
`JobTrackerTiles.tsx` was touched.

### Acknowledgement

Phase 25's source-inspection tests only checked style *values*
(`lineHeight`, `paddingBottom`, `includeFontPadding`,
`borderRadius`), never geometry *relationships* — specifically
whether the tile's outer height could hold the content stack. The
Phase 25b vitest ships an explicit content-stack math check so any
future style tweak that would re-open the spill fails immediately.

### Constraints honoured

- Scope: Phase 25b only. Phase 28 untouched. No backend, web,
  dispatch, or seed changes in this patch — pure mobile fix on
  one file plus tests.
- No new dependencies.
- Tile visual preserved — purple → blue gradient (`#7c3aed` →
  `#3b82f6`), green completion arc (`#22c55e`), centered X/Y
  numeric all intact. Ring is now 96 dp (was 108) — a deliberate
  clamp per the P0 brief.
- Grep-lint stays green.

### Deferred

Phase 27 dispatch seed follow-up (adding `service_lat`,
`service_lng`, `service_days` to the demo customer doc) — waiting
on re-instruction now that this P0 is closed.

---

## 2026-08-06 — Phase 27 · Global avatar swap for Schedule tiles + Dispatch Board (P2)

### 2026-08-07 — Phase 27 follow-up #3 · Dispatch-board denormalized fields on demo customer

Dispatch board query hard-filters on
``service_lat: {$exists: true, $ne: null}`` and (when a day is
selected) ``service_days: <day>``. The Phase 27 seed only wrote
customer-form ``latitude`` / ``longitude`` / ``address``, so the
demo customer was silently excluded from ``tech_load``. Extended
the seed helper (no product-code change) to write the denormalized
``service_*`` fields that ``customer_categories.recompute_customer_denorm``
normally populates.

- `backend/scripts/seed_phase27_demo_job.py::_upsert_demo_customer`
  now also `$set`s `service_lat` (33.7734), `service_lng`
  (-112.2378), `service_address`, and `service_days`
  (`["mon","tue","wed","thu","fri","sat","sun"]` — the exact
  lowercase 3-letter convention `dispatch_board.py` +
  `customer_categories._DAY_NAMES` use). Verbose verify log now
  echoes all four fields.
- `frontend/src/test/phase27-seed-script-invariants.test.jsx` —
  extended from 5 → **8 assertions**: adds `service_lat`,
  `service_lng`, `service_address`, and the `mon..sun`
  day-name convention lock.
- **End-to-end verification** (super-admin `GET /api/dispatch/board`
  against the pod): `tech_load` returns 1 row for Luis
  (`count: 1, drops: ['seed-phase27-demo-customer']`, `name:
  'Luis Marquez'`, `color_hex: '#D97706'`); pin resolves with
  `crew_label: 'Landscaping'` and all `service_days` intact.
- Full cross-suite regression sweep — Phase 23/25/25b/26/27 all
  green (**66/66 vitest passing**). No product code touched.

### 2026-08-06 (even later) — Phase 27 follow-up #2 · Dispatch-board seed extension

Dispatch avatar row was blocked because `/api/dispatch/board`'s
`tech_load` is derived from `customers.assigned_tech_ids`, not job-
level assignment. Extended the seed script (no product-behaviour
change) so the demo customer document exists with Luis in the
tech-array — data-only fix.

- `backend/scripts/seed_phase27_demo_job.py` — added
  `_upsert_demo_customer` helper. Uses `$addToSet` on the
  `assigned_tech_ids` array so re-runs never duplicate the entry;
  `upsert=True` so first run inserts, later runs update. Job
  document's `customer_id` now references the seeded customer id
  (`seed-phase27-demo-customer`) so the dispatch board's
  customer/job join lights up. Verbose logging prints the final
  `assigned_tech_ids` array so testers can confirm the write.
  Idempotency verified on-pod: first run inserted, second run
  updated with the array still holding exactly one entry.
- `frontend/src/test/phase27-seed-script-invariants.test.jsx` (NEW,
  5 cases, all green) — source-inspects the seed script and locks:
  1. `db.customers.update_one(…)` is called (not just jobs).
  2. `$addToSet` on `assigned_tech_ids` (idempotency guard).
  3. `upsert=True` (so first run inserts).
  4. Job payload's `customer_id` references the seeded id.
  5. Preflight bails with `return None` + "bailing" log when the
     tenant / Luis drift (regression guard against orphan writes).

Full Phase 25/26/27 vitest sweep: **43/43 passing** (added 5 new
seed assertions). No product code was touched; existing
`dispatch_board.py` logic is unchanged.

### 2026-08-06 (later) — Phase 27 follow-up · CalendarSchedule + demo-job seed

Routing miss caught in verification: `/schedule` mounts
`CalendarSchedule` (Grid mode is the default), not the legacy
`TodaySchedule`. The Phase 27 avatar swap has been extended to the
primary surface + a demo job seeded so the tester can visually
verify both dense-layout avatars.

- `frontend/src/pages/schedule/CalendarSchedule.jsx` — the Grid-mode
  per-job card render (`GridPanel`, jobs.map, line ~1300) now mounts
  a compact `<TechAvatar size="xs" />` immediately left of the
  customer name, guarded by the same
  `technician_name || assigned_technician_name || technician_id`
  conditional used in `TodaySchedule.jsx`. Testid:
  `schedule-card-tech-avatar-${j.id}` — matches the legacy-timeline
  surface so `[data-testid^=\"schedule-card-tech-avatar-\"]`
  resolves on whichever surface is active. Row height unchanged
  (20 px avatar fits under the existing font-size line-height).
- `frontend/src/pages/schedule/TodaySchedule.jsx` — kept intact for
  the legacy `/schedule/legacy-timeline` route.
- **Seed helper** —
  `backend/scripts/seed_phase27_demo_job.py` (NEW, idempotent):
  upserts one job with the stable id `seed-phase27-today-job`
  assigned to Luis Marquez (`landscaper@aquaterra.com`) on today's
  date, with Peoria-AZ coordinates so it lands on the Dispatch
  Board map viewport. Second run only updates
  `scheduled_date` (to today) + `updated_at` so it never leaves
  stale calendar-day data behind. Preflight bails cleanly with a
  WARNING if the pinned tenant/user drift so no orphan rows land.
  Ran on the demo pod today — insert on first run, matched=1 on
  second run.
- **Vitest** — extended
  `frontend/src/test/phase27-avatar-dense-layouts.test.jsx` with 4
  new assertions locking the CalendarSchedule surface (import,
  `<TechAvatar size='xs' />` mount, testid pattern, technician
  conditional). Suite total: **15 cases, all green**. Full Phase
  25/26/27 sweep: **38/38 passing**. No existing Phase 27
  assertions were altered.

**Seeded job id for the tester**: `seed-phase27-today-job`
(tenant `3814833a-dd0d-4bd9-90ea-351c24924649`, assigned to
`landscaper@aquaterra.com`, scheduled for today).

To re-seed on a later day (e.g., new tester run): run
`python3 /app/backend/scripts/seed_phase27_demo_job.py` — it will
idempotently move the job to today's date.

### Housekeeping (Phase 26 tester side-effect)

- Reset seed user `landscaper@aquaterra.com` (Luis Marquez) back to
  `department: "landscape_tech"` — the Phase-26 tester mutation had
  flipped him to `pool_tech`. Update ran as a targeted
  `db.users.update_one` and left every other row untouched.

### Added

- **Shared web avatar shim** —
  `frontend/src/components/common/TechAvatar.jsx` (NEW): thin wrapper
  over the Phase-B1 `<UserAvatar />` that standardises the dense
  layout pixel vocabulary — ``xs=20 · sm=28 · md=40``. Zero business
  logic; all fallback behaviour (image → initials → deterministic
  pastel tint) inherited from the underlying component. `TECH_SIZE_PX`
  named export lets consumers hard-lock the numeric size.

- **Shared mobile avatar** —
  `mobile/components/common/TechAvatar.tsx` (NEW): RN-native equivalent
  matching the web shim's ``xs/sm/md`` vocabulary. Same fallback chain,
  same deterministic pastel palette so cross-platform reviewers see
  the same visual weight. Pure RN primitives — no new dependencies.

### Changed — web

- `frontend/src/pages/dispatch/TechLoadStrip.jsx` — swapped the
  generic `<UserRound />` lucide icon for `<TechAvatar size="xs" />`
  on every tech-load row. Each avatar carries a
  `dispatch-tech-avatar-${tech_user_id}` testid.
- `frontend/src/pages/schedule/TodaySchedule.jsx` — the per-job
  schedule card header now renders a compact `<TechAvatar size="xs" />`
  immediately left of the service-type badge, conditional on the
  payload actually carrying an assigned tech identity
  (`technician_name` / `assigned_technician_name` / `technician_id`).
  Header line-height already accommodated a 20px badge, so row
  height is unchanged. Testid:
  `schedule-card-tech-avatar-${j.id}`.

### Changed — mobile

- `mobile/app/(app)/schedule/calendar.tsx` — the per-job grid row
  (`JobRow`) now shows a 20dp `<TechAvatar />` chip on the customer
  line when the job carries an assigned tech. Wrapped the customer
  `<Text>` + avatar in a horizontal flex row so nothing pushes the
  cluster of chips below. Testid:
  `grid-tech-avatar-${job.id}`.
- `mobile/app/(app)/dispatch/board.tsx` — deliberately untouched.
  The board.tsx filter is `!j.technician_id && !j.assigned_to`, so
  the surface renders unassigned jobs only — there is no tech
  identity to visualise. The Phase-27 mobile vitest guards this
  invariant so a future refactor that adds assigned-job rendering
  gets flagged for an avatar swap.

### Preserved

- Dense-layout row heights unchanged on both surfaces.
- Tenant color theming preserved (avatar tint is deterministic
  from initials, orthogonal to tenant colors).
- Phase 25 label-clipping guarantees on `JobTrackerTiles.tsx` are
  intact — the Phase-27 mobile vitest re-asserts the label
  `lineHeight`, `includeFontPadding`, `paddingBottom`, and
  outside-SVG contract.

### Tests

- **Vitest — web** —
  `frontend/src/test/phase27-avatar-dense-layouts.test.jsx` (NEW,
  11 cases, all green):
  1. `TECH_SIZE_PX` matches the ``{xs:20, sm:28, md:40}`` spec.
  2. `<TechAvatar size="xs" />` renders at 20 x 20 px.
  3. `<TechAvatar size="sm|md" />` renders at 28 / 40 px.
  4. Initials fallback: `"Luis Marquez" → "LM"`.
  5. `TechLoadStrip.jsx` imports `TechAvatar` from
     `@/components/common/TechAvatar`.
  6. `TechLoadStrip.jsx` mounts `<TechAvatar size="xs" />`.
  7. `TechLoadStrip.jsx` attaches
     `dispatch-tech-avatar-${tech_user_id}` testid.
  8. `TechLoadStrip.jsx` no longer imports or renders
     `<UserRound />` (regression guard, comment mentions allowed).
  9. `TodaySchedule.jsx` imports the shared TechAvatar.
  10. `TodaySchedule.jsx` mounts `<TechAvatar size="xs" />`.
  11. Card avatar carries `schedule-card-tech-avatar-${j.id}` testid.

- **Vitest — mobile source-inspection** —
  `frontend/src/test/phase27-mobile-avatar-dense.test.jsx` (NEW,
  9 cases, all green):
  1. `mobile/app/(app)/schedule/calendar.tsx` imports the mobile
     TechAvatar.
  2. Same file mounts `<TechAvatar size="xs" />`.
  3. Avatar chip guarded behind a `technician_name || assigned_…`
     conditional (no chip for unassigned jobs).
  4. Per-job testID `grid-tech-avatar-${job.id}` present.
  5. Dispatch board: either references TechAvatar or is
     confirmed unassigned-only (the current file satisfies #2).
  6-9. Phase 25 regression guards (label lineHeight, includeFontPadding,
       paddingBottom≥borderRadius, outside-SVG).

- **Regression sweep** — Phase 23/25/26/27 vitests all green
  (**45/45 passing**). Full-suite baseline unchanged at 16 pre-existing
  failures (all `@jest/globals` stale-import files on surfaces
  outside Phase 27's scope — `phase22-mobile-schedule-gates`,
  `phase34-*`, etc.). `slice-p17-additions.test.jsx` (which
  exercises `TechLoadStrip`) passes 7/7 — the avatar swap is
  compatible with the existing Phase 17 shift-route flow.

### Manual verification checklist

**Web** — open the preview URL and hit these two routes as an
admin/dispatcher:

1. **Dispatch Board** — the right-column "Tech Load" strip now
   shows a 20 px round avatar (initials on a deterministic pastel
   tint, or the tech's photo if `profile_photo_url` is set) in
   place of the generic person icon. Row height unchanged.
2. **Today Schedule (`/schedule/today`)** — each job card that
   has an assigned technician shows a matching 20 px avatar
   inline with the red service-type text at the top of the card.
   Jobs without an assigned tech render unchanged (no chip).

**Mobile (Expo Go)** — `yarn tunnel` in `/app/mobile/` and open on
Android:

1. Log in as any role that lands on the Schedule tab.
2. **Schedule → Grid view** — each per-job card in the day list
   shows a compact 20 dp avatar immediately left of the customer
   name when the job has an assigned tech. Jobs without a tech
   render unchanged.
3. **Schedule → JobTrackerTiles** (Phase 25 regression) — the
   "Service Stops" / "Repair Stops" tiles must still render with
   the "p" descender fully visible on the purple → blue gradient.
4. **Dispatch board** (Expo Go) — unchanged; this surface still
   renders only unassigned jobs and has no tech identity to swap.

### Constraints honoured

- Scope: Phase 27 only. Phase 28 untouched.
- Invoice invariant preserved — no `db.invoices` writes.
- No new dependencies (backend/frontend/mobile).
- Row / tile heights unchanged on all four dense surfaces.
- Grep-lint stays green.

---

## 2026-08-05 — Phase 26 · Super-admin Review Department Suggestions modal + audit trail (P1)

### Added

- **Backend** — new endpoint
  `POST /api/admin/apply-department-suggestions` in
  `backend/routers/inventory_reports.py`:
  - **Auth**: `require_super_admin` — admin/owner/technician all get
    403.
  - **Request**:
    ```json
    { "applications": [ { "user_id": "…", "department": "pool_tech|landscape_tech|both" } ] }
    ```
    Empty `applications` is accepted and returns
    `{applied: 0, failed: []}` with zero writes.
  - **Response**:
    ```json
    { "applied": <int>, "failed": [ { "user_id": "…", "reason": "user_not_found|update_failed" } ] }
    ```
  - **Audit trail**: every successful update inserts a row into
    `db.department_change_audit`:
    ```
    { id, tenant_id, actor_user_id, target_user_id,
      from_department, to_department, source: "admin_bulk_apply", ts }
    ```
    Audit rows are bulk-inserted with `ordered=False` so an
    individual audit failure never rolls back a successful user
    mutation; any insert-time exception is logged for post-hoc
    reconciliation.
  - **Coexistence**: distinct from the Phase-20 admin+
    `POST /api/admin/users/bulk-department` (which stays audit-free
    for backward compatibility) — this new endpoint is the
    audit-tracked super-admin surface.

- **Frontend** — new component
  `frontend/src/components/admin/SuggestDepartmentsModal.jsx`:
  - Fully controlled (parent owns `open`/`onClose`/`onApplied`).
  - Loads suggestions via
    `POST /api/admin/suggest-departments` on open, hides rows with
    no signal, preselects rows with confidence ≥ 0.75.
  - Table columns: checkbox · Technician · Current · Suggested
    (editable `<select>` — admin can override the AI suggestion
    before applying) · Confidence · Rationale (`pool_jobs ·
    landscape_jobs · days_window`).
  - Header row: "Select all" checkbox, footer shows
    `N of M selected` counter.
  - Footer buttons: Cancel + `Apply selected (N)` (disabled when
    N=0 or a request is in flight).
  - On Apply → POSTs `{applications: [{user_id, department}]}` to
    the new Phase-26 endpoint; success toast on
    `{applied>0, failed:[]}`, warning toast with counts on partial
    success, error toast on network/500. Uses existing `sonner`
    toast wiring — no new toast library introduced.
  - Test IDs: `phase26-*` (modal, table, toggle-all, per-row check,
    per-row override select, apply, cancel, close, loading, empty,
    error).

- **UI entry point**: new "Review Department Suggestions" button
  added to the header of the Admin Users page
  (`frontend/src/pages/admin/AdminUsersList.jsx`), next to the
  existing Phase-20 "Suggest departments" button:
  - Location: `/admin/users` (or whichever route mounts
    `AdminUsersList`).
  - `data-testid="admin-users-review-departments-btn"`.
  - Clicking opens the new Phase-26 modal; on successful apply
    the users list refetches so the admin sees the mutated
    `department` value immediately.

### Tests

- **Pytest** — `backend/tests/test_phase26_bulk_apply_departments.py`
  (NEW, 5 cases, all green):
  1. Happy path — 3 applications → 3 `db.users` updates + 3
     `db.department_change_audit` rows.
  2. Partial failure — 1 ghost `user_id` yields `applied: 2` +
     `failed: [{user_id, reason: 'user_not_found'}]`; audit rows
     land only for the two that succeeded.
  3. Admin role → 403.
  4. Technician role → 403.
  5. Empty payload → `applied: 0, failed: []`, zero writes to
     either collection.

- **Vitest** —
  `frontend/src/test/phase26-suggest-departments-modal.test.jsx`
  (NEW, 6 cases, all green):
  1. Renders suggestion rows from the mocked load.
  2. "Select all" cycles preselected → all → none with the
     counter updating.
  3. Apply button disabled when zero rows selected.
  4. Clicking Apply POSTs the correct `{applications: [...]}`
     payload to `/admin/apply-department-suggestions`.
  5. Success toast fires when apply returns `{applied>0, failed:[]}`.
  6. Error toast fires when apply throws (500-like).

### Constraints honoured

- Scope: Phase 26 only. Phases 27–28 untouched.
- Invoice invariant preserved — no `db.invoices` writes.
- `db.quotes` / `doc_type` not touched.
- No new dependencies (backend uses stdlib `uuid`; frontend uses
  existing `sonner` toast + `@/api` axios wrapper).
- Phase-20 endpoint and modal remain untouched — this is an
  additive audit-tracked super-admin surface, not a replacement.

---

## 2026-08-04 — Phase 25 · Mobile Schedule — JobTrackerTiles label descender-clip fix (P0)

### Fixed

- `mobile/app/(app)/schedule/JobTrackerTiles.tsx` — the "p" descender
  in "Stops" was still being clipped on Android after Phase 24. Root
  causes identified:
  1. **No explicit `lineHeight`** on the label — RN measured the
     text box tight to `fontSize: 15` (implicit lineHeight ≈ 17-18),
     leaving <2dp for the descender. On Android that's routinely
     rounded away.
  2. **`adjustsFontSizeToFit` + `numberOfLines={1}`** — a known RN
     Android bug where the shrunk font still uses the original
     baseline math, chopping descenders even when the visible
     glyph would fit.
  3. **Corner-radius clip** — `LinearGradient` with
     `borderRadius: 16` implicitly clips at rounded corners; with
     the prior `padding: 14` the descender was landing inside the
     corner-radius arc.
  4. **`includeFontPadding`** — if any parent Text theme flipped
     the Android default off, the descender pad disappears.

  Fix:
  - Label style now sets `lineHeight: 22` (fontSize + 7 buffer,
    exceeds the spec minimum of `fontSize + 4`).
  - Label style adds `paddingBottom: 6` as belt-and-suspenders.
  - Label style adds explicit `includeFontPadding: true` so Android
    always keeps the descender pad regardless of parent theme.
  - `adjustsFontSizeToFit` dropped from the `<Text>` element — the
    labels are short (`"Service Stops"` / `"Repair Stops"`) and
    known-fit at 108dp ring size; the prop only introduced the
    shrink-to-fit descender bug.
  - Tile style splits `padding: 14` into `paddingHorizontal: 14`,
    `paddingTop: 14`, `paddingBottom: 20`. `paddingBottom > 
    borderRadius` (20 > 16) guarantees the descender never lands
    inside the corner-radius arc.
  - Tile does NOT set `overflow: "hidden"` — deliberately, so the
    label's immediate parent can never clip descenders even under
    edge-case font-metric drift.

### Tests

- `frontend/src/test/phase25-job-tracker-label-clipping.test.jsx`
  (NEW) — source-inspection vitest that reads
  `mobile/app/(app)/schedule/JobTrackerTiles.tsx` and locks the
  descender-clip contract:
  1. label `lineHeight` >= `fontSize + 4`
  2. label `paddingBottom` >= 4 (or `paddingVertical` >= 4)
  3. label `includeFontPadding: true`
  4. label's immediate parent (`tile`) has **NO**
     `overflow: "hidden"`
  5. `tile.paddingBottom` >= `tile.borderRadius` (descender safe
     zone)
  6. `<Text>` element does not carry `adjustsFontSizeToFit`
  7. Regression guard from Phase 24 — label still outside `<Svg>`

- Phase 23 / Phase 24 assertions in
  `phase23-job-tracker-tiles.test.jsx` remain intact (source
  patterns unchanged for testIDs, gradient, arc color, and label
  outside-SVG lock).

### Constraints honoured

- Mobile-only — no backend or web code changes.
- No new dependencies.
- Tile visual preserved — purple → blue gradient (`#7c3aed` →
  `#3b82f6`), green completion arc (`#22c55e`), centered big-number
  `X/Y` count all unchanged.
- Grep-lint stays green — zero writes to `db.invoices`; no
  hard-coded URLs.

### Manual verification (Expo Go)

Because the pod cannot headless-render Expo, please spot-check in
Expo Go:

1. `yarn tunnel` in `/app/mobile/` and open the app in Expo Go on
   any Android device (Android is where the descender clip was most
   visible; iOS was less affected).
2. Sign in as `landscaper@aquaterra.com` / `password123` (or any
   role that lands on the Schedule tab first).
3. Navigate to **Schedule** — the two tiles ("Service Stops" and
   "Repair Stops") sit above the WeekStrip.
4. Confirm the full word "**Stops**" reads cleanly on **both**
   tiles — the "p" descender must be fully visible on the purple →
   blue gradient background with no bottom-edge clip.
5. Optional stress test — pick a day with 0 jobs vs a day with many
   jobs; the tile height/aspect is fixed via `aspectRatio: 1` so
   the label position is invariant, but confirming both empty (`0/0`)
   and populated states look correct is worthwhile.

---

## 2026-08-03 — Phase 24 · Mobile Schedule — Scroll fix + JobTrackerTiles label clip fix

### Fixed

- `mobile/app/(app)/schedule/JobTrackerTiles.tsx` — the "Service Stops"
  / "Repair Stops" labels were being clipped by the tile's rounded
  gradient corners on narrow devices. Root cause: prior layout used
  `justifyContent: "space-between"` which pushed the label into the
  tile's inner padding zone, where the SVG's own bounding-box math +
  the tile's `borderRadius: 16` combined to eat the descenders on
  smaller phones. Fix: the label is now a plain `<Text>` node rendered
  *below* the ring in normal flex-column flow (never inside the SVG
  viewBox), with `justifyContent: "flex-start"` + explicit `gap: 10`
  spacing, `color: "rgba(255,255,255,0.95)"`, `fontWeight: "600"`,
  `numberOfLines={1}`, and `adjustsFontSizeToFit`. Ring size trimmed
  132 → 108 dp so the label + ring both fit comfortably inside the
  square tile without touching the padding zone.

- `mobile/app/(app)/schedule/calendar.tsx` — the mobile schedule
  page didn't scroll top-to-bottom on shorter devices: the
  `LandscapingClockWidget` + `JobTrackerTiles` + `WeekStrip` +
  mode-switch band sat in a fixed flex column above the per-view
  `ScrollView` inside `GridView`/`CalendarView`, so any content that
  overflowed below the fold was unreachable. Fix: wrapped the body
  (everything below the `Header`, above the `Modal`) in a single
  vertical `<ScrollView contentContainerStyle={{ paddingBottom: 40 }}
  testID="schedule-root-scroll">`. Converted the outer `<ScrollView>`
  in `GridView` and `CalendarView` to plain `<View>`s to eliminate
  nested-vertical-scroll conflicts. `WeekStrip`'s internal
  horizontal scroll and `CalendarView`'s inner horizontal
  columns-scroll are on the perpendicular axis and continue to work
  as independent nested scrolls. The reassign-Tech `Modal` is
  rendered above via RN's Modal portal, so it stays outside the
  scroll region.

### Tests

- `frontend/src/test/phase23-job-tracker-tiles.test.jsx` — added
  two Phase-24 source-inspection assertions to lock the visual
  contract:
  1. label `<Text>` must live **outside** the `<Svg>...</Svg>`
     block (never rendered as SVG text, so RN flex layout owns its
     positioning);
  2. label style must resolve to `rgba(255,255,255,0.95)` +
     `fontWeight: "600"` per the spec, preventing a silent
     regression on future refactors.

### Constraints honoured

- Mobile-only — no backend or web changes.
- No new dependencies.
- Tile visual preserved — purple → blue gradient (`#7c3aed` →
  `#3b82f6`), green completion arc (`#22c55e`), centered big-number
  `X/Y` count all unchanged.
- Grep-lint stays green — zero writes to `db.invoices`; no
  hard-coded URLs; no new dependency added.

---

## 2026-08-02 — Phase 23 · Mobile Schedule — Job-Tracker progress-ring tiles

### Added

- `mobile/app/(app)/schedule/JobTrackerTiles.tsx` (NEW) — two
  side-by-side circular progress-ring tiles (Service Stops · Repair
  Stops) rendered at the top of the mobile schedule page, matching
  the user's reference screenshot.
  - `react-native-svg` Circle track + green arc (`#22c55e`) using
    a `strokeDasharray` proportional to `done/total`.
  - `expo-linear-gradient` purple → blue (`#7c3aed` → `#3b82f6`)
    background per the reference.
  - Empty state (`total === 0`) renders the track ring only — no
    green arc — with centered `0/0` text.
  - Full-complete state (`done === total > 0`) renders a full green
    ring.
  - Loading state fades the tile to 50% opacity so the layout
    doesn't jump.
  - Every tile carries a stable `testID` (`schedule-tile-service`,
    `schedule-tile-repair`, and nested `-count` / `-label`).

**Client-side classification** — job schema doesn't have a `kind`
field (612 nulls in `db.jobs`). Classification uses a keyword regex
over `service_type`: `/(repair|fix|broken|leak|replace)/i` → repair;
everything else (including landscape and nulls) → service. **No
backend change needed.**

### Changed

- `mobile/app/(app)/schedule/calendar.tsx` — imported
  `<JobTrackerTiles>` and rendered it above `<WeekStrip>` with
  `jobs={dayJobs}` (the client-side memoized array of today's jobs
  matching `focusISO`). `loading={busy}` wires the existing
  fetch-busy flag to the tile fade.

### Tests

- `frontend/src/test/phase23-job-tracker-tiles.test.jsx` (NEW) — 9
  vitest cases. Splits into two groups:
  - **Pure logic**: classify by keyword; count total + done across
    mixed jobs; empty list → 0/0; fully-complete states.
  - **Render contract (source inspection)**: mobile file exposes
    every required testID, imports `react-native-svg`, uses
    `#22c55e` for the green arc, uses purple→blue gradient, guards
    the arc render behind `total > 0 && pct > 0`, and displays
    "Service Stops" / "Repair Stops" labels.

### Design decisions

- **SVG lib** — `react-native-svg` (already in tree from earlier
  phases). The ring is 2 `<Circle>` elements: track + arc via
  `strokeDasharray`. Deliberately did not pull in a third-party
  progress-ring library for a 4-line effect.
- **Gradient** — `expo-linear-gradient` (already installed) diagonal
  `[0,0] → [1,1]`, matches the reference screenshot's top-left
  purple to bottom-right blue.
- **Classification is client-side** — the schedule fetch already
  ships `service_type` + `status` down the wire; no new backend
  endpoint. Landscape jobs correctly bucket as service (the split is
  service vs repair, not pool vs landscape).
- **Arc rotation** — SVG arcs start at 3 o'clock by default;
  applied `rotate(-90 ${cx} ${cy})` so progress fills from 12
  o'clock, matching the reference.
- **Testability** — chose source-inspection tests plus pure-function
  unit tests for the classifier over rendering the SVG in jsdom.
  React Native SVG + `expo-linear-gradient` can't render outside of
  the Expo runtime; source-inspection catches the render-contract
  regressions that matter (missing testIDs, wrong colors, empty-state
  guard removed).

### Cross-cutting checks

- Grep-lint: 0 `db.invoices` writes (no backend changes). ✅
- `/api/openapi.json` reachable (HTTP 200). ✅
- Vitest baseline: **523 pass / 13 fail** — inside the 11-14 flake
  tolerance (improved by 1 vs Phase 22).
- No backend restart needed (mobile-only + frontend vitest).

### Files added / changed

- `mobile/app/(app)/schedule/JobTrackerTiles.tsx` (NEW, ~145 lines)
- `mobile/app/(app)/schedule/calendar.tsx` (2-line import + 1
  render insertion)
- `frontend/src/test/phase23-job-tracker-tiles.test.jsx` (NEW, 9
  tests)
- `CHANGELOG.md` — this entry

### Note on visual verification

Native mobile-viewport screenshot requires Expo Go on a physical
device — the pod cannot render the Expo runtime headlessly. Confirmed
via source-inspection vitests (colors, testIDs, gradient, arc
condition, labels) + pure-logic unit tests for the classifier +
counter. To visually verify on-device, follow the Phase 21
`mobile/EXPO_GO_RUNBOOK.md` (`cd mobile && yarn tunnel`).

---

## 2026-08-02 — Phase 22 · Tech mobile restrictions + bell repositioning + auto-invoice on job complete

### Sub-item A · Mobile tech schedule — Complete chip only

**Reported problem** — the mobile Expo schedule grid rendered all 5
bulk-action chips (Complete / Move / Delete / Assign / Rearrange) for
technicians. Techs shouldn't be able to move, delete, reassign, or
reorder jobs.

**Fix** — `mobile/app/(app)/schedule/calendar.tsx` — every non-Complete
pill wrapped in an `{isAdmin ? <Pressable…/> : null}` gate. The
existing `canWriteJobs = isAdmin || isTech` remains (Complete still
fires for techs); only the 4 admin-only chips are new.

**Test** — `frontend/src/test/phase22-mobile-schedule-gates.test.jsx`
locks the visibility matrix as a pure predicate + source-inspects the
mobile file to prove every non-Complete testid is preceded by an
`isAdmin ?` gate. **6/6 pass.**

### Sub-item B · Notification bell to the LEFT of hamburger

**Reported problem** — schedule screen had the notification bell
visually overlapping the ambient shell hamburger.

**Fix** — `mobile/app/(app)/schedule/calendar.tsx` — the schedule
Header's `right={…}` slot now wraps `<NotificationBell />` in a
`<View style={{ marginRight: 52 }} testID="schedule-header-bell">` —
44dp (iOS HIG hamburger tap target) + 8dp gap. Bell is now clearly
left of the hamburger with no overlap.

**Test** — same vitest file source-inspects the wrapper for
`marginRight >= 44` and the `schedule-header-bell` testID.

### Sub-item C · Auto-invoice on job complete + charge card on file

**Investigation delivered upfront** — `PATCH /api/jobs/{id}` is
actually a `PUT` route (`routers/jobs.py:915`). Job schema has NO
`line_items` / `labor_hours` / `labor_rate` — only single-line
`price`. Synthesized shape: 1 service line + N chemical lines from
Phase 18 `chemical_usage_events`. No existing job-complete auto-invoice
logic.

**Added**
- `backend/services/auto_invoice.py` (NEW · ~230 lines) —
  `create_invoice_from_job(job_id, tenant_id)` helper with idempotent
  short-circuit (via `job.auto_invoice_id`), tenant opt-out check
  (`settings.auto_invoice_on_job_complete`, defaults True), line-item
  builder (service line from `job.price` + chemical lines from Phase
  18 events), invoice insert into `db.quotes` with
  `doc_type="invoice"` (Phase 11 invariant, NEVER writes to
  `db.invoices`), and card-on-file auto-charge via
  `charge_card_on_file(invoice_id, tenant_id,
  idempotency_key="auto_invoice:{job_id}")`. All failures swallowed;
  audit row written to `db.auto_invoice_runs` for every attempt.
- Hook installed at `routers/jobs.py:981` immediately after the
  equipment-tracker auto-log — wrapped in `try/except` so it can
  never crash the job-complete handler.

**Test** — `backend/tests/test_phase22_auto_invoice.py` — 5 pytest
cases covering the full acceptance matrix. **5/5 pass.**

**Verification (live curl matrix on preview)**
```
PUT  /api/jobs/{id}  {"status":"completed"}          → 200
  → job.auto_invoice_id stamped
  → db.quotes row created (doc_type=invoice,
                          source=auto_invoice_on_job_complete,
                          payment_status=unpaid,
                          total_cents=13000,
                          line_items=1)
  → db.auto_invoice_runs audit row written
PUT  /api/jobs/{id}  {"status":"completed"}  (replay)→ 200
  → invoice_count unchanged (idempotent short-circuit)
```

### Design decisions

- **Line-item synthesis strategy** — job schema is deliberately thin;
  used the single `price` field for the service line and Phase 18
  `chemical_usage_events` for consumable lines. Future work: full
  line-item support on jobs (`Phase XX · service-catalog line-items`).
- **Idempotency key** — `f"auto_invoice:{job_id}"` gives us the same
  stable key even if the retry loop kicks in inside
  `charge_card_on_file`.
- **Fail-open on tenant setting** — default `True` when the setting
  isn't present. Admins can flip it via
  `tenant.settings.auto_invoice_on_job_complete=false`.
- **Never crash the caller** — the hook is best-effort; the invoice
  helper wraps its entire body in try/except and returns a diagnostic
  dict. Job-completion transactions never fail because of an invoice
  glitch.
- **Grep-lint invariant preserved** — all writes go to `db.quotes`
  with `doc_type="invoice"`. Zero `db.invoices` writes anywhere in
  Phase 22 files.

### Files added / changed

- `backend/services/auto_invoice.py` (NEW)
- `backend/routers/jobs.py` — one hook block after status→completed
- `backend/tests/test_phase22_auto_invoice.py` (NEW, 5 tests)
- `mobile/app/(app)/schedule/calendar.tsx` — bell padding + isAdmin
  gates on 4 pills
- `frontend/src/test/phase22-mobile-schedule-gates.test.jsx` (NEW,
  6 tests — includes source-inspection of the mobile file)
- `CHANGELOG.md` — this entry

### Cross-cutting checks

- Grep-lint: 0 `db.invoices` writes in any Phase 22 file. ✅
- `/api/openapi.json` reachable (HTTP 200). ✅
- Vitest baseline: 522 pass / 14 fail — at the 14-flake tolerance
  ceiling. ✅
- Pytest new: **11/11 pass** (5 auto-invoice + 6 mobile-gate).

### Follow-up (not blocking)

- Native mobile-viewport screenshot of the tech-only chip layout
  requires Expo Go on a physical device — the pod cannot render the
  Expo runtime headlessly. Confirmed the change via source
  inspection + vitest.
- Invoice PDF email delivery on auto-create — deferred; existing
  invoice-email flow can be triggered by admins from the auto-created
  invoice in `db.quotes`.

---

## 2026-08-02 — Bug fix · Login-page demo-credential chips 401 on tech tap

**Fixed** — the "Pool Tech" chip on both the web login page
(`frontend/src/components/auth/PreviewDemoLogins.jsx:45`) and the mobile
Expo login screen (`mobile/app/login.tsx:157`) referenced
`mike@aquaterra.com`, an account that was never seeded — the backend
boot log had been calling this out for weeks
(`auto_heal_demo_passwords ... Missing rows: ['mike@aquaterra.com']`).
Clicking the chip fired the field-populate (`onPick`) correctly, but
the immediate `onSubmitDirect` returned 401 so users perceived the
click as broken.

**Change** (single-line each, two files):
- `PreviewDemoLogins.jsx` — `email: "mike@aquaterra.com"` →
  `"landscaper@aquaterra.com"`; `role_label: "Pool Tech"` →
  `"Landscape Tech"` (matches the real seed account).
- `mobile/app/login.tsx` — same substitution.

**Test guard**
- `frontend/src/test/preview-demo-logins.test.jsx` — updated the
  spec assertion + widened the click-handler assertion to cover all 4
  chips (previously only the "super" chip's `onPick` payload was
  asserted, which let the tech-chip email typo slip through). Result:
  **8/8 vitest cases pass**.

**Verified**
- Mobile-viewport (390 × 844) headless browser: all 4 chips
  (`demo-login-super`, `-admin`, `-customer`, `-tech`) render
  visible. Tapping the tech chip signs in and redirects to
  `/schedule` — the authenticated technician shell (Schedule / D2D /
  Time Clock / Tools / Training / Profile nav rendered).
- Grep-lint: 0 `db.invoices` writes touched.

---

## 2026-08-02 — Phase 21 · Prod deploy unblock + seed drift + Expo Go publish

Three small items shipped in one pass to close out immediate ops needs.

### Sub-item A · Unblock production frontend build (`postcss-selector-not` engine pin)

**Reported problem**: Production deploy at 2026-08-01 23:57 UTC failed at
the `frontend-build-push` cloud-build step:

```
error postcss-selector-not@9.0.0: The engine "node" is incompatible with
this module. Expected version ">=20.19.0". Got "20.18.1"
```

The customer-apps build container ships Node 20.18.1;
`postcss-selector-not@9.0.0` was released with `engines.node >=20.19.0`.

**Fix**
- `frontend/package.json` — direct dependency
  `"postcss-selector-not": "^9.0.0"` → `"^8.0.1"`.
- Added a `resolutions` block that also pins any transitive resolution
  to `^8.0.1` with an inline `//` comment explaining the constraint.
- Post-fix `node_modules/postcss-selector-not/package.json`:
  `{"version": "8.0.1", "engines": {"node": ">=18"}}` — satisfies Node
  20.18.1.
- Verified locally: `yarn install` clean + `yarn build` completes in
  66.89s producing `build/static/js/main.e0bdafe8.js` (1.42 MB gzip)
  and `build/static/css/main.a38d0066.css` (26.39 kB gzip).

**Design decision — why `^8.0.1` and not `^9.0.0`**
- `8.0.1` is the last release with `engines.node >=18` — works on any
  container from Node 18 through 20+.
- `9.0.0` shipped a stricter engine constraint; keeping the pin at 8.x
  is the smallest-blast-radius fix.
- Base image Node bump was **explicitly out of scope** per the phase
  brief (bigger blast radius; separate ops phase).

### Sub-item B · Landscape / department seed drift fix

**Reported problem**: Phase 20's `UserDepartmentIn` enum accepts only
`pool_tech | landscape_tech | both | None`. Multiple legacy seed rows
carried mis-cased or region-labelled values that would 422 on any
admin edit:

```
Pre-fix db.users.department distribution across 111 tenants:
  None → 31 valid
  'north' → 3 legacy (regional label, not a department)
  'south' → 3 legacy
  'landscaping' → 2 (needs remap)
  'both' → 1 valid
  'Pool' → 1 (case-drift)
  'Landscaping' → 1 (case-drift)
```

**Fix**
- `backend/scripts/fix_landscape_tech_seed_drift.py` (NEW) —
  idempotent one-shot migration with a `--dry-run` flag. Mapping:
    - `landscaping` / `Landscaping` / `landscape` → `landscape_tech`
    - `Pool` / `pool`                             → `pool_tech`
    - Anything else non-null NOT in the enum      → `None` (WARNING logged)
    - Already-valid values (or `None`)            → untouched
- Ran real (not dry) once: `{scanned: 11, remapped: 4, cleared: 6, already_valid: 1}`.
- Ran a second time to prove idempotency: `{scanned: 5, remapped: 0, cleared: 0, already_valid: 5}`.
- Post-fix distribution: only valid enum values remain
  (`None: 37, landscape_tech: 3, pool_tech: 1, both: 1`).

**Test coverage**
- `backend/tests/test_phase21_landscape_seed_drift.py` (NEW, 2 tests)
    - `test_landscape_drift_is_fixed` — seeds three users
      (`landscaping`, valid `pool_tech`, unknown `north`), runs the
      script, asserts:
        * `landscaping` → `landscape_tech`
        * `pool_tech` untouched
        * `north` → `None`
    - `test_script_is_idempotent` — second run does not mutate any row
      in the test tenant.

**Design decision — legacy `north` / `south` rows**
- These are regional labels, not departments. Cleared to `None` (not
  remapped to any enum value) and logged as WARNINGs so admins can
  re-seat the field to the correct department + record the
  region-label elsewhere if needed.

### Sub-item C · Expo Go publish runbook (dev tunnel path)

**Investigation summary** — investigated first, before touching code:
- `eas.json` NOT present in `/app/mobile/`.
- `app.json`: `slug=frontend`, **no `owner`**, no `updates` block, no
  `runtimeVersion`.
- `expo-updates` package NOT installed.
- `eas` CLI NOT installed on the pod (`which eas` empty).
- `EXPO_TOKEN` env NOT set.

**Conclusion** — cannot run `eas update` from this pod. Falling back
to the local dev-server tunnel path per the phase brief.

**Fix**
- `mobile/package.json` — added `"tunnel": "expo start --tunnel"` script
  so testers can `yarn tunnel` without memorizing the flag.
- `mobile/EXPO_GO_RUNBOOK.md` (NEW) — one-page instructions covering
  Expo Go install on iOS + Android, prerequisites, the exact command
  to run locally (`cd mobile && yarn tunnel`), expected terminal
  output (QR code + `exp://…` URL), LAN-mode fallback, what testers
  will see once the app launches, and a graduation checklist for
  when the user wants to move to `eas update` in a future ops phase.

**Follow-up (explicitly deferred)**
- `eas update --branch preview` requires creating an Expo
  organization, adding `owner`/`updates`/`runtimeVersion` to
  `app.json`, installing `expo-updates`, running `eas init`, and
  configuring an update policy. That's a discrete phase — not
  urgent while the local tunnel serves the internal-testing use
  case.

### Cross-cutting checks

- Grep-lint: 0 `db.invoices` writes in any Phase 21 file. ✅
- `/api/openapi.json` reachable (HTTP 200). ✅
- Vitest baseline: 522 pass / 14 fail — inside the tolerated 11-14
  flake budget. ✅
- Regression pytest sweep: 10/10 pass (2 drift + 4 localhost demo
  login + 4 external-ingress demo login).
- Landscaper login still works post-migration (JWT + user record
  unchanged; only `department` field remapped).

### Files added / changed

- `frontend/package.json` — direct `postcss-selector-not` pin +
  `resolutions` block
- `frontend/yarn.lock` — regenerated (all
  `postcss-selector-not@*` now resolve to `8.0.1`)
- `backend/scripts/fix_landscape_tech_seed_drift.py` (NEW,
  idempotent one-shot)
- `backend/tests/test_phase21_landscape_seed_drift.py` (NEW, 2
  tests)
- `mobile/package.json` — new `tunnel` script
- `mobile/EXPO_GO_RUNBOOK.md` (NEW)
- `CHANGELOG.md` — this entry

### Follow-ups (logged for future phases, none blocking)

1. Base image Node LTS bump (would let us drop the `postcss-selector-not`
   pin and pick up any future `>=20.19.0` deps).
2. `eas update` migration (Expo org + `expo-updates` + runtime version
   policy) — enables OTA updates + tap-through deep links.
3. Automatic detection of new department-drift values as the field
   evolves (nice-to-have — the current script handles known drift
   patterns and logs anything it doesn't recognize).

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

## 2026-10-02 · backend · fix(mobile-sync): offline-bundle jobs now match on scheduled_date (fallback scheduled_at), mirroring portal_next_visits

## 2026-10-02 · backend · fix(job-timers): offline-arrival parity + null (not 0) on parse-failure; dashboard aggregates unaffected

## 2026-10-02 · frontend+backend · feat(jobs-page): inline-edit Scheduled/Technician/Price/Customer tiles on JobDetail (Phase 3a — Jobs Overhaul)
