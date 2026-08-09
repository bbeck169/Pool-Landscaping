# Phase 54d · Ewing connector + `SUPPLIER_METADATA` config extraction

_Status: SHIPPED (Feb 2026)_

## Scope
- Wire Ewing Irrigation (third supplier) — mirrors the SiteOne (54c) pattern.
- Extract per-supplier copy from `SupplierSettings.jsx` into a
  `SUPPLIER_METADATA` map (as I suggested at the end of 54c) so 54e is a
  config patch, not a code change.
- No new endpoints — reuses the generic `POST /suppliers/{slug}/sync` +
  `POST /suppliers/{slug}/test-connection` surface locked in 54c.

## Files touched

| File | Kind | Purpose |
| --- | --- | --- |
| `backend/services/suppliers/ewing.py` | **new** | Playwright-driven Ewing connector. Imports `LoginFailedError`/`LayoutChangedError` from `poolcorp` and `_next_backoff`/`RATE_LIMIT_HTTP_STATUSES` from `siteone`. |
| `backend/services/suppliers/ewing_selectors.py` | **new** | 12-key selector config, single-source of truth for DOM tweaks. |
| `backend/services/suppliers/sync.py` | edit | Added `run_ewing_sync` (7-line wrapper on `run_supplier_sync`). |
| `backend/services/suppliers/connector.py` | edit | `CONNECTORS["ewing"]` swapped to the wired class (guarded try/except). |
| `backend/routers/suppliers.py` | edit | `_WIRED_SYNC_SLUGS` expanded to `{poolcorp, siteone, ewing}`; `_wired_sync_runner` gained an `ewing` branch. |
| `backend/tests/test_phase54a_suppliers_skeleton.py` | edit | 501-check slug swapped ewing → heritage; wired-set expanded to include `ewing`. |
| `backend/tests/test_phase54c_siteone_connector.py` | edit | `test_test_connection_501_for_unwired_supplier` swapped ewing → heritage (ewing now wired). |
| `backend/tests/test_phase54d_ewing_connector.py` | **new** | 17 tests mirroring the 54c structure. |
| `frontend/src/pages/settings/supplier_metadata.js` | **new** | The extracted metadata map + `WIRED_SLUGS` set. |
| `frontend/src/pages/settings/SupplierSettings.jsx` | edit | `WiredSupplierCard` + `ComingSoonCard` now read from `SUPPLIER_METADATA`. All hard-coded strings removed. |
| `frontend/src/test/supplier-settings.test.jsx` | edit | +7 tests: 4 Ewing wired-card tests + 3 `SUPPLIER_METADATA` shape-integrity tests. |
| `memory/PHASE54D_EWING_CONNECTOR.md` | **new** | This file. |

## `ewing_selectors.py` — selector-config summary

| Key | Purpose |
| --- | --- |
| `login_url` | `https://www.ewingoutdoorsupply.com/customer/account/login` |
| `catalog_url` | `https://www.ewingoutdoorsupply.com/products` |
| `input_username` / `input_password` / `btn_submit` | Login form triple |
| `logged_in_marker` | Post-login DOM marker |
| `product_card` | One-per-SKU tile (layout-change guard) |
| `field_sku` / `field_name` / `field_cost` / `field_msrp` / `field_category` / `field_uom` / `field_description` | ExternalProduct fields |
| `btn_next_page` / `page_indicator` | Pagination |
| `rate_limit_banner` | Logging clarity — connector detects 429/503 from HTTP status directly |

All selectors are fallback-style comma lists (e.g. `input[name='login[username]'], input[name='email'], input#email`) so a small DOM tweak on the Ewing site doesn't break the sync.

## `SUPPLIER_METADATA` structure (paste)

```js
export const SUPPLIER_METADATA = {
  poolcorp: {
    display_name:         "Pool360 (PoolCorp)",
    tagline:              "Live wholesale pricebook sync (Playwright headless).",
    username_label:       "Pool360 username",
    username_placeholder: "your-pool360-username",
    password_label:       "Password",
    password_placeholder: "your-pool360-password",
    delete_confirm_text:  "Remove saved Pool360 credentials? …",
    sync_description:     "Pool360 catalog import — pool + spa equipment.",
  },
  siteone: { …same shape… },
  ewing:   { …same shape… },
  heritage:    { display_name, tagline, coming_in: "54e" },
  epoolsupply: { display_name, tagline, coming_in: "54e" },
};

export const WIRED_SLUGS = new Set(
  Object.keys(SUPPLIER_METADATA).filter((s) => !SUPPLIER_METADATA[s].coming_in),
);
```

