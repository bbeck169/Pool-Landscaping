# Phase I1.7.d · Feb-2026 — Tenant Payments BYO Providers + Unified Provider-Health Cron

**Ships:** Cleanup C1 (calendars authz skips closed), Cleanup C2 (explicit `connection_type` in `/schemas`), and Phase I1.7.d (Square / PayPal / Authorize.Net / Lumino BYO adapters + unified health cron).

---

## What shipped

### C1 — Calendars OAuth authz tests
Previous session closed the 2 skipped OAuth authz tests by adding shared multi-technician fixtures to `conftest.py` and unskipping them. Verified this session: **20 pass, 0 skip** in `test_i17c3_calendars_byo_providers.py`.

### C2 — Explicit `connection_type` in `/schemas`
`ProviderSchema.connection_type: "api_key" | "oauth" | "oauth_connect"` now surfaced on every provider entry in `GET /api/tenants/me/integrations/schemas`. Calendars (`calendars_google`, `calendars_outlook`) declare `"oauth"`; SMS / Email / AI / Maps declare `"api_key"`. Test: `test_i17c2_schemas_connection_type.py`.

### I1.7.d — Payments BYO
* New subpackage `services/payments_byo/` (parallel to `services/ai`, `services/maps`, `services/calendars`) with:
    * `PaymentsByoProvider` ABC — `create_charge`, `refund_charge`, `verify_webhook`, `test_connection`
    * 4 adapters: `SquareProvider`, `PayPalProvider`, `AuthorizeNetProvider`, `LuminoProvider` (each mock-short-circuits when `PAYMENTS_TESTMODE_MOCK=true`)
    * Registry + models + usage (per-op `charge_count` / `refund_count` / `ops_total`) + cap enforcement (null=unlimited, 0=block-all, hard 429 at cap, soft warn at 80%)
    * Uniform preserve-secret + cap-only-edit semantics via `save_provider_config` + existing `_preserve_stored_secrets`
* New endpoints (all under `/api/tenants/me/integrations`):
    * `PUT  /pay_{provider}` — save encrypted config + sidecar meta
    * `DELETE /pay_{provider}` — clears `tenant_secrets` + `tenant_payments_provider`
    * `POST /pay_{short}/webhook?tenant_id=…` — signed verify (Square HMAC-SHA256 over `body`; PayPal cert-based or HMAC-SHA256 in mock mode; Authorize.Net HMAC-SHA512 `sha512=…`; Lumino HMAC-SHA256)
    * `POST /pay_{short}/test-connection` — per-provider health probe; records to `tenant_provider_health`
    * `GET  /payments/usage` — one row per provider with `charge_count`, `refund_count`, `pct_used`, `status`
* `/schemas` — new `payments: []` array with `connection_type=api_key` per entry
* `/integrations` — response augmented with top-level `health: { provider_key: {status, checked_at, last_error, consecutive_failures, last_ok_at} }`

### Unified `tenant_provider_health` cron
* One service (`services/provider_health/`), one worker, one collection.
* Cycles across **AI + Maps + Calendars + Payments-BYO** every `PROVIDER_HEALTH_CRON_INTERVAL_SECONDS` (default 900 = 15 min).
* Started once on FastAPI startup via `start_health_cron()` (idempotent). Disable with `PROVIDER_HEALTH_CRON_DISABLED=true`.
* Redacts `Authorization: Bearer`, `api_key=`, `access_token=` from any probe message before persistence.

### Frontend
* `HealthDot` component (green / red / amber) on **every** integration card — Stripe, SMS, Email, AI (×3), Maps (×2), Calendars (×2), Payments (×4).
* New `PaymentsCard` component mirroring `MapsCard` — form inputs per field, monthly-request-cap input, Save / Test connection / Disconnect buttons.
* Root component fetches `/payments/usage` in parallel with existing calls; passes `health[provider_key]` into every card.

---

## Files touched

### Backend (new)
* `services/payments_byo/__init__.py`
* `services/payments_byo/models.py`
* `services/payments_byo/tenant_base.py`
* `services/payments_byo/_helpers.py`
* `services/payments_byo/registry.py`
* `services/payments_byo/usage.py`
* `services/payments_byo/square_provider.py`
* `services/payments_byo/paypal_provider.py`
* `services/payments_byo/authnet_provider.py`
* `services/payments_byo/lumino_provider.py`
* `services/provider_health/__init__.py`
* `services/provider_health/store.py`
* `services/provider_health/cron.py`
* `backend/tests/test_i17c2_schemas_connection_type.py`
* `backend/tests/test_i17d_payments_byo_providers.py`

### Backend (edited)
* `backend/routers/tenant_integrations.py` — `payments_byo` branch in `_kind_for` / `_resolve_provider` / PUT / DELETE, new `PaymentsCard` endpoints, `/schemas.payments`, `/integrations.health`
* `backend/server.py` — startup hook that calls `start_health_cron()`
* `backend/.env` — added `PAYMENTS_TESTMODE_MOCK=true` for preview

### Frontend (new)
* `frontend/src/test/i17d-payments-byo-card.test.jsx`

### Frontend (edited)
* `frontend/src/components/settings/TenantIntegrationsCard.jsx` — `HealthDot`, `PAYMENTS_PROVIDER_LABELS`, `PaymentsCard`, health-dot injected next to every existing StatusPill

---

## Test results

Backend (all I1.7.* + C2):
```
test_i17a_integrations_endpoint.py .....
test_i17b_provider_registry.py .......
test_i17c1_ai_byo_providers.py ..........
test_i17c2_maps_byo_providers.py ..........
test_i17c2_schemas_connection_type.py .
test_i17c3_calendars_byo_providers.py ....................
test_i17d_payments_byo_providers.py .................
== 84 passed ==
```

Frontend (all i17*):
```
i17a-integrations-page.test.jsx      9 tests
i17b-sms-card.test.jsx               8 tests
i17b-email-card.test.jsx             7 tests
i17b-stale-badge.test.jsx            3 tests
i17c1-ai-byo-card.test.jsx          12 tests
i17c2-maps-byo-card.test.jsx        10 tests
i17c3-calendars-byo-card.test.jsx   12 tests
i17d-payments-byo-card.test.jsx      7 tests   ← new
== 68 passed ==
```

---

## Explicitly out-of-scope (deferred to I1.7.e)
* Rewiring existing `/payments/charge` / invoice callsites to dispatch through the BYO adapters — the platform Stripe Connect flow (I1.7.a) still owns the charge path today.
* Dollar-amount caps — this phase is request-count only.
* Real (non-mock) API calls in preview — `PAYMENTS_TESTMODE_MOCK=true` short-circuits everything.

---

## Environment
* Preview: `PAYMENTS_TESTMODE_MOCK=true`, `PROVIDER_HEALTH_CRON_INTERVAL_SECONDS=900` (default), `PROVIDER_HEALTH_CRON_DISABLED` unset.
* Production: user should set `PAYMENTS_TESTMODE_MOCK=false` (or unset) once real Square/PayPal/AuthNet/Lumino credentials are ready to route real charges.
