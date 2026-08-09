# Phase 54c · SiteOne connector + `POST /api/suppliers/{slug}/test-connection`

_Status: SHIPPED (Feb 2026)_

## Scope
- Wire SiteOne (B2B) as the second supplier — mirrors the Pool360 pattern
  from Phase 54b.
- Introduce a generic **test-connection** endpoint that all wired suppliers
  reuse (Pool360 + SiteOne today, plus every 54d/e supplier in the pipeline).
- Fold the "test connection" affordance into the Settings UI for both wired
  suppliers so operators can validate credentials in ~5 s before committing
  to a full multi-thousand-SKU sync.

## Files touched

| File | Kind | Purpose |
| --- | --- | --- |
| `backend/services/suppliers/siteone.py` | **new** | Playwright-driven SiteOne connector + `_next_backoff` helper + `RATE_LIMIT_HTTP_STATUSES`. Reuses `LoginFailedError` + `LayoutChangedError` from Pool360. |
| `backend/services/suppliers/siteone_selectors.py` | **new** | Data-only selector config (12 keys). |
| `backend/services/suppliers/sync.py` | edit | Extracted generic `run_supplier_sync(...)`; new `run_siteone_sync(...)`; `run_poolcorp_sync` still exported (thin wrapper — Phase 54b tests keep passing). |
| `backend/services/suppliers/connector.py` | edit | `CONNECTORS["siteone"]` now points to the wired `services.suppliers.siteone:SiteOneConnector` (guarded try/except so a fresh checkout without Playwright still imports). |
| `backend/routers/suppliers.py` | edit | `POST /suppliers/{slug}/sync` — wired-slug set is now `{poolcorp, siteone}`. New `POST /suppliers/{slug}/test-connection` (super_admin+admin only). |
| `backend/tests/test_phase54a_suppliers_skeleton.py` | edit | Updated the 501-slug fixture (was `siteone` → now `ewing`). `test_all_connector_stubs_raise_not_implemented` now skips both wired slugs. |
| `backend/tests/test_phase54c_siteone_connector.py` | **new** | 18 tests — see below. |
| `frontend/src/pages/settings/SupplierSettings.jsx` | edit | Renamed `PoolcorpCard` → `WiredSupplierCard`; `WIRED_SLUGS` set = `{poolcorp, siteone}`; new "Test connection" button + `runTest` handler + `<test-result>` badge; dynamic labels/placeholders + delete-confirm text. |
| `frontend/src/test/supplier-settings.test.jsx` | edit | Test count: **10 → 19** (added 4 SiteOne wired tests + 5 test-connection branch tests). |
| `memory/PHASE54C_SITEONE_CONNECTOR.md` | **new** | This file. |

## Selector-config summary — `siteone_selectors.py`

| Key | Purpose |
| --- | --- |
| `login_url` | `https://www.siteone.com/en/pro/login` |
| `catalog_url` | `https://www.siteone.com/en/pro/products` |
| `input_username` / `input_password` / `btn_submit` | Login form triple (with fallback selectors) |
| `logged_in_marker` | Post-login DOM marker (user menu / logout link) |
| `product_card` | One-per-SKU tile — layout-change guard fires when this returns zero cards |
| `field_sku` / `field_name` / `field_cost` / `field_msrp` / `field_category` / `field_uom` / `field_description` | ExternalProduct field selectors |
| `btn_next_page` / `page_indicator` | Pagination |
| `rate_limit_banner` | Logging clarity only — connector already detects 429/503 from HTTP status |

Every selector is a list of fallbacks (e.g. `input[name='username'], input#username`) so a small DOM tweak on SiteOne doesn't break the sync.

## `POST /api/suppliers/{slug}/test-connection` — shape + timing

### Request
```
POST /api/suppliers/{slug}/test-connection
Authorization: Bearer <jwt>
```
No body. The slug must be in `{poolcorp, siteone}` today (501 for the other three).

### Response shapes

| Scenario | Status | Body |
| --- | --- | --- |
| Success | 200 | `{ "ok": true, "supplier_slug": "siteone" }` |
| Bad credentials | 200 | `{ "ok": false, "error": "login_failed", "message": "...", "supplier_slug": "siteone" }` |
| Rate limited (message contains 429/503/rate/throttle) | 200 | `{ "ok": false, "error": "rate_limited", ... }` |
| Timeout (>`TEST_CONNECTION_TIMEOUT_S` = 15 s) | 200 | `{ "ok": false, "error": "timeout", "supplier_slug": "siteone" }` |
| Any other exception | 200 | `{ "ok": false, "error": "unknown", "message": "...", ... }` |
| Non-admin caller | 403 | `{ "detail": { "error": "forbidden" } }` |
| No saved credentials | 400 | `{ "detail": { "error": "no_credentials", "message": "..." } }` |
| Un-wired supplier slug (ewing/heritage/epoolsupply) | 501 | `"connector not implemented yet, coming in phase 54d"` (etc.) |

