# Phase K55 · Feb-2026 — SuperCool + HomeWorks integration-removal DIAGNOSIS

**Status**: Diagnosis only. No code changes. Awaiting user green light on
removal plan.

**Guiding principle (from user brief)**: Preserve historical DB data
(`source: "supercool"`, `homeworks_*` fields, and every `homeworks_*`
collection). This is a code migration, not a data purge.

---

## 1 · SuperCool footprint

SuperCool is scoped narrower than HomeWorks — image-generation only,
via the Phase 26 MCP-OAuth pattern.

### Backend

| File | Role | Removal action |
|---|---|---|
| `backend/services/media_provider.py` | Contains `SupercoolProvider` class + `_tenant_supercool_connected()` helper. Also the ONLY place the provider adapter lives — the `EmergentFallbackProvider` is right below it. | **KEEP the module but delete the `SupercoolProvider` class + `_tenant_supercool_connected`.** `pick_provider(tenant_id)` becomes a single-branch return of `EmergentFallbackProvider()`. |
| `backend/services/soshie/ai_image_gen.py` | Calls `pick_provider()` — automatically flows to Emergent after removal, no change needed. | KEEP as-is |
| `backend/services/mcp_oauth_client.py` | Shared MCP-OAuth client, also used by HomeWorks BYO OAuth flow (see §2). | KEEP — shared plumbing |
| `backend/routers/integrations_supercool.py` | `/api/integrations/supercool/*` connect/disconnect endpoints | DELETE FILE. Also remove `include_router` at `server.py:417-418`. |
| `backend/routers/media_gen.py` | `pick_provider` consumer. `_daily_limit()` reads `SUPERCOOL_DAILY_IMAGE_LIMIT` env. | KEEP, but rename the env var to `AI_MEDIA_DAILY_IMAGE_LIMIT` (see §5). |
| `backend/tests/test_soshie_ai_image_gen.py` | Uses `SupercoolProvider` in fixtures | UPDATE — mock `EmergentFallbackProvider` directly |
| `backend/tests/test_phaseb_image_gen.py` | Same | UPDATE |
| `backend/tests/test_mcp_oauth_supercool.py` | Tests the MCP-OAuth flow specifically for SuperCool | DELETE (SuperCool endpoints gone) |

### Frontend

| File | Removal action |
|---|---|
| `frontend/src/pages/settings/integrations/SupercoolIntegrationPage.jsx` | DELETE FILE |
| `frontend/src/pages/settings/IntegrationsPages.jsx` | Remove SuperCool tile row |
| `frontend/src/pages/marketing/ContentStudioPage.jsx` | Remove "SuperCool connected" badge/status; keep image-gen flow (routes through backend which auto-picks Emergent) |
| `frontend/src/pages/marketing/GbpPostsPage.jsx` | Same |
| `frontend/src/pages/ops/RepairCalculatorPage.jsx` | Grep hit — verify + remove if wired |
| `frontend/src/App.js` | Remove route `settings/integrations/supercool` (line 774) |
| `frontend/src/test/phase26-supercool-integration.test.jsx` | DELETE |
| `frontend/src/test/settings-nav-old-routes.test.jsx` | Remove SuperCool row if present |
| `frontend/src/test/phaseb-content-studio.test.jsx` | UPDATE — assert Emergent-only path |
| `frontend/src/test/phaseb-followups.test.jsx` | UPDATE |
| `frontend/src/test/phase30-4-confirm-modal-migration.test.jsx` | UPDATE if SuperCool referenced |

### Mobile

| File | Removal action |
|---|---|
| `mobile/app/marketing/content-studio.tsx` | Remove SuperCool status chip; keep gen flow |
| `mobile/app/settings/integrations/supercool.tsx` | DELETE FILE |
| `mobile/.expo/types/router.d.ts` | Regenerated automatically |

### DB / Data preservation

- `db.mcp_oauth_tokens` where `provider="supercool"` — **PRESERVE**. No delete, no migration.
- `db.generated_media` where `provider="supercool"` — **PRESERVE**. These are historical images tenants have already used in campaigns.
- No collections drop, no field strip.

### Env vars to remove

