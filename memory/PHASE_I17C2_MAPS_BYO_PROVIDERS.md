# Phase I1.7.c.2 · Tenant Integrations: Maps BYO Providers

**Feb-2026 · Status: SHIPPED (green — 14/14 backend + 7/7 new frontend)**

## Scope
Add tenant-scoped Bring-Your-Own-Key support for **Google Maps** and **Mapbox**,
with encrypted-at-rest secret storage, monthly per-operation usage tracking,
and soft-warn / hard-block cap enforcement. Cap semantics are locked to be
byte-for-byte identical to AI (null=unlimited, 0=block-all, >0 hard-block with
80% soft-warn). OSM was intentionally not implemented (no BYO key required
for public Nominatim endpoints; neither OSM nor Nominatim is wired in the
codebase today, so the platform-default fallback is the existing env-keyed
Google Maps / Mapbox services under `services/google_maps/*`).

## Backend
- `services/maps/tenant_base.py` — `MapsProvider` ABC with three
  operations: `geocode`, `route`, `static_map_url`.
- `services/maps/google_maps_provider.py` — Geocoding API, Routes v2
  (`computeRoutes` w/ FieldMask), Static Maps URL builder.
- `services/maps/mapbox_provider.py` — Geocoding v5, Directions v5,
  Static Maps v1 style overlay URL builder. Handles the `lng,lat`
  coord ordering quirks.
- `services/maps/registry.py` — provider registry, short-name
  map (`maps_google ↔ google`, `maps_mapbox ↔ mapbox`).
- `services/maps/_helpers.py` — JSON-encode config → encrypted blob
  via `services.secrets.put_secret`. `primary_secret_field="api_key"`
  → `last_4` masking. Test-mode gate: `MAPS_TESTMODE_MOCK=true`.
- `services/maps/usage.py` — two collections:
    - `tenant_maps_provider` (plaintext sidecar: `monthly_request_cap`
      + non-secret extras like `region_bias`, `style`).
    - `tenant_maps_usage` (per-`(tenant, provider, yyyymm)` counters
      broken down by operation: `geocode`, `route`, `static_map`,
      `total`). Cap enforced against `total`.
  Cap semantics identical to AI (locked with user):
    - `null` → **unlimited** (default)
    - `0` → **block all** (kill-switch)
    - `>0` → hard-block at `used >= cap`; soft-warn at `used >= 0.8*cap`.
- `services/maps/dispatcher.py` — public entry points:
    - `dispatch_maps_geocode(...)`
    - `dispatch_maps_route(...)`
    - `dispatch_maps_static_map_url(...)`
  Rules:
    - No BYO row → platform-default fallback (env keys under
      `GOOGLE_MAPS_API_KEY` / `MAPBOX_ACCESS_TOKEN` via the existing
      `services.google_maps.*` wrappers). Same behaviour the app has
      had all along.
    - BYO row + cap hit → **raise `TenantMapsRequestCapExceeded`**
      (HTTP 429), NO platform fallback.
    - BYO row + cap ok → dispatch, `record_usage(...)` after success
      with the correct operation flag.

## Endpoints (all `/api`-prefixed)
- `PUT /tenants/me/integrations/maps_{google|mapbox}` — reuses the
  shared `SaveIntegrationBody` + `_preserve_stored_secrets` path
  (added in I1.7.c.1 post-tester fix) — no duplication. Accepts
  `{config: {api_key, region_bias|style, ...}, monthly_request_cap}`.
- `DELETE /tenants/me/integrations/maps_{provider}` — removes BOTH
  the encrypted secret row AND the metadata sidecar.
- `GET /tenants/me/integrations/maps/usage` — mirrors `/ai/usage`.
  Returns per-provider snapshot: `{provider, period_yyyymm, geocode,
  route, static_map, total, monthly_request_cap, connected, pct_used,
  status}` where `status ∈ {ok, warn, blocked}`.
