# Hotfix #3 · Feb-2026 — D2D existing-customer gate + Zillow property enrichment

## Summary

* **Part A** — Techs no longer see the "existing customers" panel/pins on the D2D map. Admin / super_admin / dispatcher keep them.
* **Part B** — All authenticated users (including techs) can pull Zillow property data for a D2D prospect / knock row via a "Pull property data" button. Cached per-address for 24h, rate-limited to 100 requests/hour per tenant.

## Part A — customer list gate

### Backend
* New endpoint `GET /api/d2d/customers-nearby` in `backend/routers/d2d.py` — returns customers with `lat`/`lng` for map plotting. Gated with a new `_require_admin_or_super` helper that raises 403 for anything other than `admin` / `super_admin` / `dispatcher`.
* The generic `/api/customers` endpoint is **not** touched. Techs still hit it for job-detail lookups (verified by `test_d2d_job_detail_lookups_still_work_for_tech`).

### Frontend
* `frontend/src/pages/d2d/D2dPages.jsx` · `D2dMap` — imports `useAuth`, derives `canSeeCustomers = ["admin", "super_admin", "dispatcher"].includes(user.role)`, and:
    * Skips the customer fetch entirely for techs.
    * Switches from `GET /customers` to `GET /d2d/customers-nearby` for authorized roles.

## Part B — Zillow property enrichment

