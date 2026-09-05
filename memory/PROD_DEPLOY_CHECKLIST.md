# Prod Deploy Checklist — 2026-08-01 (Phase 12 · Deployment Readiness Audit)

## Go/No-Go recommendation

**GO with conditions** — all shipped features (Phases 1-11) are prod-ready. Zero deployment blockers. Two non-blocking warnings + several INFO items listed below.

## Per-phase readiness

| Phase | Feature | Status | Notes |
|---|---|---|---|
| P1  | Widget Analytics (MR3) | ✅ prod-ready | `POST /public/widget/analytics/track` requires `event_type` + `session_id` fields (schema is stricter than the smoke script currently assumes — updated in `PROD_SMOKE.sh`). Rate-limit enforced. |
| P2  | Share-Replay + GPS Read Lockdown | ✅ prod-ready | `POST /gps/replay/share` schema uses `{user_id, replay_date}`. Public `/api/public/replay/*` returns 404 as designed. |
| P3  | Dispatch Route Optimize | ✅ prod-ready | 404 `no_jobs_for_tech_on_date` is a valid semantic response for empty seeds. Tech/customer 403 verified. |
| P4  | Drag-Drop Auto-Insert + Batch Preview | ✅ prod-ready | |
| P5a | AEO Auditor / JSON-LD / LLMs.txt | ✅ prod-ready | `POST /aeo/jsonld/generate` requires `types` array. |
| P5b | AI Visibility + Fixes | ✅ prod-ready | Manager-tenant probe returned 200 with `skipped_reason`; cost cap wired. |
| P5c | Brand Mentions | ✅ prod-ready | Returns `provider_configured=false` when Serper/Google CSE keys absent per-tenant. |
| P6  | Reputation Response Drafts | ✅ prod-ready | 404 on bad mention_id; EMERGENT_LLM_KEY present in .env so no 503. |
| P7  | Weekly Scorecard Digest | ✅ prod-ready | `preview` is a `GET` (not `POST`). |
| P8  | Weekly AEO PDF Digest | ✅ prod-ready | Signed URL round-trip verified; PDF starts with `%PDF-1.4`, 2368 bytes. HMAC valid+tampered+expired+cross-tenant all correctly enforced. |
| P9  | LLMs.txt Auto-Publish | ✅ prod-ready | `not_configured` responses correct for tenants without provider keys. |
| P10 | Response Library + Batch Preview Pills + Savings KPI | ✅ prod-ready | |
| P11 | Invoice dual-collection refactor | ✅ prod-ready | Reconciliation-log endpoint enforces super-admin; `find_invoice_dual` deprecation fires once per boot. |

## Env vars required for prod deploy

### Backend (`/app/backend/.env`) — REQUIRED (blockers if missing)
- `MONGO_URL` — SET
- `DB_NAME` — SET
- `JWT_SECRET` — SET (used as HMAC fallback for Phase 8 signed URLs)
- `EMERGENT_LLM_KEY` — SET (Phase 5b visibility, 5b fixes, Phase 6 drafts)
- `RESEND_API_KEY` + `RESEND_FROM` — SET (Phase 7 + Phase 8 email delivery)
- `MAPBOX_ACCESS_TOKEN` — SET (route-map / GPS features)
- `CORS_ORIGINS` — SET (currently `*`; **WARN**: tighten before public prod)

### Backend — OPTIONAL / FEATURE-GATED
- `AEO_VISIBILITY_CRON_HOUR_UTC` — default 07:00 UTC
- `AEO_MENTIONS_CRON_HOUR_UTC` — default 08:00 UTC
- `AEO_VISIBILITY_MONTHLY_CAP_USD` — feature-gated cost cap
- `AEO_MENTIONS_MONTHLY_CAP_USD` — feature-gated cost cap
- `LUMINO_API_TOKEN` — SET; `LUMINO_ZAPIER_SHARED_SECRET` — SET
- `LUMINO_API_URL` — **MISSING** (used by reconciler; parked externally per session note)
- `LUMINO_WEBHOOK_SECRET` — **MISSING** (webhook validator; parked per session note)
- `RC_*` (RingCentral) — all SET
- `WORDPRESS_*` — all SET
- `GOOGLE_MAPS_API_KEY` / `GOOGLE_API_KEY` — SET
- `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` — SET
- `WEATHERAPI_KEY` — SET
- `OPENWEB_NINJA_API_KEY` (Zillow adapter) — SET
- `ZAPIER_INVOICE_LINK_WEBHOOK_URL` — SET (parked externally per session note)

### Per-tenant configuration (each tenant sets independently in the admin UI)
- **Slack webhook URL** (Phase 7 scorecard delivery)
- **Serper.dev key** OR **Google CSE key + CX** (Phase 5c mentions)
- **AEO visibility enabled toggle** + **AEO mentions enabled toggle**
- **Scorecard digest schedule** (DOW + hour + recipients)
- **AEO PDF digest schedule** (DOW + hour + recipients + include-negative-snippets)
- **LLMs.txt publish provider config** (Netlify/Vercel/Cloudflare Pages PAT + site/project id)

### Deprecated / removed
- `STRIPE_*` — removed (LZ4 in a prior session); frontend `.env` still ships `REACT_APP_STRIPE_PUBLISHABLE_KEY` — **INFO**, safe to leave for now, remove during next cleanup pass.
- `db.invoices` writes — retired (Phase 11); grep-lint pytest enforces the guard.

## Blocker / Warning / Info summary

**BLOCKERS**: none.

**WARNINGS**:
1. `CORS_ORIGINS=*` — permissive. Tighten to the public prod origin before general release.
2. Mongo compound indexes missing on 15 of 17 Phase 1-11 collections. See §5 in the audit report. Not a data-integrity risk today (row counts are low: `quotes=588, widget_analytics_events=311, route_optimize_events=17`, everything else <30). Add before scaling past ~10 tenants or ~100k events.

**INFO**:
1. `LUMINO_API_URL` + `LUMINO_WEBHOOK_SECRET` unset — the parked Lumino/Zapier reconciler path is inert until these are supplied. This is expected per the pre-session inbox item that keeps Lumino/Zapier parked.
2. Historical Lumino `paid_at` drift on the ~466 pre-refactor invoices remains unreconciled — a separate follow-up phase will backfill from `db.payment_events`. Called out in the `GET /api/admin/invoice-reconciliation-log` response body.
3. Frontend `REACT_APP_STRIPE_PUBLISHABLE_KEY` is a dangling artifact from LZ4 (Stripe SDK was removed). No consumer in the current code — safe to drop in the next cleanup pass.
4. Backend `APP_BASE_URL` unset — used only if a code path needs to build absolute URLs; nothing today depends on it.
5. Vitest baseline 13/537 failing — inside the accepted 11-14 tolerance since Phase 8. Zero Phase 1-11-authored tests among the failures.

