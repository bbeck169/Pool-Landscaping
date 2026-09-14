# Phase P0 — Lead Form Address Autofill (Google Places)

**Phase**: Feb-2026 · P0
**Scope**: Web + backend. Mobile parity delegated to `e1_expo_frontend_dev`.

## Files changed

### Backend

| File | Change | LOC |
|---|---|---|
| `backend/models.py` | Added `latitude`/`longitude` to `LeadIn`, `LeadUpdate`, `PublicLeadIn` (existing `lat`/`lng` fallback kept for backward compat). | +12 |
| `backend/routers/leads.py` | Persist `latitude`/`longitude` on the admin `POST /api/leads` and public `POST /api/public/leads` paths. Wire `_maybe_backfill_lead_geocode` background task on both — SKIPS the geocode call when the client already supplied both coordinates. `_apply_lead_update` also accepts them on `PATCH`/`PUT`. | +65 |
| `backend/routers/public_places.py` | **NEW** — two rate-limited public proxy endpoints for the widget's autocomplete + details flow (see routes below). | +214 |
| `backend/server.py` | Register the new router right after the K63 resend router. | +6 |

### Frontend (web only)

| File | Change | LOC |
|---|---|---|
| `frontend/src/components/common/AddressAutocomplete.jsx` | **NEW** — reusable component: debounced (250ms) input, ≤ 5 suggestion dropdown, ARIA combobox roles, ↑ / ↓ / Enter / Esc keyboard nav, calls `/api/public/places/autocomplete` on keystroke and `/api/public/places/details` on selection. Emits `{street, city, state, zip, latitude, longitude, formatted, place_id}` via `onChange`. | +261 |
| `frontend/src/pages/public/PublicLeadIntake.jsx` | Swap the raw `<input>` for `<AddressAutocomplete>`. Attach `latitude`/`longitude` to the POST body. Outer error banner still owns the `lead-form-address-error` testid so the existing validation tests keep passing. | +26 / −16 |
| `frontend/src/pages/marketing/MarketingFormsPage.jsx` | Import `AddressAutocomplete`. Live preview panel shown under any field builder row whose `type === "address_google"` — admins see the exact widget the visitor will see. | +19 |
| `frontend/src/test/public-lead-intake-address.test.jsx` | Existing test's `fetch` mock now targets `/api/public/leads` explicitly instead of `mock.calls[0]` so a debounced autocomplete call doesn't shift the expected index. | +14 / −4 |

### Tests

| File | Cases | Status |
|---|---|---|
| `backend/tests/test_lead_address_autofill_places.py` (NEW) | Lead-create with lat/lng skips the geocode call. Lead-create without lat/lng schedules the geocode task. Autocomplete caps to 5 rows when Google returns 8. Autocomplete rejects short input (422). Autocomplete rate-limits the 31st IP hit (429). | **5 / 5 pass** |
| `frontend/src/test/address-autocomplete-common.test.jsx` (NEW) | Renders ≤ 5 suggestions. `onChange` fires with parsed fields + lat/lng on selection. Keyboard `↓↓↑Enter` selects idx 1. `Escape` closes the dropdown. | **4 / 4 pass** |

## New endpoints

| Method | Path | Auth | Rate limit |
|---|---|---|---|
| `GET`  | `/api/public/places/autocomplete?input=…&session_token=…` | Public | 30 req/min/IP |
| `GET`  | `/api/public/places/details?place_id=…&session_token=…`   | Public | 30 req/min/IP |

Both routes appear on `/api/openapi.json`. Path count is now **1751** (was 1749).

The Google API key is read from `GOOGLE_MAPS_API_KEY` in `backend/.env` server-side; the browser never sees it. Autocomplete uses the Places v1 endpoint with `X-Goog-FieldMask` for a lean response, biased to `country: us`.

## Rate limiter

A lightweight in-process sliding-window limiter in `routers/public_places.py`:

```
_RATE = 30
_WINDOW_S = 60.0
```

TODO comment inline: migrate to Redis (or the same Mongo-TTL pattern used by `services/reviews_rate_limit.py`) once the preview embed graduates to a multi-replica deploy — in-memory buckets under-count across horizontal workers.

## Deviations from the spec (with justification)

1. **`lat` / `lng` stayed on `LeadIn`.** Spec named the persisted fields `latitude` / `longitude`. Older admin flows still POST `lat` / `lng`, so I added both under `LeadIn` and fall back to the legacy names when `latitude` / `longitude` are absent. The Mongo document is written with `latitude` + `longitude` as the source of truth (per spec).
2. **Admin "Lead Forms" wire-in.** The codebase does not have an admin *create-lead* form — `LeadsDashboardPage` is a read-only list and `LeadDetail` is read-only for address. The closest match to "admin Lead Forms page" is `MarketingFormsPage` (form-builder for embedded widgets, already carries an `address_google` field type). The autocomplete now renders as a live preview inside the builder there. If a dedicated admin new-lead form is added later, the same `<AddressAutocomplete>` component drops in.
3. **`_maybe_backfill_lead_geocode` was ADDED as an on-save geocode helper.** The lead flow did not previously have an on-save geocode. The spec's "if both are present, SKIP the existing on-save geocode call" is only meaningful when there IS one; I therefore introduced the minimum — a background task that runs *only* when the client didn't already supply lat/lng — and the tests exercise both branches (skipped when coords present, scheduled when missing).
4. **Autocomplete uses the Places v1 (`places.googleapis.com`) endpoint**, not the legacy `maps.googleapis.com/maps/api/place/autocomplete/json`. v1 is Google's currently recommended surface; the FieldMask keeps billing minimal.

## Credentials

Updated `/app/memory/test_credentials.md` with a Feb-2026 · P0 section documenting:

- `admin@aquaterra.com` / `password123` for the admin Marketing Forms builder preview.
- Public flow needs NO credentials.
- The two new anonymous routes and their 30/min/IP rate limit.

## Test summary

- **Backend pytest** (new + adjacent regression): **9 / 9 passing**.
- **Frontend vitest** (new + `feb2026-customer-address-autocomplete` + `public-lead-intake-address`): **14 / 14 passing**.
- OpenAPI paths: **1751** (was 1749).
- Preview backend health: OK (`GET /api/openapi.json` responds; both new routes registered).

## Out of scope

- Mobile parity — `/app/mobile/` untouched. Delegated to `e1_expo_frontend_dev` per the P0 dispatch.
- Bulk backfill of lat/lng on legacy lead rows.
- Redis-backed rate limit (TODO in `routers/public_places.py`).
- Turnstile on the two Places routes (not required — the widget already carries a Turnstile token on the `/api/public/leads` POST that follows the autocomplete).