The vitest source-inspection tests (in `supplier-settings.test.jsx`) enforce:

1. Every slug in `WIRED_SLUGS` has all 7 required wired fields.
2. Every unwired slug has `coming_in` + `display_name` + `tagline`.
3. `WIRED_SLUGS` = `{poolcorp, siteone, ewing}` (kept in sync with backend's `_WIRED_SYNC_SLUGS`).

Adding Heritage in Phase 54e is a 3-line diff to this file (drop `coming_in`, add the 7 wired fields) — no changes to `SupplierSettings.jsx`.

## Test-count delta

### Backend (`pytest`)
| Suite | Before | After | Δ |
| --- | --- | --- | --- |
| `test_phase54a_suppliers_skeleton.py` | 14 | 14 | 0 (updated in place) |
| `test_phase54b_poolcorp_connector.py` | 9 | 9 | 0 |
| `test_phase54c_siteone_connector.py` | 18 | 18 | 0 (one test updated in place) |
| `test_phase54d_ewing_connector.py` | 0 | 17 | **+17** |

**Phase 53+54 curated total: 74 → 88** (still 100 % green in **~18 s**).

### Frontend (`vitest`)
| Suite | Before | After | Δ |
| --- | --- | --- | --- |
| `supplier-settings.test.jsx` | 19 | 26 | **+7** |

**Full vitest: 1408 → 1415** (still 100 % green).

## Confirmation of invariants (post-ship)

| Gate | Result |
| --- | --- |
| `yarn vitest run` | **1415 / 1415 pass** |
| `yarn lint` | exit **0** |
| Mobile Jest | **236 / 236 pass** (unchanged) |
| Phase 53+54 curated backend suite | **88 / 88 pass** |
| Playwright live network calls in tests | **0** (fully mocked) |
| Existing 54b/54c invariants (Pool360 + SiteOne tests) | **untouched, still green** |

## Screenshots

Captured live against `poolscape-audit.preview.emergentagent.com` with an
admin JWT primed into `localStorage`. See:

- `/tmp/phase54d_all_five_cards.jpg` — full-page overview showing Pool360, SiteOne, Ewing (all "Connected" green pills) + Heritage/ePoolSupply cards with "Coming in Phase 54e" pulled from metadata.
- `/tmp/phase54d_ewing_card.jpg` — focused view of the Ewing card confirming metadata-driven title ("Ewing Irrigation"), tagline ("Ewing Irrigation B2B pricebook sync (Playwright headless)."), username label ("Ewing username"), all five action buttons, legal disclaimer, and a real Recent-syncs row showing the Chromium-missing background-task error.

## 🟡 OPERATOR NOTE — Chromium NOT installed on preview / prod containers

**Surface, do not act on.** The Playwright chromium binary is missing from
the preview backend container. The connector code paths all handle this
gracefully (background sync writes the error into the job row; test-connection
classifies it as `unknown` and the UI renders the red badge) — but no live
sync can actually reach a wholesaler yet.

**Recommended ops mini-phase before 54e ships**:

1. Add a container startup hook that runs `playwright install chromium`
   (approx 200 MB one-time download; write to `/root/.cache/ms-playwright/`
   which persists across supervisor restarts).
2. Alternatively bake the browser into the container image via a
   `Dockerfile.RUN python -m playwright install --with-deps chromium` step —
   avoids the download at every cold-start.
3. Verify with a smoke check: from the running backend container run
   `python -c "from playwright.sync_api import sync_playwright; \
   sync_playwright().start().chromium.launch(headless=True).close()"` —
   expect zero output + exit code 0.

Live Ewing verification (and Pool360, SiteOne) is deferred until:
- The operator provides real wholesaler credentials, AND
- Chromium is installed per above.

Phase 54e's scheduled cron will fail loudly (into the sync-jobs error log,
not silently) if this ops step isn't done — but that's a bad first
impression. Better to solve it before 54e ships.

## Deviations from scope

**None.** All items in the locked scope were shipped as specified:

- ✅ `EwingConnector` + selectors mirror SiteOne exactly.
- ✅ `POST /api/suppliers/ewing/sync` wired (202 + background task, dedupe, soft-delete, role gate, no-creds 400).
- ✅ `SUPPLIER_METADATA` extraction with all requested fields per slug + `coming_in` on stubs.
- ✅ `WiredSupplierCard` + `ComingSoonCard` now consume metadata; hard-coded strings removed.
- ✅ Source-inspection tests on metadata shape.
- ✅ Full backend + vitest coverage for Ewing card + metadata.
- ✅ Playwright fully mocked; no live Ewing network.
- ✅ All invariant gates green.