## Verification data appended to `PROD_SMOKE.sh`

Added Phase 1-11 curl checks at the bottom of the smoke script. See §10 in the audit report.

---

# Prod Deploy Checklist — 2026-07-29

## Summary

This session shipped the LZ5 Lumino backfill utility, Phase P1 (Dispatch board mobile
bugfix + client-side error diagnostics), P2 (live GPS pins on Dispatch), Task 5
(payments summary re-added post-LZ4 + RingCentral SSE churn gating), Phase PB1 (internal
Profit Report, admin-only), Phase G0/G1/G2 (GPS driver tracking foundation, ingest,
settings, server-side stop-detection batch + Driver Activity timeline), Phase MR0
(public check-in submission + admin moderation queue with address masking), Phase
MR1+MR2 (public embeddable widget with Shadow DOM + JSON-LD + admin embed preview),
Phase MR-QoL (bulk approve/reject + AI Rewrite wiring on the moderation surface), and
the three free-tier SEO phases: SEO-A (on-page SEO auditor with PageSpeed + robots +
security headers), SEO-B (backlink outreach CRM reusing Resend), and SEO-C (keyword
ideation via Google Autocomplete + pytrends Google Trends). LZ4 (Stripe SDK removal)
was completed in a prior session and is included here only for env-var / dependency
reference. Everything is preview-only until this sync.

## Session Guardrails (Held Across Full G3–G5d Track)

The following guardrails held for the entire session and are worth capturing for the
handoff:

- **No external repo cloning.** Multiple attempts to pull code from GitHub were
  refused across context restarts; nothing from an external repo was ever copied
  into `/app`.
- **No mobile touches from `e1_dev`.** All mobile work went through the Expo
  specialist during earlier phases; `/app/mobile/` was untouched throughout the
  G3–G5d track.
- **No LZ4 / LZ5 / AB1 / PB1 / PB1-M / MR0 / MR1+MR2 / MR-QoL / SEO-A / SEO-B /
  SEO-C code paths modified** during G3–G5d. Those surfaces stayed frozen; the only
  changes below live under new files or new endpoints on the GPS track.
- **Preview only.** Prod (`app.plofv.com`) was never touched by this agent. Every
  landing catalogued below was shipped and verified on the preview environment
  only.

## New / Modified Backend Files

### LZ4 (context — prior session)
| Path | Change | Purpose |
|---|---|---|
| `backend/server.py` | modified | Removed Stripe cron blocks (signposts kept as comments) |

### LZ5 — Lumino payment-link backfill (super-admin only)
| Path | Change | Purpose |
|---|---|---|
| `backend/routers/lumino_backfill.py` | added | Manual Lumino payment-link backfill endpoints |

### P1 — Dispatch board mobile fix + client-error diagnostics
| Path | Change | Purpose |
|---|---|---|
| `backend/routers/client_errors.py` | added | `POST /api/client-errors` + admin list view |
| `backend/server.py` | modified | Registered client_errors router |

### Task 3 — `GET /api/users?role=technician`
| Path | Change | Purpose |
|---|---|---|
| `backend/routers/admin_users.py` | modified | Fixed 405 on role filter |

### P2 — Live GPS positions on Dispatch
| Path | Change | Purpose |
|---|---|---|
| `backend/routers/gps_live_positions.py` | added | `GET /api/gps/live-positions` |

### Task 5 — Payments summary + SSE noise gate
| Path | Change | Purpose |
|---|---|---|
| `backend/routers/payments_summary.py` | added (re-added post-LZ4) | `GET /api/payments/summary` tile data |
| `backend/routers/ringcentral*.py` | modified | SSE disconnect log gating |

### PB1 — Profit Report
| Path | Change | Purpose |
|---|---|---|
| `backend/routers/profit_report.py` | added | Internal profit report endpoints (admin-only) |
| `backend/tests/test_profit_report.py` | added | pytest coverage |

### G0/G1/G2 — GPS driver tracking + stop detection
| Path | Change | Purpose |
|---|---|---|
| `backend/routers/gps_ingest.py` | added | `POST /api/gps/pings` batch ingest |
| `backend/routers/gps_settings.py` | added | Tenant GPS settings CRUD |
| `backend/routers/gps_stops.py` | added | Stop-detection query endpoints |
| `backend/services/gps_stop_detector.py` | added | Pure stop-detection algorithm |
| `backend/services/gps_stops_batch.py` | added | 3-minute cron batch processor |
| `backend/services/stop_geo.py` | added | Haversine helpers |
| `backend/tests/test_gps_ingest.py` | added | pytest |
| `backend/tests/test_gps_settings.py` | added | pytest |
| `backend/tests/test_gps_stops.py` | added | pytest |
| `backend/tests/test_gps_stop_detector.py` | added | Unit tests for the pure algorithm |

### MR0 — Public check-in moderation
| Path | Change | Purpose |
|---|---|---|
| `backend/routers/public_checkins.py` | added | Tech submit → moderation pipeline |
| `backend/routers/moderation_public_checkins.py` | added | Admin queue list/detail/patch/approve/reject/unpublish |
| `backend/services/address_masker.py` | added | House-number-stripping helper |
| `backend/tests/test_public_checkins.py` | added | pytest |

### MR1+MR2 — Public widget
| Path | Change | Purpose |
|---|---|---|
| `backend/routers/public_widget.py` | added | Public feed + `widget.js` script + admin preview |
| `backend/tests/test_public_widget.py` | added | pytest (feed + script + JSON-LD parity) |

### MR-QoL — Bulk actions + AI Rewrite
| Path | Change | Purpose |
|---|---|---|
| `backend/routers/moderation_public_checkins.py` | modified | Bulk approve/reject endpoints |
| `backend/routers/checkin_rewrite.py` | added | `POST /api/checkins/rewrite-description` (Emergent LLM) |
| `backend/tests/test_moderation_bulk.py` | added | pytest |

