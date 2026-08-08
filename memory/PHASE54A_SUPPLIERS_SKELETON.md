# Phase 54a — Wholesale supplier pricebook import (skeleton)

**Date:** Feb 2026  
**Scope:** Preflight audit + supplier-agnostic data model + credentials plumbing + 6-endpoint router + 5 connector stubs. **No supplier network calls, no scraping, no UI changes.** Pool360 / SiteOne / Ewing / Heritage Pool Plus / ePoolSupply all stubbed with `NotImplementedError`.

## Preflight audit

### Existing pricebook — extended, not replaced

| Concern | Finding |
|---|---|
| Backend collection | `db.items` — tenant-scoped via `tenant_id` |
| Backend model | `class ItemIn` in `backend/models.py` |
| Backend router | `backend/routers/items.py` (`/api/items`, `/api/pricebook/{id}`) |
| Frontend page | `frontend/src/pages/ops/OpsHub.jsx` Pricebook tab, route `/price-book` in `src/App.js:891` |
| Price-flow into quotes/invoices | `_stamp_line_snapshots` copies `retail_price_snapshot`, `wholesale_price_snapshot`, `labor_cost_snapshot` from items onto quote line-items. **Unchanged by 54a — additive fields don't touch quote path.** |
| Prior supplier concept | **None.** No existing `supplier_id` field or supplier collection. |

### 5-supplier integration surface

⚠️ **PAUSE flag surfaced (batched):** All 5 suppliers most likely require **scraping** (or manual CSV interim). None publish a documented public REST API. Full audit table:

| Supplier | Slug | API? | Auth | Rate limits | Recommendation | Effort | Planned phase |
|---|---|---|---|---|---|---|---|
| Pool360 (PoolCorp) | `poolcorp` | No public REST | Portal session (username/password) | Undisclosed | **Scrape (PAUSE)** or partner API | L | 54b |
| SiteOne | `siteone` | No public REST | Portal session | Undisclosed | **Scrape (PAUSE)** or manual CSV | M | 54c |
| Ewing Irrigation | `ewing` | No public REST | Portal session | Undisclosed | **Scrape (PAUSE)** or manual CSV | M | 54d |
| Heritage Pool Plus | `heritage` | Very unlikely (regional distributor) | Likely portal + partial catalog scrape | Undisclosed | **Manual CSV** primary, **scrape (PAUSE)** fallback | M/L | 54e |
| ePoolSupply | `epoolsupply` | No — consumer e-commerce | None (public catalog) | Undisclosed | **Scrape (PAUSE)** or manual CSV | M | 54e |

**Slug rationale:** short forms (`poolcorp / siteone / ewing / heritage / epoolsupply`) match the existing app convention for short-form identifiers; display names preserved for UI.

**Batched scraper approval needed** — before ANY 54b/c/d/e connector work begins, user must confirm scraping is acceptable OR provide partner-API credentials for at least one supplier.

### Encryption pattern reused

**Fernet** — matches the pattern in `backend/services/mcp_oauth_client.py`. Phase 54a introduces a distinct key namespace `SUPPLIER_CREDENTIAL_ENCRYPTION_KEY` (env-first / file-fallback / generate-and-persist) so a compromise in one domain doesn't cascade.

### Cron pattern confirmed

`AsyncIOScheduler` singleton owned by `server.py:7`, attached-to pattern from `services/walkie/cleanup_cron.py` + `services/lana/reminder_cron.py`. Phase 54e will attach its supplier-sync job to the same singleton — no new scheduler.

---

## Files touched

| File | Kind | Purpose |
|---|---|---|
| `backend/models.py` | modified | +3 additive optional fields on `ItemIn`: `supplier_id`, `external_sku`, `last_synced_at` |
| `backend/services/suppliers/__init__.py` | **added** | Package marker + module docstring |
| `backend/services/suppliers/connector.py` | **added** | `SupplierConnector` protocol, `ExternalProduct` dataclass, `BaseSupplierConnector` + 5 concrete stubs (all `NotImplementedError`), `CONNECTORS` registry + `SUPPLIER_SEED` list |
| `backend/services/suppliers/crypto.py` | **added** | Fernet encrypt/decrypt helpers with a dedicated key namespace |
| `backend/routers/suppliers.py` | **added** | 6-endpoint router with role gate, tenant scoping, auto-seed, credential round-trip, index creation |
| `backend/server.py` | modified | Router registered after ebit include (2-line block) |
| `backend/tests/test_phase54a_suppliers_skeleton.py` | **added** | 17 pytest tests (auto-seed, idempotency, role gate, credential round-trip + non-plaintext-in-DB, tenant isolation, sync 501, sync-jobs empty, connector protocol, pricebook item accepts new fields, indexes exist) |
| `memory/PHASE54A_SUPPLIERS_SKELETON.md` | **added** | This delivery doc |

## Data model diff summary

