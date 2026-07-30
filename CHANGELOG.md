# Changelog

All notable changes to Pool & Landscaping CRM are documented here.

Format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).
Entries are dated (YYYY-MM-DD, UTC) since we're not cutting semver releases yet.
Do not rewrite history — only prepend new entries at the top.

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