### SEO-A — Free on-page SEO auditor
| Path | Change | Purpose |
|---|---|---|
| `backend/services/seo_scanner.py` | added | Pure scanner (autocomplete, PSI, schema, robots, security) |
| `backend/routers/seo_scans.py` | added | 5 endpoints |
| `backend/tests/test_seo_scanner.py` | added | Unit + live-server tests |

### SEO-B — Backlink outreach CRM
| Path | Change | Purpose |
|---|---|---|
| `backend/routers/outreach.py` | added | 13 endpoints (prospects, templates, send, followups, pipeline) |
| `backend/services/outreach_followups.py` | added | Daily follow-up digest cron |
| `backend/tests/test_outreach.py` | added | pytest |

### SEO-C — Keyword ideation
| Path | Change | Purpose |
|---|---|---|
| `backend/services/keyword_ideator.py` | added | Google Autocomplete matrix + pytrends |
| `backend/routers/keywords.py` | added | 3 endpoints (ideate, history, lookup) |
| `backend/tests/test_keyword_ideator.py` | added | Unit + live-server tests |

### G3 — Reverse-geocoding for stops (Mapbox)
| Path | Change | Purpose |
|---|---|---|
| `backend/services/reverse_geocoder.py` | added | Mapbox reverse-geocode client with in-DB cache + graceful degrade when `MAPBOX_ACCESS_TOKEN` is unset |
| `backend/routers/gps_stops.py` | modified | Attach `address` string to stop rows when cache hit / on-demand fetch |
| `backend/routers/gps_settings.py` | modified | `GET /api/admin/gps/settings` now returns `mapbox_token_configured: bool` (env-read on every call — no restart needed to pick up the token) |
| `backend/tests/test_reverse_geocoder.py` | added | pytest (cache hit, cache miss, missing-token graceful degrade) |

### G4 — GPS route rendering
| Path | Change | Purpose |
|---|---|---|
| `backend/routers/gps_route.py` | added | `GET /api/gps/route` — polyline + stops for a driver/day |
| `backend/tests/test_gps_route.py` | added | pytest |

### G5a — Geofences + entry/exit alerts
| Path | Change | Purpose |
|---|---|---|
| `backend/routers/geofences.py` | added | Geofence CRUD + entry/exit event query |
| `backend/services/geofence_engine.py` | added | Point-in-polygon + hysteresis state machine (hooked into the G2 stop-detection batch) |
| `backend/tests/test_geofences.py` | added | pytest (CRUD + entry/exit trigger logic) |

### G5b — Auto job attribution
| Path | Change | Purpose |
|---|---|---|
| `backend/routers/stop_attribution.py` | added | Attribution config + manual batch trigger |
| `backend/services/stop_attribution.py` | added | Match stops → jobs by proximity + same-day window; writes `attributed_job_id` / `attributed_customer_id` / `attribution_status` back onto `driver_stops` |
| `backend/routers/gps_stops.py` | modified | Search filters (`?q=`, `?attributed_only=`) + customer-name join on GPS report rows |
| `backend/tests/test_stop_attribution.py` | added | pytest |

### G5c — Route Replay animation meta
| Path | Change | Purpose |
|---|---|---|
| `backend/routers/gps_route.py` | modified | Extended response with `playback_duration_s` for animated replay clients |
| `backend/tests/test_gps_route_replay.py` | added | pytest |

### G5d — Driver Scorecard / Leaderboard
| Path | Change | Purpose |
|---|---|---|
| `backend/routers/driver_scorecard.py` | added | Leaderboard + per-user scorecard endpoints with TTL cache |
| `backend/services/scorecard_compute.py` | added | Pure scoring / aggregation engine (stops, on-time %, dwell, attribution rate, geofence entries) |
| `backend/tests/test_driver_scorecard.py` | added | pytest |

## New / Modified Frontend Files

### P1
| Path | Change | Purpose |
|---|---|---|
| `frontend/src/components/ErrorBoundary.jsx` | added | Global React error boundary, reports to `/api/client-errors` |
| `frontend/src/pages/admin/AdminDiagnosticsErrorsPage.jsx` | added | Admin viewer for client-side errors |

### P2
| Path | Change | Purpose |
|---|---|---|
| `frontend/src/pages/DispatchBoard.jsx` | modified | Poll `/api/gps/live-positions` and render tech pins |

### G2
| Path | Change | Purpose |
|---|---|---|
| `frontend/src/pages/admin/DriverActivityPage.jsx` | added | Timeline view of server-detected stops |
| `frontend/src/pages/admin/AdminGpsSettingsPage.jsx` | added | Tenant GPS settings admin |
| `frontend/src/test/driver-activity-page.test.jsx` | added | vitest |
| `frontend/src/test/gps-settings-page.test.jsx` | added | vitest |

### MR0
| Path | Change | Purpose |
|---|---|---|
| `frontend/src/pages/admin/ModerationCheckinsPage.jsx` | added | Two-panel moderation UI (later extended in MR-QoL) |
| `frontend/src/components/checkins/SubmitToPublicButton.jsx` | added | Tech-side "submit for public display" action |
| `frontend/src/test/moderation-queue.test.jsx` | added | vitest |
| `frontend/src/test/moderation-actions.test.jsx` | added | vitest |

### MR1+MR2
| Path | Change | Purpose |
|---|---|---|
| `frontend/src/pages/admin/WidgetEmbedPage.jsx` | added | Live widget preview with copy-paste snippet |
| `frontend/public/widget.js` | added | Standalone Shadow-DOM widget script |
| `frontend/src/test/widget-embed-page.test.jsx` | added | vitest |
| `frontend/src/test/widget-script.test.js` | added | vitest for widget.js |

### MR-QoL
| Path | Change | Purpose |
|---|---|---|
| `frontend/src/pages/admin/ModerationCheckinsPage.jsx` | modified | Bulk-select + Action bar + AI Rewrite wiring |
| `frontend/src/components/ai/AIDescriptionRewriteButton.jsx` | added | Reusable AI rewrite pill |
| `frontend/src/test/moderation-bulk.test.jsx` | added | vitest |
| `frontend/src/test/moderation-ai-rewrite.test.jsx` | added | vitest |

### SEO-A
| Path | Change | Purpose |
|---|---|---|
| `frontend/src/pages/admin/SeoAuditorPage.jsx` | added | URL scan UI + score gauge + section detail + history |
| `frontend/src/test/seo-auditor-page.test.jsx` | added | vitest |

