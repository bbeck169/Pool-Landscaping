# Tech Debt — Feb-2026 Code-Review deferred items

Created **Feb-2026** as part of the Phase O4 · Offline Sync Backend Idempotency Sprint post-triage. All items below were flagged by an external code review, triaged against the codebase, and confirmed as real work — but NOT worth carving out a dedicated refactor sprint for. Each is small enough to fold into a natural change reason the next time we touch the surrounding area.

**Rule of thumb:** Do not ship any of these as standalone refactors. When a future ticket already needs to modify the target file, take the opportunity to also land the refactor below. If N months pass with no natural touch and the debt is compounding, escalate to a dedicated ticket.

For the linter-noise-suppression rationale (why we're NOT chasing the reviewer's 221 undefined-variable / 54 secret / 2,395 complexity findings), see the header comment in [`/app/backend/pyproject.toml`](/app/backend/pyproject.toml).

---

## Extraction refactors (circular-import cleanup)

### TD-01 · Extract `services/geocoding.py` from the tenants ↔ google cycle
- **Current state:** `routers/google.py:21` imports `get_current_tenant` from `routers/tenants.py` (top-level); `routers/tenants.py:671` imports `_geocode_one` from `routers/google.py` (in-function, comment-annotated as intentional cycle-break).
- **Why deferred:** Touches auth flow. The in-function import is idiomatic FastAPI, boots clean, and the cycle isn't causing runtime issues.
- **When to ship:** Next time a natural change requires editing either file — extract `_geocode_one` into `services/geocoding.py` and delete the local import.

### TD-02 · Extract `realtime_utils.py` from the utils ↔ realtime cycle
- **Current state:** `routers/realtime.py:20` imports `now_iso`/`new_id` from `utils.py` (top-level); `utils.py:340` imports `bus` from `routers/realtime.py` (in-function, comment-annotated `# local import to avoid circular`).
- **Why deferred:** Touches every `notify_*` callsite via the `bus` publish. Moving to a dedicated module has a wide blast radius for a low-return refactor.
- **When to ship:** Next time we touch the realtime/notification event pipeline.

### TD-03 · Extract shared parser out of `services/seo_scanner.py` ↔ `services/aeo_auditor.py`
- **Current state:** `services/aeo_auditor.py:23` imports `parse_schema_org` from `services/seo_scanner.py` (top-level); `services/seo_scanner.py:630` imports `compute_aeo_signals` from `services/aeo_auditor.py` (in-function).
- **Why deferred:** Both files are stable and rarely touched. The parser is small enough that extraction is trivial when a natural touch happens.
- **When to ship:** Whenever we next add/change an SEO or AEO signal — carve `parse_schema_org` into `services/seo_common.py`.

## Complexity refactors

### TD-04 · Refactor `unlink_tech_from_customer` (`routers/admin_migrations.py:563`, cc=26)
- **Current state:** Radon rates D=26. Single admin migration endpoint that walks jobs, service reports, geofences, GPS pings, customer_tasks, and audit log entries and rewrites tech pointers.
- **Why deferred:** Load-bearing customer/tech unlink logic. Every conditional exists because a real bug once landed there. Refactoring in isolation risks regressions in the tenant admin unlink flow.
- **When to ship:** Next time we add a new `db.<collection>` that needs to be swept during unlink — take the opportunity to extract per-collection sweepers into a `_unlink_sweepers` list.

### TD-05 · Refactor `deactivate_users` (`routers/admin_migrations.py:249`, cc=17)
- **Current state:** Radon rates C=17. Bulk deactivation with per-user role/consent/session/token invalidation.
- **Why deferred:** Same file as TD-04, same reasoning. Both refactors are candidates for a coordinated cleanup when a natural touch reason surfaces.
- **When to ship:** Bundle with TD-04.

### TD-06 · Drop `recurring_templates_active_customer_idx_v1` — no consumers after Feb-2026 dashboard tile redefinition
- **Current state:** Compound index `(tenant_id, active, customer_id)` on `db.recurring_job_templates`, created by `services/migrations/recurring_templates_active_customer_idx.py` (sentinel `recurring_templates_active_customer_idx_v1`). Was designed to cover the first-pass dashboard tile's `distinct("customer_id", {tenant_id, active: True})` aggregation.
- **Why orphaned:** The Feb-2026 second-pass tile REDEFINITION moved the query off `recurring_job_templates` entirely — the dashboard now runs `db.customers.count_documents({...})` covered by the new `customers_dashboard_active_inactive_idx` (see the same-day sibling migration). The only other consumer, the cross-tenant recurring-job cron in `routers/recurring_jobs.py:641`, uses `find({"active": True})` without `tenant_id` — so it cannot leverage the compound index (MongoDB requires the prefix column to be filtered).
- **Why deferred:** Indexes should be dropped in a dedicated cleanup phase — folding an index-drop into a semantic change makes rollback complicated. Keep the index in production until we bundle it with the next cross-collection index-audit.
- **When to ship:** Next cross-collection Mongo index audit (or if the recurring-job cron ever grows a tenant-scoped variant that COULD use it, in which case reevaluate before dropping).

---

## Related — items explicitly REJECTED (do NOT resurrect these)

The Feb-2026 code review also proposed the following, all of which were rejected for concrete reasons. Documented here so a future reviewer doesn't re-open them:

- **Splitting `server.py` / `routers/jobs.py` / `routers/customers.py` on import-count alone.** Actual counts (113 / 11 / 16) are ~2–6× lower than reviewer's report and well within FastAPI norms. Mechanical split hurts cohesion.
- **Swapping `random.Random(seed)` → `secrets` in `routers/seo_agentic.py`, `seed.py`, `tests/test_phase32_cfo.py`.** Each site relies on deterministic-random for mock/demo/fixture stability; `secrets` breaks those contracts. All 3 sites carry inline `# nosec B311` markers explaining why.
- **Refactoring `emailer.send_invoice_reminder_email` (cc=14).** The function is a linear guard-chain (config→customer→email→outbound guard→render→send); cc=14 is a metric artifact of idiomatic FastAPI early-return style. Splitting it hurts readability.
- **Touching `migrations/rebrand_aquaterra_to_plofv.py::_apply_tenant_config_updates` (cc=17).** One-off migration that has already run; the file is dead code kept for audit purposes.
- **Deleting the try/except optional-dep guards in `services/suppliers/connector.py:135-141, 167-173`.** These are NOT cycle-breaking hacks — they're Playwright-optional-dep guards that keep `connector.py` importable in CI unit-test containers. Deleting them would break every backend test container that doesn't install Playwright.

---

Last updated: **Phase O4 · Feb-2026** (Offline Sync Backend Idempotency Sprint post-triage).
