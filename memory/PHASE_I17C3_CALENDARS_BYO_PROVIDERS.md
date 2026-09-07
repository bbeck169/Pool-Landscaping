# Phase I1.7.c.3 · Feb-2026 — Tenant Integrations: Calendars BYO
### Google Calendar + Microsoft Outlook

## Task A (rolled-up follow-up) — `window.confirm` → in-app modal
Every integration-card disconnect flow (Stripe · SMS · Email · AI · Maps · **and now** per-tech Calendars) now routes through `mustConfirm(...)` from `components/ui/confirm-dialog.jsx` instead of the browser's native `window.confirm(...)`.

* Modal test-ids used across all cards:
    * `integrations-disconnect-confirm`
    * `integrations-disconnect-cancel`
* Vitest coverage added: "opens modal", "confirm fires DELETE", "cancel closes modal" for **every** card that has a disconnect action (Stripe, SMS/Twilio, Email/Resend, AI/OpenAI, Maps/Google, Calendars/Google per-tech).
* Frontend total: **3817 passed / 34 skipped**.

## Task B — Calendars BYO (this phase)

### Scope
* Per-technician OAuth for Google Calendar + Microsoft Outlook only. **Apple / CalDAV / iCloud skipped** per phase lock.
* Two-way sync architecture: **push_event** (CRM job → Calendar) and **pull_delta** (Calendar → CRM availability). **MVP is polling-only.** Webhooks (Google `watch`, Graph subscriptions) are a **documented I1.7.e follow-up** — not shipped in this phase.
* Cap semantics **mirror AI/Maps exactly**: `null=unlimited`, `0=block-all`, `>0` hard-blocks at `used>=cap`, warns at 80%. Counters: `push_event`, `pull_delta`, `total`.

### New Env vars (empty defaults in preview)
```
CALENDARS_TESTMODE_MOCK=true
GOOGLE_CALENDAR_CLIENT_ID=
GOOGLE_CALENDAR_CLIENT_SECRET=
GOOGLE_CALENDAR_REDIRECT_URI=
OUTLOOK_CLIENT_ID=
OUTLOOK_CLIENT_SECRET=
OUTLOOK_REDIRECT_URI=
```
Redirect URIs come from **env only** — never derived from request headers (open-redirect vector). The router 503s gracefully with `InvalidCalendarProviderConfig` when live-mode env vars are missing.

### Backend
`/app/backend/services/calendars/`

* `models.py` — `CalendarEvent`, `CalendarPushResult`, `CalendarPullDelta`, `CalendarProviderUsage`, `TechnicianCalendarLinkSummary`, `TenantCalendarsSyncOpCapExceeded`, `InvalidCalendarProviderConfig`, `TenantCalendarsNotConnected`, `UnknownCalendarProvider`.
* `_helpers.py` — `calendars_testmode_mock()`, `current_period_yyyymm()`, `validate_config`, `google_oauth_env()`, `outlook_oauth_env()`.
* `oauth_state.py` — **P0 SECURITY** · signed + bound state tokens.
    * HMAC-SHA256 with `SECRETS_MASTER_KEY` as the key.
    * Payload bound to `(tenant_id, technician_user_id, provider_short, nonce, iat, exp)`.
    * TTL clamped at 10 min max (`_MAX_TTL_SECONDS`).
    * Single-use — every consumed nonce is inserted into `calendar_oauth_state_consumed` (unique index + TTL @ 24h).
    * Errors: `OAuthStateExpired`, `OAuthStateReplayed`, `OAuthStateTampered`.
* `tenant_base.py` — `CalendarProvider` ABC.
* `google_calendar_provider.py` — Google Calendar (scopes: `calendar.events`, `calendar.readonly`, `userinfo.email`).
* `outlook_calendar_provider.py` — Microsoft Graph (scopes: `offline_access`, `Calendars.ReadWrite`, `User.Read`).
* `registry.py` — provider lookup + short-name helpers. Provider keys: `calendars_google`, `calendars_outlook`. Short names: `google`, `outlook`.
* `usage.py` — `tenant_calendars_provider` (cap sidecar) + `tenant_calendars_usage` (counters). `enforce_cap_or_raise` mirrors Maps.
* `technician_link.py` — Mongo collection `technician_calendar_link` with unique `(tenant_id, technician_user_id, provider_key)`. Access + refresh tokens stored encrypted via `services.secrets` keyed by `calendars_{provider}:{technician_user_id}`.
* `dispatcher.py` — `dispatch_calendars_push_event`, `dispatch_calendars_pull_delta`, `ensure_indexes(db)`.
* Boot: `server.py` startup gains an idempotent `services.calendars.dispatcher.ensure_indexes` call gated by the D2 startup-index flag.