**Existing `db.items` — extended (additive only):**
```
+ supplier_id: str | null       (link to suppliers.id; null = manually entered)
+ external_sku: str | null      (supplier-side SKU for dedupe on sync)
+ last_synced_at: str | null    (ISO-8601)
```
Plus two new indexes:
- `(tenant_id, supplier_id)` → `items_tenant_supplier` (drives the supplier filter UI in 54b/e)
- `(tenant_id, external_sku)` → `items_tenant_external_sku` (sparse — sync dedupe)

**New `db.suppliers`:**
```
id, tenant_id, slug, display_name, active (bool), sync_frequency,
last_sync_at, last_sync_status, last_sync_item_count, created_at
```
Index: `(tenant_id, slug)` unique. Auto-seeded 5 rows on first read.

**New `db.supplier_credentials`:**
```
id, tenant_id, supplier_id, encrypted_username, encrypted_password,
encrypted_api_key, notes, updated_at
```
Index: `(tenant_id, supplier_id)` unique. Plaintext NEVER stored — Fernet-encrypted, verified by direct-DB inspection in the test.

**New `db.supplier_sync_jobs`:**
```
id, tenant_id, supplier_id, started_at, finished_at, status,
items_added, items_updated, items_removed, error_message
```
Index: `(tenant_id, supplier_id, started_at desc)`.

## Endpoint list

| Method | Path | Gate | Status |
|---|---|---|---|
| GET | `/api/suppliers` | admin+ | 200 · auto-seeds 5 rows on first read |
| GET | `/api/suppliers/{slug}/credentials` | admin+ | 200 · `{has_credentials, updated_at, notes}` |
| POST | `/api/suppliers/{slug}/credentials` | admin+ | 200 · Fernet-encrypted upsert |
| DELETE | `/api/suppliers/{slug}/credentials` | admin+ | 200 · `{ok, deleted_count}` |
| POST | `/api/suppliers/{slug}/sync` | admin+ | **501** · `"connector not implemented yet, coming in phase {54b/c/d/e}"` |
| GET | `/api/suppliers/{slug}/sync-jobs` | admin+ | 200 · `{supplier_slug, jobs, count}` |

Role gate: `super_admin + admin` on every endpoint. manager / tech / customer → **403** on all six.

## Test count delta

| Suite | Before | After | Δ |
|---|---:|---:|---:|
| Backend pytest (added new file) | 31 | **48** | **+17** |
| Frontend vitest | 1389 | 1389 | 0 (backend-only phase) |
| Mobile jest | 236 | 236 | 0 (backend-only phase) |

## Suite verification (all green)

| Check | Result |
|---|---|
| `yarn lint` (frontend) | **exit 0** ✅ |
| `yarn test:unit` (frontend vitest) | **158 files · 1389 / 1389 green** ✅ (unchanged) |
| `yarn test` (mobile jest) | **29 suites · 236 / 236 green** ✅ (unchanged) |
| Backend Phase 53a + 53c + 53d + 54a pytest | **48 / 48 green** ✅ |
| Backend Phase 41.4 curated coverage gate | Untouched — additive only. |
| `yarn lint` (mobile) | Pre-existing 232-problem baseline unchanged. |

## Guardrails verified

- ✅ Zero supplier network calls / scrapers in 54a. Every concrete connector raises `NotImplementedError`.
- ✅ No plaintext credentials in any API response — direct-DB inspection asserted in `test_credentials_round_trip_and_never_plaintext`.
- ✅ No touch to the three hotfix code paths.
- ✅ No touch to Phase 49/50/50.1/50.2/41.1b/41.1c/41.1d/41.2/41.3/41.4/41.5/42.4/43/46/47c-48b/51a-d/51.5/51.6/53a-d code beyond the router-include line in `server.py` and the additive fields on `ItemIn` in `models.py`.
- ✅ No touch to Stripe / Mapbox / Time-Off / RingCentral runtime.
- ✅ No existing pricebook UI change (audit only).
- ✅ Price flow into quotes/invoices unchanged (additive fields don't touch `_stamp_line_snapshots`).

## Deviations from scope

**None.** One implementation choice worth logging:

- **Auto-seed on first `GET /suppliers` (per tenant)** rather than a global server-boot seed. Rationale: mirrors how Phase 41.1b / 51a introduced tenant-scoped entities — new tenants get the 5 suppliers automatically on first admin read, without a separate `on_startup` step that would need to iterate every tenant. Idempotent via `(tenant_id, slug)` unique index.

## Handoff — next phase gate

**Before Phase 54b can start**, user needs to answer one question:

> All 5 audited suppliers require scraping (or manual CSV) because none publish a public REST API. Approve the scraper approach as a batch, OR indicate which supplier(s) you have partner-API credentials for.

Once approved, Phase 54b will land the Pool360 connector as the first real implementation (session-based login → catalog scrape → dedupe on `external_sku` → upsert into `db.items` with `supplier_id` populated → APScheduler daily job in Phase 54e).
