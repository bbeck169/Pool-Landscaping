# Phase 54b · Pool360 scraper connector + Settings UI

_Status: SHIPPED (Feb 2026)_

## Scope
- Playwright-driven wholesale sync connector for Pool360 (PoolCorp).
- Manual "Sync now" endpoint (`POST /api/suppliers/poolcorp/sync`) returns 202 + background task.
- Wholesale supplier settings UI at `/settings/suppliers` (Pool360 wired; four other wholesalers show "Coming in 54c/d/e").

## Backend
### New files
- `backend/services/suppliers/poolcorp.py` — `PoolCorpConnector.authenticate()` +
  `list_products()`, headless Chromium, UA=`AquaTerra-PriceBook/1.0`,
  1 req/sec, 30 s page timeout, exponential backoff up to 60 s on
  pagination timeouts. `LoginFailedError` + `LayoutChangedError` exceptions.
- `backend/services/suppliers/selectors.py` — Pool360 CSS selectors as config
  (product card, SKU, name, dealer-price, MSRP, pagination-next, …).
- `backend/services/suppliers/sync.py` — `start_sync_job`, `finalize_sync_job`,
  `apply_products_to_pricebook` (dedupe on `(tenant_id, supplier_id, external_sku)`;
  soft-delete missing rows via `deleted_at`; refuses to soft-delete when
  incoming product list is empty), and `run_poolcorp_sync` (full flow driver).

### Router changes
- `POST /api/suppliers/poolcorp/sync` now:
  - 202 Accepted + `{"job_id", "status": "running", "supplier_slug"}`.
  - Kicks a FastAPI `BackgroundTasks` runner off with decrypted creds.
  - 400 `{"error": "no_credentials"}` when no creds saved.
  - 403 for manager / tech / customer roles.
- Other four supplier slugs still 501 with "coming in phase 54c/d/e".

### Tests — `backend/tests/test_phase54b_poolcorp_connector.py` (9 tests)
- `_parse_price` helper.
- `apply_products_to_pricebook`: insert + update + soft-delete (empty list refuses).
- `run_poolcorp_sync`: success / login failure / layout-change (mocked connector).
- Router: manager 403, no-credentials 400, creds-present 202 + `job_id`.
- Playwright fully mocked (no live Pool360 network in tests).

### Tech-stack change
- Added `playwright==1.61.0` to `backend/requirements.txt` (installed previously).

## Frontend
### New files
- `frontend/src/pages/settings/SupplierSettings.jsx` — the page.
  - `PoolcorpCard`: credentials form (username + password), Save / Sync now /
    Refresh history / Remove buttons, sync history table (last 10 runs),
    literal legal disclaimer, connection status pill.
  - `ComingSoonCard`: for siteone / ewing / heritage / epoolsupply.
  - Manager role → inputs disabled + action buttons hidden + read-only notice.

### Wiring
- `App.js` imports `SupplierSettings`.
- Route: `/settings/suppliers` gated by new `AdminOrManagerForSuppliers`
  wrapper (admin + super_admin + manager allowed; tech + customer → `/`).

### Tests — `frontend/src/test/supplier-settings.test.jsx` (10 tests)
- Page container renders after `/suppliers` load.
- Legal disclaimer string renders verbatim.
- Coming-soon cards render for the other four wholesalers.
- Empty history state.
- Save credentials → `POST /suppliers/poolcorp/credentials`.
- Sync now disabled when no creds; enabled + POST when creds present.
- Sync failure surfaces server `detail.message` in a toast.
- Manager role → form disabled + action buttons absent + read-only notice.
- `App.js` wrapper regression guard (string-source assertion).

## Legal disclaimer (locked verbatim by spec)
> Automated syncing may be subject to your wholesaler's Terms of Service. By connecting, you acknowledge responsibility for compliance with those terms.

## Invariants after 54b
- Vitest: **1399 / 1399** (baseline 1389 + 10 new).
- Mobile Jest: **236 / 236** unchanged.
- Backend Phase 53+54 curated suite: **56 / 56**.
- `yarn lint` exit 0.

## Deferred to later phases
- **54c** — SiteOne connector.
- **54d** — Ewing connector.
- **54e** — Heritage + ePoolSupply connectors + scheduled cron sync.
- **54f** — Pricebook UI: supplier column + filter (Web + Mobile).
- **Live Pool360 verification** — operator hasn't provided real credentials.
  Selectors + backoff + layout-change guard are all covered by mocked tests;
  first live sync is expected to require a selector patch pass (design goal
  of `selectors.py`: config, not code).

## Known non-issues surfaced during shipping
- Phase 47c / 48b Stripe RBAC test cluster still paused — untouched by 54b.
- Phase 34 HTTP ReadTimeout cluster still open — one of the 54b router
  tests was refactored to use `http://localhost:8001` (bypassing the
  preview-URL alias) to sidestep the same class of flakiness.