- `GET /tenants/me/integrations/schemas` — now returns `maps[]` with
  `google` and `mapbox` schemas (fields include the provider-specific
  `region_bias` / `style` public config fields).
- `GET /tenants/me/integrations` — masks maps providers with `last_4`
  alongside AI/Stripe/SMS/Email.

## Frontend
- `components/settings/TenantIntegrationsCard.jsx` — new `MapsCard`
  sub-component mirroring `AICard`:
    - `api_key` password input (blank preserves stored value via the
      shared backend helper).
    - Schema-driven non-secret fields (`region_bias` for Google,
      `style` for Mapbox) so adding a new maps provider needs zero
      component changes.
    - `monthly_request_cap` numeric input (empty=null, 0=block).
    - Usage progress bar with per-operation breakdown row
      (`geocode X · route Y · static Z`) and warn/blocked banners.
- Root component now fetches `/tenants/me/integrations/maps/usage`
  in parallel with the AI usage endpoint. Existing state hooks and
  CSS shared verbatim — no duplication.
- `maps` dropped from `COMING_SOON`.

## Tests
- `backend/tests/test_i17c2_maps_byo_providers.py` — **14 cases**:
    - `test_registry_lists_google_and_mapbox`
    - `test_put_maps_google_stores_encrypted_key_and_masks_on_get`
    - `test_put_maps_mapbox_stores_encrypted_key_and_masks_on_get`
    - `test_delete_maps_provider_clears_secret`
    - `test_dispatch_maps_uses_tenant_provider_when_configured`
    - `test_dispatch_maps_falls_back_to_platform_when_unconfigured`
    - `test_dispatch_maps_tracks_usage_per_operation`
    - `test_dispatch_maps_soft_warning_at_80pct`
    - `test_dispatch_maps_hard_block_at_100pct_returns_429`
    - `test_maps_cap_zero_blocks_immediately`
    - `test_maps_hard_block_does_not_fallback_to_platform`
    - `test_get_maps_usage_returns_current_period_per_operation`
    - `test_openapi_declares_new_maps_endpoints`
    - `test_cap_only_edit_preserves_stored_maps_secret` (uniformity
      guard for the shared `_preserve_stored_secrets` helper).
- `frontend/src/test/i17c2-maps-byo-card.test.jsx` — **7 cases**:
    render, save body shape, cap-only edit blank api_key, warn state,
    blocked state, disconnect visual flip, manager gate.
- `i17a-integrations-page.test.jsx` updated: `maps` dropped from
  coming-soon list, mock returns `maps[]` schemas + `maps/usage`.

## Numbers
- **Backend I1.7 suite: 126/126 green** (up from 112).
- **Frontend I1.7 suite: 34/34 green** (up from 27).
- Live UI on preview: both maps cards render below AI cards with
  correct fields, cap input, usage row, and Save button.

## Compatibility
- No existing maps call-sites rewired — deferred to Phase I1.7.e alongside
  the AI callsite migration.
- `SaveIntegrationBody` gained one optional field (`monthly_request_cap`);
  legacy payloads continue to work.
- Platform-default fallback is the existing env-keyed Google Maps + Mapbox
  services under `services/google_maps/*`. **OSM stayed as-is: not
  implemented, no fallback change** — the existing code already didn't
  use it.

## Follow-ups (deferred, not in this phase)
- **I1.7.e** — Rewire existing maps call-sites through
  `dispatch_maps_*` so ALL tenant maps runs through the same
  cap/fallback gate (and translate `TenantMapsRequestCapExceeded → 429`
  at every consumer).
- **I1.7.c.3** — Calendars BYO (Google Calendar / Outlook / iCloud).
- **429 mapping** — same as AI: surface the cap-exceeded exception
  at every future callsite when the rewire lands.
- **Payments providers Square / PayPal / Authorize.net / Lumino**
  (Phase I1.7.d) still queued.