- `SUPERCOOL_URL`
- `SUPERCOOL_MCP_URL`
- `SUPERCOOL_DAILY_IMAGE_LIMIT` — rename to `AI_MEDIA_DAILY_IMAGE_LIMIT` (see §5). Old name kept as fallback for one release cycle.

### Cron / scheduler

None — SuperCool has no scheduled tasks.

---

## 2 · HomeWorks footprint

HomeWorks is a **deep** integration — data import, dispatcher, cron, OAuth, MCP client, dedupe, mapping, delta-sync. Removal is meaningfully larger than SuperCool.

### Backend — services (14 modules)

| Module | Role | Removal action |
|---|---|---|
| `backend/services/homeworks/__init__.py` | Package entry | DELETE PACKAGE |
| `backend/services/homeworks/dedupe.py` | Idempotency layer (queries `homeworks_id` field) | DELETE |
| `backend/services/homeworks/mapping.py` | Raw HomeWorks doc → Aquaterra shape | DELETE |
| `backend/services/homeworks/copilot_scraper.py` | Legacy scraper path | DELETE |
| `backend/services/homeworks_mcp/__init__.py` | Package entry | DELETE PACKAGE |
| `backend/services/homeworks_mcp/client.py` | MCP client (uses `HOMEWORKS_MCP_URL`) | DELETE |
| `backend/services/homeworks_mcp/oauth_metadata.py` | OAuth discovery | DELETE |
| `backend/services/homeworks_mcp/token_refresh.py` | Token refresh | DELETE |
| `backend/services/homeworks_mcp/token_store.py` | Persists to `db.homeworks_byo_integrations` | DELETE (module); leave collection intact |
| `backend/services/homeworks_mcp/state_store.py` | CSRF state store (`db.homeworks_byo_oauth_states`) | DELETE (module); leave collection intact |
| `backend/services/homeworks_mcp/pkce.py` | PKCE helper | DELETE |
| `backend/services/homeworks_mcp/queries.py` | Read layer over HW API | DELETE |
| `backend/services/homeworks_mcp/importer_base.py` | Base class for the 4 importers | DELETE |
| `backend/services/homeworks_mcp/active_customers_importer.py` | Active-customer sync | DELETE |
| `backend/services/homeworks_mcp/inactive_customers_importer.py` | Inactive-customer sync | DELETE |
| `backend/services/homeworks_mcp/pricebook_importer.py` | Pricebook sync | DELETE |
| `backend/services/homeworks_mcp/delta_sync_importer.py` | Delta sync | DELETE |
| `backend/services/homeworks_mcp/import_dispatcher.py` | Cron dispatcher registered at `server.py:1887` | DELETE |
| `backend/services/homeworks_mcp_client.py` | Older BYO client (comment at line 15 mentions `db.homeworks_byo_oauth_states`) | DELETE (module); leave collections intact |

### Backend — routers (9 files)

| Router | Endpoints | Removal action |
|---|---|---|
| `backend/routers/homeworks_integration.py` | `/api/integrations/homeworks/*` (BYO OAuth) | DELETE. Remove `include_router` at `server.py:446`. |
| `backend/routers/homeworks_import.py` | `/api/settings/import/homeworks/*` | DELETE. Remove `include_router` at `server.py:600-601`. |
| `backend/routers/integrations_homeworks_oauth.py` | env-var-driven OAuth flow | DELETE. Remove `include_router` at `server.py:424`. |
| `backend/routers/integrations_homeworks_imports.py` | Import orchestration | DELETE. Remove `include_router` at `server.py:428`. |
| `backend/routers/integrations_homeworks_active_imports.py` | Active-customers subset | DELETE. Remove `include_router` at `server.py:430`. |
| `backend/routers/integrations_homeworks_delta_sync.py` | Delta-sync trigger | DELETE. Remove `include_router` at `server.py:434`. |
| `backend/routers/integrations_homeworks_income_items.py` | Income-items subset | DELETE. Remove `include_router` at `server.py:436`. |
| `backend/routers/integrations_homeworks_dispatcher.py` | Dispatcher admin ops | DELETE. Remove `include_router` at `server.py:440`. |
| `backend/routers/customer_tags.py`, `backend/routers/pricebook_manual_pricing.py`, `backend/routers/properties.py`, `backend/routers/suppliers.py`, `backend/routers/customers.py` | Grep hits — the reference is to `homeworks_id` / `homeworks_created_at` fields on existing docs. **These fields are historical audit trail.** | KEEP the file. AUDIT: leave the `homeworks_*` field read-through logic in place (still surfaces historical values), just no write path. |