### Backend
* **Service** — `backend/services/enrichment/zillow.py` — new `fetch_zillow_property(address, *, tenant_id, force_refresh=False)` function.
    * Reuses the existing `services.property_data.zillow_adapter.ZillowClient` (OpenWebNinja Zillow provider — already the codebase's convention, mature test surface, 30-day per-address cache). The brief suggested RapidAPI; we chose to keep the existing provider to avoid duplicating a working surface. See "Provider choice note" below.
    * `ZILLOW_TESTMODE_MOCK=true` → deterministic fixture (SHA-1 of the normalised address seeds every numeric — same address always yields the same fixture).
    * Neither `ZILLOW_TESTMODE_MOCK=true` **nor** any provider key (`ZILLOW_RAPIDAPI_KEY`, `OPENWEB_NINJA_API_KEY`, `OWN_API_KEY`) set → raises `ZillowNotConfigured` → router returns **503** `{"error": "zillow_not_configured", "message": "…"}`.
    * 24h in-Mongo cache keyed on `sha256(normalised_address)` in the existing `zillow_cache` collection. `cached=True` on the response payload when served from cache.
    * Per-tenant 100 req/hour cap in a new `zillow_enrich_rate` Mongo collection (keyed on `(tenant_id, YYYY-MM-DDTHH)`, atomic `$inc`). Cache hits do **not** consume the counter.
* **Endpoints** (all under `/api`) in `backend/routers/d2d.py`:
    * `POST /d2d/prospects/{prospect_id}/enrich-zillow` — pulls, persists `zillow_data` + `zillow_fetched_at` on the `d2d_knocks` row, returns the enriched payload.
    * `POST /d2d/zillow-lookup` — ad-hoc lookup, body `{"address": "…", "force_refresh": false}`.
    * Authz: **any authenticated user** (super/admin/dispatcher/planner/technician). No 403 for techs. Non-authenticated → 401.
    * 503 on `ZillowNotConfigured`, 429 on `ZillowRateLimited`.
* **Terminology.** The brief uses "prospect"; the codebase has no `prospects` collection. `prospect_id` in the URL alias resolves to `d2d_knocks._id`.

### Frontend
* `frontend/src/pages/d2d/D2dPages.jsx` · new `ZillowRowPanel` component + wired into every row of `D2dKnocks`.
* Button label:
    * No cached data → **"Pull property data"**.
    * Cached data ≤ 24h old on the knock → **"Refresh Zillow data"** with panel pre-open using the cached fields.
* Panel renders `estimated_value` as USD currency, `sqft` / `lot_size_sqft` with thousands separators, `bed_count` / `bath_count`, `year_built`, and `image_url` when present.
* Error handling:
    * 503 (`zillow_not_configured`) → `toast.error("Zillow API not configured — ask your admin.")`.
    * 429 (`zillow_rate_limited`) → `toast.error("Zillow rate limit hit …")`.
    * Anything else → generic error toast with the message.

### Data model changes
* `d2d_knocks` gains two fields (opt-in, added by first enrichment call — no migration required):
    * `zillow_data: dict` — full `ZillowProperty` payload.
    * `zillow_fetched_at: iso8601`.
* New Mongo collection `zillow_enrich_rate` for the rate limiter.

## Environment
* Preview: `ZILLOW_TESTMODE_MOCK=true` added to `backend/.env`.
* Production: user should either
    * Leave `ZILLOW_TESTMODE_MOCK=true` while road-testing the UI, OR
    * Set `ZILLOW_RAPIDAPI_KEY` (or the existing `OPENWEB_NINJA_API_KEY` if staying on OpenWebNinja) and unset the mock flag.

## Provider choice note (RapidAPI vs OpenWebNinja)
The brief suggested RapidAPI's Zillow endpoint. The codebase already ships an OpenWebNinja Zillow adapter with per-address cache, 30-day TTL, admin budget guard, and existing test coverage. Rather than duplicating that surface with a parallel RapidAPI client, this hotfix reuses OpenWebNinja and maps its response into the requested `ZillowProperty` shape. Swapping to RapidAPI (or any other Zillow provider) is now a one-line change inside `ZillowClient.search_by_address` — the enrichment surface is decoupled.

## Tests

### Backend — `backend/tests/test_d2d_customer_gate_and_zillow_hotfix.py`
```
test_d2d_customer_list_forbidden_for_technician_403                                   ✓
test_d2d_customer_list_allowed_for_admin_200                                          ✓
test_d2d_customer_list_allowed_for_super_200                                          ✓
test_d2d_job_detail_lookups_still_work_for_tech                                       ✓
test_zillow_endpoint_allowed_for_technician                                           ✓
test_zillow_endpoint_allowed_for_admin                                                ✓
test_zillow_endpoint_401_for_unauthenticated                                          ✓
test_zillow_returns_503_when_not_configured                                           ✓
test_zillow_returns_mock_fixture_when_testmode_enabled                                ✓
test_zillow_caches_on_prospect_and_hits_cache_on_second_call                          ✓
test_zillow_rate_limit_100_per_hour_per_tenant_returns_429_on_101st                   ✓
== 11 passed ==
```

### Frontend — `frontend/src/test/d2d-customer-gate-zillow-hotfix.test.jsx`
```
D2D map · Part A · existing-customer list gate                                        ✓
  ↳ does NOT fetch /d2d/customers-nearby for technician role                          ✓
  ↳ DOES fetch /d2d/customers-nearby for admin role                                   ✓
D2D knocks · Part B · Zillow enrichment                                               ✓
  ↳ renders 'Pull property data' button for tech role                                 ✓
  ↳ clicking Pull calls the enrichment endpoint and renders fields                    ✓
  ↳ cached prospect shows 'Refresh Zillow data' + pre-rendered fields                 ✓
  ↳ 503 response surfaces 'Zillow API not configured' toast                           ✓
== 6 passed ==
```

## Follow-up ticket · I1.7.f — Data Enrichment BYO providers

Convert the env-var-based Zillow key into a tenant-BYO card at `/settings/integrations`, alongside AI, Maps, Calendars, Payments. Providers to slot in:

* Zillow (OpenWebNinja or RapidAPI) — this hotfix's stopgap consolidates into the BYO surface.
* RentSpree — comparable comps + rental yield.
* PropStream / DataTree / other property-data APIs.

Design surface should mirror `services.payments_byo.registry`:
* `services/enrichment_byo/registry.py` with a `PropertyDataProvider` ABC (`lookup_by_address`, `test_connection`).
* Existing `services/enrichment/zillow.py` becomes the first adapter.
* New `enrichment` array on `GET /api/tenants/me/integrations/schemas` with `connection_type=api_key`.
* Unified `tenant_provider_health` cron already ships with I1.7.d — health dots on the new cards for free.

## Expo parity follow-up

`mobile/app/d2d/index.tsx` and siblings exist. Both changes should be mirrored:
* **Part A** — the mobile D2D screen also plots a customer layer for admin; that fetch must be gated to `admin`/`super_admin`/`dispatcher` roles.
* **Part B** — the mobile D2D screen should surface the same "Pull property data" button and hit the new `/api/d2d/prospects/{id}/enrich-zillow` endpoint. Backend already supports it.

Dispatch to the Expo specialist as a separate ticket — this hotfix ships the web + backend contract.

## Files touched

### New
* `backend/services/enrichment/__init__.py`
* `backend/services/enrichment/zillow.py`
* `backend/tests/test_d2d_customer_gate_and_zillow_hotfix.py`
* `frontend/src/test/d2d-customer-gate-zillow-hotfix.test.jsx`
* `memory/HOTFIX_D2D_CUSTOMER_GATE_AND_ZILLOW.md` (this file)

### Modified
* `backend/routers/d2d.py` — appended 3 endpoints (customers-nearby, zillow-lookup, prospects/enrich-zillow) + `_require_admin_or_super` helper.
* `backend/.env` — added `ZILLOW_TESTMODE_MOCK=true`.
* `frontend/src/pages/d2d/D2dPages.jsx` — `useAuth` import, `D2dMap` role gate for customer fetch, new `ZillowRowPanel` component, wired into `D2dKnocks` table row.