### SEO-B
| Path | Change | Purpose |
|---|---|---|
| `frontend/src/pages/admin/outreach/ProspectsKanbanPage.jsx` | added | dnd-kit Kanban + drawers + send/import modals |
| `frontend/src/pages/admin/outreach/TemplatesPage.jsx` | added | Template CRUD + variable palette |
| `frontend/src/test/outreach-prospects.test.jsx` | added | vitest |
| `frontend/src/test/outreach-send.test.jsx` | added | vitest |

### SEO-C
| Path | Change | Purpose |
|---|---|---|
| `frontend/src/pages/admin/KeywordIdeatorPage.jsx` | added | Autocomplete + Trends + tabs UI |
| `frontend/src/test/keyword-ideator-page.test.jsx` | added | vitest |

### G3 — Reverse-geocoded addresses on stops
| Path | Change | Purpose |
|---|---|---|
| `frontend/src/pages/admin/DriverActivityPage.jsx` | modified | Render reverse-geocoded address labels on stop rows |
| `frontend/src/pages/admin/AdminGpsSettingsPage.jsx` | modified | Show `mapbox_token_configured` badge |

### G4 — GPS route rendering on Driver Activity
| Path | Change | Purpose |
|---|---|---|
| `frontend/src/hooks/useGpsRoute.js` | added | Reusable fetcher for `/api/gps/route` |
| `frontend/src/pages/admin/DriverActivityPage.jsx` | modified | Render map polyline + stop pins |

### G5a — Geofences
| Path | Change | Purpose |
|---|---|---|
| `frontend/src/pages/admin/GeofencesPage.jsx` | added | Google Maps `DrawingManager` custom drawing UI + CRUD |
| `frontend/src/test/geofences-page.test.jsx` | added | vitest |

### G5b — Attribution + GPS report search filters + customer names
| Path | Change | Purpose |
|---|---|---|
| `frontend/src/pages/admin/DriverActivityPage.jsx` | modified | Search bar + customer name / job link columns |
| `frontend/src/pages/admin/StopAttributionSettingsPage.jsx` | added | `proximity_threshold_m` + `same_day_only` config + manual run-batch button |
| `frontend/src/test/driver-activity-search.test.jsx` | added | vitest |

### G5c — Route Replay panel
| Path | Change | Purpose |
|---|---|---|
| `frontend/src/pages/admin/RouteReplayPanel.jsx` | added | Animated polyline playback with play / pause / speed on the Driver Activity map |
| `frontend/src/test/route-replay-panel.test.jsx` | added | vitest |

### G5d — Driver Scorecard / Leaderboard
| Path | Change | Purpose |
|---|---|---|
| `frontend/src/pages/admin/DriverScorecardPage.jsx` | added | Leaderboard + per-driver detail + `recharts` trend lines + custom date-range picker |
| `frontend/src/test/driver-scorecard-page.test.jsx` | added | vitest |

### Cross-cutting
| Path | Change | Purpose |
|---|---|---|
| `frontend/src/App.js` | modified | Route registrations for every new page above |
| `frontend/src/nav/adminNav.js` | modified | Sidebar entries (see below) |

## Mobile Files