### Timing budget
- Success path (post-login DOM marker present): **~5 s target**.
- `asyncio.wait_for(...)` wraps `connector.authenticate()` at `TEST_CONNECTION_TIMEOUT_S = 15.0` s (module-level in `routers.suppliers` — overridable by tests).
- No catalog walk, so it never hits multi-page pagination.

## Test-count delta

### Backend (`pytest`)
| Suite | Before | After | Δ |
| --- | --- | --- | --- |
| `test_phase54a_suppliers_skeleton.py` | 14 | 14 | 0 (2 tests updated in place — same count) |
| `test_phase54b_poolcorp_connector.py` | 9 | 9 | 0 |
| `test_phase54c_siteone_connector.py` | 0 | 18 | **+18** |

**Phase 53+54 curated total: 56 → 74** (still 100 % green).

### Frontend (`vitest`)
| Suite | Before | After | Δ |
| --- | --- | --- | --- |
| `supplier-settings.test.jsx` | 10 | 19 | **+9** |

**Full vitest: 1399 → 1408** (still 100 % green).

## Confirmation of invariants (post-ship)

| Gate | Result |
| --- | --- |
| `yarn vitest run` | **1408 / 1408 pass** |
| `yarn lint` | exit **0** |
| Mobile Jest (`yarn test` in `/app/mobile`) | **236 / 236 pass** (unchanged) |
| `pytest test_phase53a_ebit_backend.py test_phase53d_ebit_contract_lock.py test_phase54a_suppliers_skeleton.py test_phase54b_poolcorp_connector.py test_phase54c_siteone_connector.py` | **74 / 74 pass** in ~18 s |
| Playwright real network calls in tests | **0** (fully mocked; direct-function-call pattern for the router branch tests to avoid live-server monkeypatch limits) |

## Screenshots

Captured live against `poolscape-audit.preview.emergentagent.com` with an
admin JWT primed into `localStorage`. See `/tmp/phase54c_supplier_settings.jpg`
and `/tmp/phase54c_connected_state.jpg`.

Visual verification:

1. **Empty state (both cards)** — Pool360 shows *Not connected* pill; input
   placeholders read `your-poolcorp-username` + `your-poolcorp-password`. Same
   for SiteOne. Legal disclaimer verbatim under both.
2. **Connected state** — after saving credentials for both suppliers, the
   status pill turns green *Connected*, the input placeholders switch to
   `•••••• (saved)`, and "Sync now" + "Test connection" become enabled. A
   `Credentials last updated ...` timestamp appears under the recent-syncs
   table.
3. **Test connection failure** — clicking `Test connection` on SiteOne in the
   preview env (which has no Chromium binary installed) fires the real
   `POST /api/suppliers/siteone/test-connection`; the router classifies the
   Playwright launch error as `error: "unknown"` and the UI renders the red
   badge *"Connection failed for an unknown reason. See server logs for
   details."* plus a `sonner` toast. This is the actual failure branch, not
   a mocked one — proves the full stack is wired.

The "test connection success" state can't be captured live (preview server
lacks Chromium). The vitest suite covers the success branch in isolation
with a mocked `POST` response.

## Deviations from scope

**One**: the four test-connection failure-branch backend tests
(`login_failed`, `rate_limited`, `unknown`, `timeout`) call the router
function `test_supplier_connection(...)` directly via `batch_safe_run` (with
a mocked `user` dict and a monkey-patched `CONNECTORS["siteone"].authenticate`)
instead of hitting the live supervisor-managed server over HTTP. Rationale:
monkey-patching the CONNECTORS registry inside the pytest process cannot
affect a separate uvicorn process, so an HTTP-based test would either need
a fully mocked `authenticate` at import time (breaks Phase 54b's already-
green suite) or a request-time env-var toggle inside the router (unwanted
runtime complexity for a testing seam). Direct-function tests use the same
router code path, hit real Motor + real Fernet crypto for the credentials
read, and are strictly stronger than an HTTP-only test of the mocked
response envelope. The role-gate + no-credentials + 501-unwired tests
still hit the live server over HTTP, so the HTTP path is not un-tested.

No other deviations.