### Backend — dispatcher registration

`backend/server.py:1882-1890` — the cron dispatcher registration:

```py
try:
    from services.homeworks_mcp.import_dispatcher import register_dispatcher
    register_dispatcher(...)
except Exception as e:
    logger.warning(f"[queue-item-5c] homeworks import dispatcher install failed: {e}")
```

**REMOVE** the try/except block entirely.

### Backend — tests

15 test files (`backend/tests/test_homeworks_*.py` + `test_importer_base.py`, `test_import_dispatcher.py`, `test_pricebook_importer.py`, `test_hydrate_homeworks_pricebook_prices.py`, `test_customers_bulk_status_change.py`). **DELETE all HW-specific tests.** For `test_customers_bulk_status_change.py`, audit — if it only tests HW-specific tag logic, delete; otherwise strip HW cases.

### Backend — migrations

- `backend/migrations/task_p33_seed_customer_tags_catalog.py` — grep hit. AUDIT — if HW-specific tags are seeded, keep the migration idempotent (already run) but don't run again. Don't delete migration files; they're history.

### Backend — scripts (10 files)

- `backend/scripts/homeworks_run_active_import.py`
- `backend/scripts/homeworks_run_import.py`
- `backend/scripts/homeworks_register_client.py`
- `backend/scripts/homeworks_schema_pull.py`
- `backend/scripts/homeworks_run_pricebook.py`
- `backend/scripts/hydrate_homeworks_pricebook_prices.py`
- `backend/scripts/backfill_pricebook_supplier_prices.py`
- `backend/scripts/homeworks_run_delta_sync.py`
- `backend/scripts/audit_pricebook_missing_supplier_prices.py`
- `backend/scripts/backfill_status_tags.py`

