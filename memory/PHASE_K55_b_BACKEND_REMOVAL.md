# Phase K55.b · Feb-2026 — SuperCool + HomeWorks backend removal

**Status**: Shipped to preview. Backend restarted clean, no import errors.
- Route count: **1672 → 1622** (−50 as expected: 44 HomeWorks + 6 SuperCool paths gone).
- All 3 canonical HW/SC endpoints (`/api/integrations/homeworks/status`,
  `/api/integrations/supercool/status`, `/api/settings/import/homeworks/status`)
  return **404 clean**.
- 20/20 tests pass on the K5x-adjacent + K53.1 + Soshie image-gen suites.
  ``test_customers_bulk_status_change.py`` shows 2 pre-existing RBAC-fixture
  failures unrelated to K55.b (Admin-access-required from admin seed).

## External-caller guardrail — PASS

`/var/log/supervisor/backend.*.log` scan: every historical inbound hit
to `/api/integrations/homeworks/*` originated from cluster-internal
IPs (`10.79.139.x`) or localhost (`127.0.0.1`). No external UAs. Since
K55.a shipped, zero new HW inbound hits observed. Nginx access log
has zero HW/SC references. **Safe to proceed** — no external
webhook/Zapier caller impact.

## Server.py surgery

- Removed **9 `include_router` blocks** + their `from routers import ...`
  imports:
    - `integrations_supercool` (line 417-418 pre-edit)
    - `integrations_homeworks_oauth`
    - `integrations_homeworks_imports`
    - `integrations_homeworks_active_imports`
    - `integrations_homeworks_delta_sync`
    - `integrations_homeworks_income_items`
    - `integrations_homeworks_dispatcher`
    - `homeworks_integration` (BYO OAuth)
    - `homeworks_import` (Copilot CRM importer)
- Removed **cron dispatcher** try/except registration block (was
  `services.homeworks_mcp.import_dispatcher.register_dispatcher`).
  The 30-second scheduler tick no longer polls the (now-deleted)
  ``homeworks_import_runs`` queue.  Historical runs stay in the
  collection as audit trail.
- Removed **`mcp_oauth_client.ensure_indexes()`** startup bootstrap
  (the module was only used by SuperCool; deleted below).

## Routers deleted (9 files)

- `routers/integrations_supercool.py`
- `routers/homeworks_integration.py`
- `routers/homeworks_import.py`
- `routers/integrations_homeworks_oauth.py`
- `routers/integrations_homeworks_imports.py`
- `routers/integrations_homeworks_active_imports.py`
- `routers/integrations_homeworks_delta_sync.py`
- `routers/integrations_homeworks_income_items.py`
- `routers/integrations_homeworks_dispatcher.py`

## Services deleted

- `services/mcp_oauth_client.py` — SuperCool-only OAuth 2.1 client.
- `services/homeworks/` — full package (`__init__`, `dedupe`,
  `mapping`, `copilot_scraper`).
- `services/homeworks_mcp/` — full package (12 modules: client,
  oauth_metadata, token_refresh, token_store, state_store, pkce,
  queries, importer_base, active_customers_importer,
  inactive_customers_importer, pricebook_importer,
  delta_sync_importer, import_dispatcher).
- `services/homeworks_mcp_client.py` — older BYO client.

## Services simplified

- **`services/media_provider.py`** — the ``SupercoolProvider``
  class, ``_tenant_supercool_connected`` helper, and
  ``_normalize_supercool_image_result`` helper are gone. The
  ``SUPERCOOL_MCP_URL`` env read + ``from services import
  mcp_oauth_client`` import are gone. ``pick_provider(tenant_id)``
  now returns ``EmergentFallbackProvider()`` unconditionally — the
  ``tenant_id`` arg is retained for consumer-compat (soshie's
  `ai_image_gen`, routers/media_gen call ``await pick_provider(tid)``)
  but is unused.  This is the K55.b → K56 seam; the K56 slice will
  simply confirm this behaviour + rename the env var
  ``SUPERCOOL_DAILY_IMAGE_LIMIT`` → ``AI_MEDIA_DAILY_IMAGE_LIMIT``.

## Scripts deleted (10 total)

- `scripts/homeworks_run_active_import.py`
- `scripts/homeworks_run_import.py`
- `scripts/homeworks_register_client.py`
- `scripts/homeworks_schema_pull.py`
- `scripts/homeworks_run_pricebook.py`
- `scripts/homeworks_run_delta_sync.py`
- `scripts/hydrate_homeworks_pricebook_prices.py` — HW-slug hardcoded.
- `scripts/backfill_pricebook_supplier_prices.py` — imported from
  ``hydrate_homeworks_pricebook_prices``; transitively broken.  HW-
  specific hydration path.
- `scripts/audit_pricebook_missing_supplier_prices.py` — imported
  from ``hydrate_homeworks_pricebook_prices``; HW-specific audit.

## Scripts KEPT

- `scripts/backfill_status_tags.py` — only mentions HW in a doc
  comment ("preserves Homeworks-imported tags"); doesn't import
  HW code. General-purpose backfill.