Session guardrail was "do NOT touch mobile". `/app/mobile/` was not modified this
session. The Expo companion app already carries the following (verify against previous
sessions' M3/PB1-M/G1 phase notes if attribution is needed):

| Dep in `mobile/package.json` | Version | Used for |
|---|---|---|
| `expo-location` | `~19.0.8` | G1 GPS ping ingestion |
| `expo-file-system` | `~19.0.23` | Attachment upload |
| `expo-document-picker` | `~14.0.8` | Doc attachments |
| `expo-image-picker` | `~17.0.11` | Photo capture / attachments |

Prod mobile build/OTA cadence is out of scope for this checklist — this document
covers the web/API deploy only.

## New Backend Collections

| Collection | Created via | Indexes | Purpose |
|---|---|---|---|
| `client_errors` | first write in `routers/client_errors.py` | `(tenant_id, ts desc)` (auto) | React ErrorBoundary reports |
| `gps_pings` | first write in `routers/gps_ingest.py` | `(tenant_id, user_id, ts desc)` (auto) | Raw GPS pings, retained 30 days |
| `gps_settings` | first write in `routers/gps_settings.py` | `(tenant_id)` unique | Per-tenant GPS config (enabled, retention, geocoder) |
| `driver_stops` | first write in `services/gps_stops_batch.py` | `(tenant_id, user_id, started_at desc)` (auto) | Server-detected stop segments |
| `gps_stops_batch_meta` | cron `gps_stops_batch_processor` | `(tenant_id)` (auto) | Per-tenant watermark of last processed batch |
| `public_checkins` | `routers/public_checkins.py` | `(tenant_id, state, submitted_at desc)`, `(tenant_id, source_checkin_id)` unique | Tech-submitted → moderation pipeline |
| `audits` | `routers/audits.py` (LZ4 audit webhook) | `(tenant_id, created_at desc)` | Lumino webhook audit log |
| `lumino_link_requests` | `routers/lumino_link_request.py` (LZ2/3) | `(tenant_id, invoice_id, created_at desc)` | Zapier bridge request log |
| `invoice_edit_history` | `routers/invoice_edit.py` | `(tenant_id, invoice_id, edited_at desc)` | Invoice edit trail |
| `service_categories` | `routers/service_categories.py` | `(tenant_id, slug)` unique | Per-tenant service catalog |
| `income_categories` | `routers/income_categories.py` | `(tenant_id, key)` unique | CFO income tagging |
| `seo_scans` | `routers/seo_scans.py` | `(tenant_id, requested_at desc)`, `(tenant_id, target_url, requested_at desc)` | SEO-A on-page audits |
| `outreach_prospects` | `routers/outreach.py` | `(tenant_id, status, last_activity_at desc)`, `(tenant_id, domain)` | Backlink outreach CRM |
| `outreach_templates` | `routers/outreach.py` | `(tenant_id, name)` | Reusable outreach emails |
| `outreach_messages` | `routers/outreach.py` | `(tenant_id, prospect_id, sent_at desc)` | Per-send log |
| `keyword_lookups` | `routers/keywords.py` | `(tenant_id, seed_keyword, region, language)` unique | 24h cached keyword ideation results |
| `keyword_search_history` | `routers/keywords.py` | `(tenant_id, user_id, requested_at desc)` | Rate-limit counter + per-user search trail |
| `reverse_geocode_cache` | first write in `services/reverse_geocoder.py` | `(lat_bucket, lng_bucket)` compound, `(expires_at)` TTL | G3 — cached Mapbox reverse-geocode results |
| `geofences` | `routers/geofences.py` | `(tenant_id, active)` | G5a — polygon boundaries |
| `geofence_events` | `services/geofence_engine.py` | `(tenant_id, user_id, ts desc)`, `(tenant_id, geofence_id, ts desc)` | G5a — entry/exit event log |
| `geofence_state` | `services/geofence_engine.py` | `(tenant_id, user_id, geofence_id)` unique | G5a — hysteresis state per (user, fence) |
| `stop_attribution_meta` | `routers/stop_attribution.py` | `(tenant_id)` unique | G5b — per-tenant config (`proximity_threshold_m`, `same_day_only`) |
| `scorecard_cache` | `routers/driver_scorecard.py` | `(tenant_id, cache_key)` unique, `(expires_at)` TTL | G5d — leaderboard TTL cache |

> **G5b extension of existing `driver_stops`**: existing rows in `driver_stops` now
> also carry `attributed_job_id`, `attributed_customer_id`, and
> `attribution_status` once the attribution batch has run for that stop. No
> destructive migration — fields are additive and default to null on legacy rows.

> **Note on indexes**: MongoDB creates indexes lazily. If you want them upfront on Prod,
> run a one-time script that calls `create_index(...)` on each collection with the
> tuples above. Everything works without explicit indexes; queries will still hit
> `tenant_id` filters first.

## Env Variables — What Prod Must Have

| Var | Required | Notes | Default if applicable |
|---|---|---|---|
| `MONGO_URL` | yes | Existing | — |
| `DB_NAME` | yes | Existing | — |
| `JWT_SECRET` | yes | Must be ≥32 chars in `APP_ENV=production` (fail-loud) | — |
| `APP_ENV` | yes | Set to `production` on Prod (was `preview` here) | `preview` |
| `APP_PUBLIC_URL` | yes | Prod's external URL | — |
| `EMERGENT_LLM_KEY` | yes | Used by AI Rewrite (MR-QoL) | — |
| `RESEND_API_KEY` | yes | Used by SEO-B outreach sends + digest cron | — |
| `RESEND_FROM` | yes | Sender identity | `onboarding@resend.dev` |
| `EMAIL_FROM` | yes | Existing | `onboarding@resend.dev` |
| `LUMINO_API_TOKEN` | yes | `sk_live_` prefix is legit per user (Lumino uses `sk_live_*` for live tokens; NOT a Stripe key) | — |
| `LUMINO_API_URL` | yes | Existing | — |
| `LUMINO_RETURN_URL` | yes | Existing | — |
| `LUMINO_WEBHOOK_SECRET` | yes | Existing | — |
| `LUMINO_ZAPIER_SHARED_SECRET` | yes | LZ2/3 bridge auth — confirm present in Prod .env | — |
| `ZAPIER_INVOICE_LINK_WEBHOOK_URL` | yes | LZ2 dispatcher — rotate if regenerated; user confirmed working in preview | — |
| `RC_JWT` / `RC_CLIENT_ID` / `RC_CLIENT_SECRET` / `RC_SERVER_URL` / `RC_FROM_NUMBER` | yes | RingCentral | — |
| `RC_WEBHOOK_URL` / `RC_VERIFICATION_TOKEN` / `RINGCENTRAL_WEBHOOK_TOKEN` | yes | RC webhooks | — |
| `RC_MODE` / `RC_OUTBOUND_ENABLED` / `RC_SMS_DEFAULT_FROM` / `RC_VOICE_DEFAULT_FROM` | yes | RC channel config | — |
| `GOOGLE_MAPS_API_KEY` | yes | Existing | — |
| `GOOGLE_API_KEY` | yes | Existing | — |
| `OPENWEB_NINJA_API_KEY` / `OPENWEB_NINJA_ZILLOW_API_KEY` | optional | Property lookup | — |
| `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` | optional | Legacy SEO tools (not SEO-A/B/C) | — |
| `WEATHERAPI_KEY` | yes | Existing | — |
| `WORDPRESS_URL` / `WORDPRESS_USERNAME` / `WORDPRESS_APP_PASSWORD` / `WORDPRESS_AUTO_PUBLISH` | optional | WordPress push | — |
| `CHECKS_ENCRYPTION_KEY` | yes | Check writer encryption | — |
| `MCP_TOKEN_ENCRYPTION_KEY` | yes | MCP OAuth cache | — |
| `CORS_ORIGINS` | yes | Existing | — |
| `ALLOW_TEST_HOOKS` | no | Must be **absent or false** on Prod | — |
| `SHOW_DEMO_LOGINS` | no | Must be **false** on Prod to hide the demo-login pills | — |
| `SEED_DEMO_USERS` | no | Must be **false** on Prod | — |
| `DEMO_AUTOHEAL` | no | Must be **false** on Prod | — |
| `AI_VISIBILITY_CRON_ENABLED` | optional | Toggle per environment | — |
| `RANK_TRACKER_CRON_ENABLED` | optional | Toggle per environment | — |
| `PAYMENT_PROVIDER` | yes | Set to `lumino` post-LZ4 | — |
| `PAYMENTS_TEST_ALLOWLIST_CUSTOMERS` | optional | Preview-only allowlist | — |
| `COMMS_TEST_ALLOWLIST_EMAILS` / `COMMS_TEST_ALLOWLIST_PHONES` | optional | Preview-only allowlist | — |
| `SUPERCOOL_MCP_URL` | **removed** | **DEPRECATED (K55.b · Feb-2026)** — Supercool retired. Do NOT set on Prod. | — |
| `SUPERCOOL_DAILY_IMAGE_LIMIT` | optional | **DEPRECATED (K56 · Feb-2026)** — migrate to `AI_MEDIA_DAILY_IMAGE_LIMIT`. Router dual-reads for one release cycle. | — |
| `AI_MEDIA_DAILY_IMAGE_LIMIT` | optional | Canonical name for the per-tenant daily image-gen cap (default 100). | — |
| `EMERGENT_IMAGE_MODEL` | optional | Emergent image-gen model id (default `gemini-3.1-flash-image-preview`; alt `gemini-3-pro-image-preview`). | — |
| `TEST_LLM_MOCK` | no | Must be **false/absent** on Prod | — |
| **`MAPBOX_ACCESS_TOKEN`** | recommended (wired in Phase G3) | Reverse-geocoding of stop coordinates. **Hot-picked-up:** if the user sets it later on Preview or Prod, `GET /api/admin/gps/settings` will immediately return `mapbox_token_configured: true` on the next request — **no backend restart required** for the value to be picked up. If unset, reverse-geocoding gracefully degrades (stops render lat/lng only, no address strings; no errors). | — |

**Env vars REMOVED (LZ4 Stripe purge — do not add these back on Prod):**
- `STRIPE_API_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_LIVE_KEY`

## Dependencies Added

**Backend `requirements.txt`** (SEO-C):
- `pytrends==4.9.2`
- `lxml==6.1.1` (transitive dep of pytrends)

**Frontend `package.json`**: No new npm deps this session. `@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities`, `recharts`, `sonner`, `lucide-react` were already installed and were reused for SEO-B (Kanban), SEO-A/C (charts), toasts, and icons.

**Mobile `package.json`**: Not modified this session. The Expo deps `expo-location`,
`expo-file-system`, `expo-document-picker`, `expo-image-picker` were added in prior
sessions (verify against the last mobile build tag).

## Dependencies REMOVED

**Backend** (LZ4 — verified: no `import stripe` remains in the codebase):
- `stripe==14.4.1`

**Frontend** (LZ4):
- `@stripe/react-stripe-js@6.8.0`
- `@stripe/stripe-js@9.10.0`

## Cron / Scheduled Jobs Added

All registered via APScheduler in `backend/server.py`. IDs are stable so
`replace_existing=True` is safe on redeploy.

| Job ID | Schedule | Purpose |
|---|---|---|
| `gps_pings_retention_purge` | daily 04:00 UTC | Purge `gps_pings` older than per-tenant retention |
| `gps_stops_batch_processor` | every 3 minutes | Server-side stop detection (G2). `max_instances=1, coalesce=True` |
| `outreach_daily_followup_digest` | daily 08:00 UTC | Email each tenant owner a summary of due outreach follow-ups |
| `stop_attribution_batch` | every 5 minutes | G5b — matches recent driver stops to jobs by proximity + same-day window. `max_instances=1, coalesce=True` |
| `reverse_geocode_cache_purge` | daily 04:30 UTC | G3 — evicts expired `reverse_geocode_cache` rows (belt-and-suspenders alongside the Mongo TTL index) |

Existing crons (not touched, listed for completeness): `seo_drip`, `chem_billing`,
`autobilling_daily`, `coverage_revert`, `late_fees`, `marketing_autopost`,
`sequences_tick`, `csat_dispatch`, `dunning_scan`, `weather_scan`, `churn_scan`,
`equipment_service_hourly`, `referral_watcher_hourly`, `weekly_digest`,
`weekly_bulk_digest`, `pool_service_weekly_email`, `monthly_pricing_digest`,
`muted_notification_digest`, `warranty_expiration_scan`, `recurring_job_generator`,
`rc_contact_pull_sync`, `ai_credits_monthly_reset`, `m5_daily_trigger_sweep`,
`m5_sequences_tick`, `m6_review_request_expiry`, `m6_review_request_tick`,
`gh0_widget_dev_seed`.

## New API Endpoints (grouped)

### P1 — Client errors
- `POST /api/client-errors`
- `GET  /api/admin/client-errors` (admin+ only)

### P2 — Live GPS
- `GET  /api/gps/live-positions`

### Task 5 — Payments
- `GET  /api/payments/summary`

### PB1 — Profit report (admin-only)
- `GET  /api/admin/reports/profit`
- `GET  /api/admin/reports/profit/jobs/{id}`
- (plus PB1 detail/export endpoints as registered in `routers/profit_report.py`)

### G0/G1 — GPS ingest + settings
- `POST /api/gps/pings`
- `GET  /api/admin/gps/settings`
- `PATCH /api/admin/gps/settings`

### G2 — Stop detection
- `GET  /api/admin/gps/driver-stops`
- `POST /api/admin/gps/stops/backfill` (manual trigger)

### MR0 — Public check-in moderation
- `POST /api/checkins/{id}/submit-public`
- `GET  /api/admin/moderation/public-checkins`
- `GET  /api/admin/moderation/public-checkins/{id}`
- `PATCH /api/admin/moderation/public-checkins/{id}`
- `POST /api/admin/moderation/public-checkins/{id}/approve`
- `POST /api/admin/moderation/public-checkins/{id}/reject`
- `POST /api/admin/moderation/public-checkins/{id}/unpublish`

### MR1+MR2 — Public widget
- `GET  /api/public/checkins/feed`
- `GET  /widget.js` (served from `frontend/public/` — no `/api` prefix)
- `GET  /api/admin/moderation/widget-embed/preview` (admin preview data)

### MR-QoL — Bulk moderation + AI Rewrite
- `POST /api/admin/moderation/public-checkins/bulk-approve`
- `POST /api/admin/moderation/public-checkins/bulk-reject`
- `POST /api/checkins/rewrite-description` (Emergent LLM)

### SEO-A — On-page SEO auditor
- `POST /api/seo/scans`
- `GET  /api/seo/scans`
- `GET  /api/seo/scans/history`
- `GET  /api/seo/scans/{id}`
- `POST /api/seo/scans/{id}/rerun`

### SEO-B — Outreach CRM (13)
- `POST /api/outreach/prospects`
- `GET  /api/outreach/prospects`
- `GET  /api/outreach/prospects/{id}`
- `PATCH /api/outreach/prospects/{id}`
- `DELETE /api/outreach/prospects/{id}`
- `POST /api/outreach/prospects/bulk-import` (multipart)
- `POST /api/outreach/prospects/{id}/status`
- `POST /api/outreach/prospects/{id}/send`
- `GET  /api/outreach/prospects/{id}/messages`
- `GET  /api/outreach/templates`
- `POST /api/outreach/templates`
- `PATCH /api/outreach/templates/{id}`
- `DELETE /api/outreach/templates/{id}`
- `GET  /api/outreach/followups`
- `GET  /api/outreach/pipeline`
- `POST /api/outreach/cron/followup-digest` (manual admin trigger)

### SEO-C — Keyword ideation
- `POST /api/keywords/ideate`
- `GET  /api/keywords/history`
- `GET  /api/keywords/lookup/{id}`

### G3 — Reverse-geocoding (no new public path)
- No new endpoints. `GET /api/admin/gps/driver-stops` rows now include an `address` string when the reverse-geocode cache is hit, and `GET /api/admin/gps/settings` returns `mapbox_token_configured: bool`.

### G4 — GPS route rendering
- `GET  /api/gps/route`

### G5a — Geofences + entry/exit alerts
- `POST /api/admin/gps/geofences`
- `GET  /api/admin/gps/geofences`
- `GET  /api/admin/gps/geofences/{id}`
- `PATCH /api/admin/gps/geofences/{id}`
- `DELETE /api/admin/gps/geofences/{id}`
- `GET  /api/admin/gps/geofence-events`

### G5b — Auto job attribution
- `GET  /api/admin/gps/attribution/settings`
- `PATCH /api/admin/gps/attribution/settings`
- `POST /api/admin/gps/attribution/run-batch` (manual trigger)
- (`GET /api/admin/gps/driver-stops` extended with `?q=`, `?attributed_only=`, and customer-name join on each row)

### G5c — Route Replay (extends G4)
- `GET  /api/gps/route` — response now carries `playback_duration_s` for animated replay clients

### G5d — Driver Scorecard / Leaderboard
- `GET  /api/admin/gps/scorecard/leaderboard`
- `GET  /api/admin/gps/scorecard/user/{user_id}`

## New Admin UI Routes / Sidebar Entries

| Route | Sidebar location | RBAC |
|---|---|---|
| `/admin/diagnostics/errors` | Reports → Client Errors | admin+ (`AdminOnly`) |
| `/admin/reports/driver-activity` | Reports → Driver Activity | admin+/manager |
| `/admin/settings/gps` | Operations → Settings → GPS Driver Activity | admin+ |
| `/admin/moderation/checkins` | Reports → Check-in Moderation | admin+/manager |
| `/admin/moderation/widget-embed` | Reports → Widget Embed | admin+/manager |
| `/admin/seo/auditor` | Reports → SEO Auditor | admin+/manager |
| `/admin/seo/keywords` | Reports → Keyword Ideation | admin+/manager |
| `/admin/outreach/prospects` | Marketing → Outreach → Outreach Prospects | admin+/manager |
| `/admin/outreach/templates` | Marketing → Outreach → Outreach Templates | admin+/manager |
| `/admin/gps/geofences` | Operations → GPS → Geofences | admin+/manager |
| `/admin/gps/attribution` | Operations → GPS → Attribution Settings | admin+ |
| `/admin/reports/driver-scorecard` | Reports → Driver Scorecard | admin+/manager |
| `/admin/tools/lumino-backfill` | Reports (hidden by default; super_admin) | super_admin only |

## Migration / Backfill Scripts to Run Once on Prod

Every script is idempotent and safe to re-run.

| Script | When | Purpose |
|---|---|---|
| `python backend/scripts/backfill_wholesale_price.py` | after deploy | Populate wholesale_price for existing product/service catalog entries |
| `python backend/scripts/backfill_persona_avatar_urls.py` | after deploy | AI persona avatars — safe idempotent |
| `python backend/scripts/reset_demo_passwords_to_default.py` | **NEVER on Prod** | Preview-only demo password reset |
| `python backend/scripts/rotate_demo_passwords.py` | **NEVER on Prod** | Preview-only |
| `python backend/scripts/seed_portal_media.py` | optional | Seeds portal media assets (skip if you already have real data) |

No collection migrations are required — new collections are created lazily on first
write. If you want the indexes listed under "New Backend Collections" upfront, create
them manually via `mongosh` or a one-off `create_index` script.

## Known Prod-side Actions the User Must Do

1. **Rotate `ZAPIER_INVOICE_LINK_WEBHOOK_URL`** if it was regenerated after the preview
   worked end-to-end. Push the new URL into Prod `.env`. Preview value confirmed
   working; do not blindly copy it if Prod's Zap is separate.
2. **Confirm `LUMINO_ZAPIER_SHARED_SECRET` is set in Prod `.env`.** LZ2/3 bridge auth
   depends on it. Preview accepts empty as a soft gate; Prod should have a value.
3. **`LUMINO_API_TOKEN`** — the `sk_live_*` prefix is legitimate for Lumino's live
   tokens (per user; not a Stripe key). Do not swap it out.
4. **`MAPBOX_ACCESS_TOKEN` is RESERVED but not wired.** Set it now in Prod `.env` if
   you want to be ready for Phase G3 (reverse-geocoding of stop coordinates). Nothing
   currently reads it; the app boots fine without it.
5. **HR agreements must be on file before flipping `gps_settings.enabled=true` per
   tenant.** The G0 admin UI enforces `hr_agreement_ack=true`; make sure the paper
   trail matches before any tech's phone starts sending pings.
6. **Verify tenant slugs are populated** for every tenant that intends to publish a
   public check-in widget. `public_checkins → approved` requires the tenant slug to
   render the widget feed correctly. Most were handled during MR1+MR2 rollout; verify
   with:
   ```
   db.tenants.find({ slug: { $in: [null, ""] } }, { name: 1 })
   ```
7. **Turn off preview-only env vars on Prod.** Ensure `SHOW_DEMO_LOGINS`,
   `SEED_DEMO_USERS`, `DEMO_AUTOHEAL`, `ALLOW_TEST_HOOKS`, `TEST_LLM_MOCK` are all
   **false or absent** in Prod `.env`.
8. **Deploy `frontend/public/widget.js` as a static asset** (not behind auth). It's a
   plain JS file served from the frontend origin — customers embed it via
   `<script src="https://<prod-domain>/widget.js" data-tenant="..." async>`.

## Test Credentials for Post-Deploy Smoke

**Preview only — do NOT use these on Prod.** If Prod has real accounts, substitute
your own. On preview:

- Super admin: `super@aquaterra.com` / `password123`
- Manager: `manager@aquaterra.com` / `password123`
- Customer: `customer@aquaterra.com` / `password123`

## Post-Deploy Smoke Test Checklist

Run against Prod's external URL (replace `$API` with `https://<your-prod-domain>/api`).
Every step should pass BEFORE announcing the deploy is live.

**Step 1: Health check.** `curl -s "$API/openapi.json" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(len(d["paths"]))'`  
Expected: prints a number ≥ 400 (total route count).

**Step 2: Login as admin.** `curl -s -X POST "$API/auth/login" -H 'Content-Type: application/json' -d '{"email":"<prod-admin>","password":"<prod-password>"}'`  
Expected: returns `{"access_token": "...", "user": {...}}`. Save the token.

**Step 3: Client errors router alive.** `curl -s "$API/admin/client-errors?limit=1" -H "Authorization: Bearer $TOKEN"`  
Expected: `{"items": [...], "total": N}` (P1 landed).

**Step 4: Live GPS positions endpoint alive.** `curl -s "$API/gps/live-positions" -H "Authorization: Bearer $TOKEN"`  
Expected: `{"positions": []}` when no techs are on shift, or a populated list otherwise (P2 landed).

**Step 5: Payments summary tile.** `curl -s "$API/payments/summary" -H "Authorization: Bearer $TOKEN"`  
Expected: JSON with money totals — NOT 404 (Task 5 landed).

**Step 6: Profit report loads.** `curl -s "$API/admin/reports/profit" -H "Authorization: Bearer $TOKEN"`  
Expected: 200 with a report body (PB1 landed).

**Step 7: GPS settings admin.** `curl -s "$API/admin/gps/settings" -H "Authorization: Bearer $TOKEN"`  
Expected: 200 with `{enabled, geocoder, ...}` (G0/G1 landed).

**Step 8: Moderation queue admin.** `curl -s "$API/admin/moderation/public-checkins?state=pending_review" -H "Authorization: Bearer $TOKEN"`  
Expected: `{"items": [...], "total": N}` (MR0 landed).

**Step 9: Public widget feed alive.** `curl -s "$API/public/checkins/feed?tenant=<your-prod-tenant-slug>&limit=5"`  
Expected: 200 with `{"items": [...]}` (MR1 landed). Also verify `https://<prod-domain>/widget.js` returns JavaScript (MR2 landed).

**Step 10: MR-QoL bulk endpoints alive.** `curl -s -X POST "$API/admin/moderation/public-checkins/bulk-approve" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"ids":["nonexistent"]}'`  
Expected: 200 with `{"approved":0,"skipped":1,...}` (MR-QoL landed).

**Step 11: SEO Auditor scan.** `curl -s -X POST "$API/seo/scans" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"target_url":"https://example.com","async":false}'`  
Expected: 200 with `{"scan_id":"...","status":"complete","results":{...}}` (SEO-A landed). PSI may return `pagespeed_error` — that's OK, the scan still completes.

**Step 12: Outreach pipeline counts.** `curl -s "$API/outreach/pipeline" -H "Authorization: Bearer $TOKEN"`  
Expected: 200 with `{"pending":N, "contacted":N, ..., "total":N}` (SEO-B landed).

**Step 13: Outreach cron fires on demand.** `curl -s -X POST "$API/outreach/cron/followup-digest" -H "Authorization: Bearer $TOKEN"`  
Expected: 200 with `{"tenants_scanned":N, "digests_sent":N, ...}`. Non-zero `digests_sent` requires Resend to be configured.

**Step 14: Keyword ideation runs.** `curl -s -X POST "$API/keywords/ideate" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"seed_keyword":"pool service <your-city>"}'`  
Expected: 200 with `autocomplete_suggestions`, `question_suggestions`, `comparison_suggestions`, `preposition_suggestions`, and `trends_summary` (SEO-C landed). Trends may error — that's OK.

**Step 15: Sidebar visual smoke.** Log into the admin UI as your Prod admin, expand
each of these menu groups, and verify no 404s: **Reports** (Driver Activity, Check-in
Moderation, Widget Embed, SEO Auditor, Keyword Ideation, Client Errors, **Driver
Scorecard**), **Operations → GPS** (**Geofences**, **Attribution Settings**),
**Marketing → Outreach** (Prospects, Templates). Click one card / one row in each
page to make sure the detail view renders.

**Step 16: GPS route rendering + Route Replay meta (G4 + G5c).** `curl -s "$API/gps/route?user_id=<tech-uid>&date=<YYYY-MM-DD>" -H "Authorization: Bearer $TOKEN"`  
Expected: 200 with `polyline`, `stops`, and **`playback_duration_s`** in the payload (G4 landed and the G5c extension shipped). An empty `polyline` is OK if that tech didn't move on that date.

**Step 17: Reverse-geocode wire status (G3).** `curl -s "$API/admin/gps/settings" -H "Authorization: Bearer $TOKEN" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("mapbox_token_configured=", d.get("mapbox_token_configured"))'`  
Expected: prints `mapbox_token_configured= True` if `MAPBOX_ACCESS_TOKEN` is set in Prod `.env`, otherwise `False`. **Either value is legal** — `False` means stops render lat/lng only (graceful degrade). If you set the token after this step, re-run the curl and it should flip to `True` **without a backend restart**.

**Step 18: Geofences + entry/exit events (G5a).** `curl -s "$API/admin/gps/geofences" -H "Authorization: Bearer $TOKEN"`  
Expected: `{"items":[...],"total":N}`. Then hit `curl -s "$API/admin/gps/geofence-events?limit=5" -H "Authorization: Bearer $TOKEN"` — expected `{"items":[...],"total":N}` (G5a landed). Empty lists are legal on a fresh install.

**Step 19: Attribution settings + batch runner (G5b).** `curl -s "$API/admin/gps/attribution/settings" -H "Authorization: Bearer $TOKEN"`  
Expected: 200 with `{"proximity_threshold_m":N,"same_day_only":true|false}`. Then `curl -s -X POST "$API/admin/gps/attribution/run-batch" -H "Authorization: Bearer $TOKEN"` — expected 200 with `{"stops_scanned":N,"stops_attributed":N,...}` (G5b landed). Non-zero `stops_attributed` requires driver stops **and** jobs in the same 24 h window.

**Step 20: Driver Scorecard leaderboard (G5d).** `curl -s "$API/admin/gps/scorecard/leaderboard?range=7d" -H "Authorization: Bearer $TOKEN"`  
Expected: 200 with `{"leaderboard":[...],"generated_at":"...","range":"7d"}` (G5d landed). An empty `leaderboard` is OK on a fresh install. Hit the same URL twice back-to-back — the second response should return quickly and carry the **same** `generated_at` value (confirming the `scorecard_cache` TTL cache is warm).

If any step above fails, do NOT declare deploy complete — bisect back to the phase in
"New API Endpoints" and investigate that router / its cron / its env vars.
