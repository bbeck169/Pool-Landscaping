# Environment Reference — canonical env vars per integration

Living document for env-var canonicalization. Updated Feb 2026 (Task TT.5).

## Zillow / Property data

**Canonical provider**: OpenWebNinja direct — `https://api.openwebninja.com/realtime-zillow-data`

| Env var | Purpose | Consumers |
|---|---|---|
| `OPENWEB_NINJA_ZILLOW_API_KEY` | Primary API key (preferred by both legacy Phase 56.9b path AND Task TT adapter) | `services/property_data/zillow_adapter.py`, `config.py` |
| `OPENWEB_NINJA_API_KEY` | Fallback API key (used when the ZILLOW-suffixed variant is unset) | Same as above |
| `ZILLOW_TEST_ALLOWLIST_ADDRESSES` | Comma-separated substring allowlist that unblocks specific non-synthetic addresses in preview | `services/property_data/zillow_adapter.py` |

**Auth pattern**: HTTP header `x-api-key: <OPENWEB_NINJA_ZILLOW_API_KEY or OPENWEB_NINJA_API_KEY>`

**Endpoints used**:
- `GET /property-details-address?address=<addr>` — search by full address (Task TT adapter, `routers/property.py::/api/property/lookup`)
- `GET /search?location=<zip>&home_status=RECENTLY_SOLD&sort=DEFAULT&page=<n>` — sold-leads search by ZIP (`routers/d2d.py::/api/d2d/sold-leads`)
- `GET /property?zpid=<zpid>` — property detail by zpid (Task TT adapter, `tests/test_zillow_live.py`)
- `GET /search_zip?zip=<zip>` — health probe (`routers/google.py`)

**Rotation on compromise**: rotate at the OpenWebNinja dashboard, then update BOTH `OPENWEB_NINJA_ZILLOW_API_KEY` and `OPENWEB_NINJA_API_KEY` in preview + prod pod env (any consumer that reads the fallback keeps working during the transition).

## Deprecated / Removed

| Env var | Status | Notes |
|---|---|---|
| `RAPIDAPI_KEY` | **Deprecated Feb 2026 (TT.5)** | Task TT originally scaffolded against RapidAPI marketplace. Reconciled to OpenWebNinja direct. Do NOT set — no consumer reads it. |
| `RAPIDAPI_ZILLOW_HOST` | **Deprecated Feb 2026 (TT.5)** | Same as above. |

## Lumino payments (Task QQ)

| Env var | Purpose |
|---|---|
| `LUMINO_ZAPIER_SHARED_SECRET` | HMAC-style shared secret for `POST /api/webhooks/lumino/zapier`. Bridge fail-closes to HTTP 401 when empty. Mint with `openssl rand -hex 32`; NEVER paste in chat, code, or `.env` commits — set directly in the pod's secure env. |

## AI / LLM

| Env var | Purpose |
|---|---|
| `EMERGENT_LLM_KEY` | Universal LLM key covering Anthropic Claude text, Gemini image (Nano Banana), OpenAI text + image + whisper, Sora 2 |

## Payments

| Env var | Purpose |
|---|---|
| `STRIPE_SECRET_KEY` / `STRIPE_PUBLISHABLE_KEY` / `STRIPE_MODE` / `STRIPE_ACCOUNT_ID` / `STRIPE_WEBHOOK_SECRET` | Stripe (active provider in preview + prod cutover in-flight) |

## Comms

| Env var | Purpose |
|---|---|
| `RESEND_API_KEY` / `RESEND_FROM_ADDRESS` / `RESEND_WEBHOOK_SECRET` / etc. | Resend email |
| `RC_CLIENT_ID` / `RC_CLIENT_SECRET` / `RC_JWT` / `RC_SERVER_URL` / `RC_FROM_NUMBER` / `RC_OUTBOUND_ENABLED` | RingCentral SMS |

## Google

| Env var | Purpose |
|---|---|
| `GOOGLE_API_KEY` | Google APIs (server-side) |
| `GOOGLE_MAPS_API_KEY` | Google Maps (frontend + backend geocoding) |

## Compromised-value guardrail

Regression test `backend/tests/test_task_qq_p25_zapier_resolution.py::test_compromised_secret_not_present_anywhere` grep-scans `/app` for the 4 known-compromised secret values (Zapier x2, RapidAPI x1, Lumino live x1) and fails CI if any reappears. New compromises should be appended to that test file (values assembled from parts at runtime so the file itself never contains a literal).