**DELETE all HW-only launchers.** The two `backfill_*` scripts and `audit_*` are HW-adjacent; audit each — if they migrate/audit HW-imported data specifically, keep as-is (they're archival tools) or move to `backend/scripts/archive/homeworks/`.

### Backend — models

- `backend/models.py` — grep hit. AUDIT — likely has a Pydantic `HomeworksIntegration` / `HomeworksToken` model. KEEP the model type (for existing collection reads) but move to `backend/homeworks_integration_models.py` (already exists as a separate file) so `models.py` doesn't carry HW-specific baggage.
- `backend/homeworks_integration_models.py` — KEEP the file (schema for historical collections).

### Frontend

| File | Removal action |
|---|---|
| `frontend/src/pages/settings/HomeworksImport.jsx` | DELETE |
| `frontend/src/pages/admin/integrations/HomeworksIntegrationPage.jsx` | DELETE |
| `frontend/src/pages/admin/integrations/HomeworksOAuthCallback.jsx` | DELETE |
| `frontend/src/pages/settings/IntegrationsPages.jsx` | Remove HW tile |
| `frontend/src/pages/PrivacyPolicy.jsx` | Remove HW reference from the third-party-data-processors section |
| `frontend/src/components/settings/HomeworksIntegrationCard.jsx` | DELETE |
| `frontend/src/components/settings/HomeworksImportCenter.jsx` | DELETE |
| `frontend/src/nav/adminNav.js:235,240` | Remove "Homeworks (POC)" + "Import from Homeworks" nav entries |
| `frontend/src/App.js:738,776,777` | Remove 3 HW routes |
| Test files: `homeworks-import.test.jsx`, `homeworks-integration-card.test.jsx`, `homeworks-integration-page.test.jsx`, `queue-item-5-homeworks-import-center.test.jsx`, `phase7-api-client-delete-verb.test.jsx`, `task-a-b-pricebook-and-dispatcher.test.jsx`, `followup-bundle-items-5-2-4-3.test.jsx`, `phase21-privacy-policy-content.test.jsx` | DELETE (HW-only) or UPDATE (mixed) |

### Mobile

- `mobile/src/nav/adminNav.ts` — remove HW nav entry.

### Env vars to remove

- `HOMEWORKS_MCP_URL`
- `HOMEWORKS_OAUTH_METADATA_URL`
- `HOMEWORKS_CLIENT_ID`
- `HOMEWORKS_CLIENT_SECRET` (if set anywhere — audit)
- `HOMEWORKS_PROD_HOST`

### DB collections — PRESERVE (do not drop, do not strip)

- `db.homeworks_byo_integrations` — OAuth token store for BYO tenants
- `db.homeworks_byo_oauth_states` — CSRF state store (short-TTL, self-expires)
- `homeworks_import_runs` — historical import job log
- `homeworks_import_state` — per-tenant sync cursors
- Per-doc fields: `homeworks_id`, `homeworks_created_at`, `homeworks_customer_id`, `homeworks_line_id`, `homeworks_quote_id`, `homeworks_invoice_id`, `homeworks_scoped_id` on `customers`, `jobs`, `invoices`, `quotes`, `pricebook_items`, `properties`, `suppliers` — historical audit trail, keep.

---

## 3 · Proposed rollout sequence (single commit is risky — recommend 3 slices)

### Slice K55.a — Frontend + nav removal
1. Delete FE pages + components + tests listed above.
2. Remove nav entries + `App.js` routes.
3. Remove SuperCool + HomeWorks tiles from `IntegrationsPages.jsx`.
4. Ship + smoke.

### Slice K55.b — Backend routers + cron dispatcher removal
1. Remove `include_router` calls in `server.py` (lines 417-418, 424, 428, 430, 434, 436, 440, 446, 600-601).
2. Remove the `try/except` cron dispatcher registration at `server.py:1882-1890`.
3. Delete router files.
4. Delete service modules.
5. Delete or archive `backend/scripts/homeworks_*.py`.
6. Delete or update backend tests (leave historical collection reads working — sample-audit `test_customers_bulk_status_change.py`).
7. Ship + backend smoke.

### Slice K55.c — Env var cleanup + docs
1. Remove HW+SC env vars from `.env.example`.
2. Instruct user to remove them from Prod after Slice K55.b lands.
3. Update `memory/env_reference.md` and `memory/env_vars.md`.
4. Update `memory/homeworks_integration.md` — mark deprecated with the date + K55 slice reference.

## 4 · Risk flags for user

1. **Historical HW-imported customer data** stays in `db.customers` with `homeworks_id` fields set. These docs are read/written normally by the app — the `homeworks_id` is just metadata now. Users won't see any change in the customer list. No data loss.
2. **BYO OAuth token store** (`db.homeworks_byo_integrations`) is preserved. If in the future you want to re-enable HW, the tokens are still there and re-registering the OAuth client will pick them back up. (One-line note in `memory/homeworks_integration.md`.)
3. **Third-party linkers** — if any external system was calling `/api/integrations/homeworks/*` endpoints directly (webhook, Zapier), they'll 404 after removal. Not currently known to exist; user should confirm no external caller.
4. **HomeWorks-only tags** — the `task_p33` migration seeded HomeWorks-specific customer tags. Those tags will still exist on customer docs after removal. UI will still render them because tags are text-based. No cleanup needed unless user explicitly wants to strip them.

## 5 · What to name the K56 env var rename target

`SUPERCOOL_DAILY_IMAGE_LIMIT` → `AI_MEDIA_DAILY_IMAGE_LIMIT` (provider-agnostic, K56-friendly).

---

## Files inspected (not changed)

* `backend/server.py` — router registrations + dispatcher registration
* `backend/services/media_provider.py` — provider adapter pattern
* `backend/routers/integrations_supercool.py`
* `backend/services/homeworks_mcp/*` — 12 modules
* `backend/services/homeworks_mcp_client.py`
* `backend/services/homeworks/*` — 4 modules
* `backend/services/soshie/ai_image_gen.py` — consumer of `pick_provider`
* `frontend/src/nav/adminNav.js:235,240`
* `frontend/src/App.js` — 3 HW routes + 1 SC route
* `frontend/src/pages/PrivacyPolicy.jsx`
* Test file inventory (grep-scanned, not opened)

## Files NOT changed

None. Diagnosis-only pass.