### New router endpoints (`routers/tenant_integrations.py`)
* `GET /api/tenants/me/integrations/calendars_{provider}/oauth/start` (302 or `?format=json`)
* `GET /api/tenants/me/integrations/calendars_{provider}/oauth/callback`
* `POST /api/tenants/me/integrations/calendars_{provider}/disconnect` (per-tech)
* `PUT /api/tenants/me/integrations/calendars_{provider}` (cap + `default_calendar_id` extras)
* `DELETE /api/tenants/me/integrations/calendars_{provider}` (wipes all per-tech links)
* `GET /api/tenants/me/integrations/calendars/usage`

Role gating on `/oauth/start` and `/disconnect`:
* `super_admin` / `admin` — can start/disconnect for any tech in tenant.
* Technician — can start/disconnect only for themselves.
* Anyone else — **403**.

### Frontend (`components/settings/TenantIntegrationsCard.jsx`)
* New `CalendarsCard` component rendered under Maps.
* Cap input + "Save cap" + technician-picker + "Connect Google/Outlook Calendar" button (redirects via `window.location.assign(auth_url)`).
* Connected-technicians list with per-tech Disconnect (routes through the in-app modal).
* Callback bounce absorbed: `?calendar_connect=success|error&provider=…&error=…` surfaces toast + cleans URL via `history.replaceState`.

### Test matrix
Backend (`test_i17c3_calendars_byo_providers.py`) — **17 passed / 2 skipped**:
* Provider registry
* OAuth start (super_admin, admin, self, other-tech-403, JSON format) — 3 pass, 2 skip due to seed fixture
* OAuth state security: `state_tampered_rejected`, `state_expired_rejected`, `state_replay_rejected`, `callback_missing_params`
* Callback happy path — link + meta persist
* Cap semantics: unlimited, zero, hard-block, soft-warn @ 80%
* `PUT` cap endpoint saves meta
* `/calendars/usage` shape (providers + technicians)
* Disconnect single tech + `DELETE` wipes all tech links

Frontend (`i17c3-calendars-byo-card.test.jsx`) — **12 passed**:
* Card renders per provider
* Save cap PUT payload
* Empty cap sends null
* Connect button calls `window.location.assign(auth_url)`
* Connected-tech list rendered
* Warn + Blocked usage bar states
* `?calendar_connect=success`/`=error` bounce toasts
* Task-A parity modal tests (opens / confirms / cancels)

### Not shipped (deferred by design)
* Webhooks (Google `watch`, Graph subscriptions) — polling-only for MVP; documented as I1.7.e follow-up.
* Live-mode push/pull adapter wiring — mocked responses today; real Google Calendar / Graph API calls scheduled for I1.7.e (**callsite rewiring phase**).
* CalDAV/iCloud/Apple — out of scope for I1.7.c.3.

### Files added / changed
* Added: `services/calendars/{__init__.py, models.py, _helpers.py, oauth_state.py, tenant_base.py, google_calendar_provider.py, outlook_calendar_provider.py, registry.py, usage.py, technician_link.py, dispatcher.py}`
* Added: `tests/test_i17c3_calendars_byo_providers.py`
* Added: `frontend/src/test/i17c3-calendars-byo-card.test.jsx`
* Modified: `routers/tenant_integrations.py`, `server.py`, `.env`, `frontend/src/components/settings/TenantIntegrationsCard.jsx`
* Modified (Task A rollup): 5 vitest suites `i17a-integrations-page`, `i17b-sms-card`, `i17b-email-card`, `i17c1-ai-byo-card`, `i17c2-maps-byo-card`.