## Tests deleted (18 total)

- `tests/test_mcp_oauth_supercool.py`
- `tests/test_phaseb_image_gen.py` — 24 refs to
  ``SupercoolProvider`` / ``mcp_oauth``; entire suite gated on
  SC-first behaviour.  New K56 tests will re-cover the Emergent-only
  path.
- `tests/test_homeworks_discount_field_drop.py`
- `tests/test_homeworks_import_commit.py`
- `tests/test_homeworks_import_inactive.py`
- `tests/test_homeworks_import_scaffold.py`
- `tests/test_homeworks_importer.py`
- `tests/test_homeworks_invoices_payments.py`
- `tests/test_homeworks_jobs_recurring.py`
- `tests/test_homeworks_mcp_client.py`
- `tests/test_homeworks_mcp_defensive_non_2xx_logging.py`
- `tests/test_homeworks_notes_photos.py`
- `tests/test_homeworks_oauth.py`
- `tests/test_homeworks_router.py`
- `tests/test_homeworks_scraper.py`
- `tests/test_hydrate_homeworks_pricebook_prices.py`
- `tests/test_import_dispatcher.py`
- `tests/test_importer_base.py`
- `tests/test_pricebook_importer.py`
- `tests/test_pricebook_backfill.py` — depended on deleted
  ``backfill_pricebook_supplier_prices`` script.

## Tests KEPT (mixed / cross-cutting)

- `tests/test_soshie_ai_image_gen.py` — passes. The single
  ``supercool`` reference is in a docstring; the tests
  themselves mock ``pick_provider``.
- `tests/test_soshie_publish_blog_wire.py` — passes.
- `tests/test_customers_bulk_status_change.py` — 2 pre-existing
  RBAC-fixture failures unrelated to K55.b; other cases pass.

## Preserved intact (per K55 diagnosis principles — DO NOT touch)

### DB collections
- `db.homeworks_byo_integrations`
- `db.homeworks_byo_oauth_states`
- `db.homeworks_import_runs`
- `db.homeworks_import_state`
- `db.mcp_oauth_tokens` where `provider="supercool"`
- `db.generated_media` where `provider="supercool"`

### Per-doc audit fields (still queryable, still rendered by list views)
- `homeworks_id`, `homeworks_created_at`, `homeworks_customer_id`,
  `homeworks_line_id`, `homeworks_quote_id`, `homeworks_invoice_id`,
  `homeworks_scoped_id` on `customers`, `jobs`, `invoices`,
  `quotes`, `pricebook_items`, `properties`, `suppliers`.
- The read paths in `routers/customers.py`, `routers/suppliers.py`,
  `routers/pricebook_manual_pricing.py`, `routers/properties.py`,
  `routers/customer_tags.py` still surface these fields. They're
  passive metadata now — no write path exists.

### Models
- `backend/homeworks_integration_models.py` — Pydantic schemas
  for the preserved collections. Kept in-tree so future code that
  needs to read historical rows has typed access.  Not imported
  by any live router post-K55.b.

## Cron dispatcher shutdown check

The APScheduler instance uses AsyncIOScheduler; deleting the
``register_dispatcher`` call means the job simply is never scheduled.
No asyncio task is orphaned. Verified via a clean
``sudo supervisorctl restart backend`` — startup log shows no
scheduler errors and the previous `[queue-item-5c] homeworks import
dispatcher install failed` warning line is gone.

## Env vars — still configured in `.env` (K55.c will remove)

- `SUPERCOOL_URL`
- `SUPERCOOL_MCP_URL`
- `SUPERCOOL_DAILY_IMAGE_LIMIT`
- `HOMEWORKS_MCP_URL`
- `HOMEWORKS_OAUTH_METADATA_URL`
- `HOMEWORKS_CLIENT_ID`
- `HOMEWORKS_CLIENT_SECRET` (if set)
- `HOMEWORKS_PROD_HOST`

None of these are read anywhere in the codebase post-K55.b (grep
verified) — they're dormant. **K55.c will strip them from
`.env.example` + docs.**

## Rollback

Single `git revert` restores all deleted files + the server.py
registrations + the cron dispatcher block. Because DB state was
untouched, any restored code path would immediately pick up the
existing historical data. Backwards-compatible rollback.

## Regression sweep for the tester

1. Backend health: `curl $API/api/health` → 200.
2. Route inventory: `curl $API/api/openapi.json | jq '.paths | length'`
   should be **1622**.
3. Every HW/SC endpoint should 404:
   - `/api/integrations/homeworks/status`
   - `/api/integrations/supercool/status`
   - `/api/settings/import/homeworks/status`
   - `/api/integrations/homeworks/dispatcher/status`
4. Content Studio image gen still works (routes through Emergent
   `nano-banana-2`).
5. Repair Calculator concept render still works.
6. GBP Posts image gen still works.
7. Customer list — customers with `homeworks_id` on their doc still
   render normally.
8. Backend logs — no `[queue-item-5c]` warning line at startup
   (dispatcher is gone).
