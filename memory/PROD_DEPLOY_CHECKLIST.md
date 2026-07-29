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
| `SUPERCOOL_MCP_URL` / `SUPERCOOL_DAILY_IMAGE_LIMIT` | optional | Supercool integration | — |
| `TEST_LLM_MOCK` | no | Must be **false/absent** on Prod | — |
| **`MAPBOX_ACCESS_TOKEN`** | **RESERVED — not yet wired** | Placeholder for Phase G3 reverse-geocoding. Set now if you want to be ready; nothing currently reads it. `gps_settings.geocoder = "mapbox"` is defaulted but the actual geocode call is not shipped. | — |

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
Moderation, Widget Embed, SEO Auditor, Keyword Ideation, Client Errors),
**Marketing → Outreach** (Prospects, Templates). Click one card / one row in each
page to make sure the detail view renders.

If any step above fails, do NOT declare deploy complete — bisect back to the phase in
"New API Endpoints" and investigate that router / its cron / its env vars.
