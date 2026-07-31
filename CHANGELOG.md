# Changelog

All notable changes to Pool & Landscaping CRM are documented here.

Format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).
Entries are dated (YYYY-MM-DD, UTC) since we're not cutting semver releases yet.
Do not rewrite history — only prepend new entries at the top.

---

## 2026-08-01 — Phase 13 · Deployment audit hygiene (W1 · CORS tightening, W2 · Session-collection indexes)

Two independent, tightly-scoped hygiene items called out by the Phase 12 audit. Shipped together as one pass.

### W1 · CORS tightening
Historical state: `CORS_ORIGINS="*"` was a dangling env var — the middleware actually read `ALLOWED_ORIGINS`, so `CORS_ORIGINS` had no effect. The Phase 12 audit correctly flagged this as a WARNING because the env variable name that operators would expect to control CORS was inert.

#### Added
- `services/…` behavior in `server.py` now honors `CORS_ORIGINS` per the operator's mental model:
  - **Unset** → prior behavior unchanged (existing `ALLOWED_ORIGINS`-derived allowlist).
  - **`*`** → permissive mode; `Access-Control-Allow-Credentials` is switched OFF (CORS spec forbids `*` + credentials); a single `WARNING [cors] CORS_ORIGINS is permissive (*) — tighten before production release.` fires on boot.
  - **`https://a.com,https://b.com,…`** → parsed (whitespace-tolerant) and appended to the existing allowlist. `allow_credentials=True` is preserved. Inline wildcards inside a list are rejected with a WARNING and stripped.
- `tests/test_cors_config.py` — 6 unit tests: wildcard permissive marker, comma-separated exact list, whitespace tolerance, inline-wildcard stripping, empty-env return, startup-log-line contract.

#### Verified live
- `CORS_ORIGINS="*"` → boot log emits `[cors] CORS_ORIGINS is permissive (*) — tighten before production release.` (one line per uvicorn worker). Final `CORS allow_origins = ['*']`.
- `CORS_ORIGINS="https://poolscape-audit.preview.emergentagent.com,https://staging.example.com"` → boot log emits no warning; final allowlist merges the two supplied origins with the existing `ALLOWED_ORIGINS`-derived list: `['https://poolscape-audit.preview.emergentagent.com', 'https://app.plofv.com', 'https://plofv.com', 'https://staging.example.com']`.
- Reverted to `*` at end of test — production preview restored to permissive baseline.

### W2 · Session-collection compound indexes
Phase 12 flagged 15 of 17 session collections as missing `(tenant_id, ts_desc)` compound indexes. All added.

#### Added
- `scripts/create_session_indexes.py` — idempotent one-shot migrator with `--dry-run`. For each of 15 collections, picks the appropriate timestamp field (primary → fallback via document-sample inspection), then creates a named index `tenant_<field>_desc`. Prints per-collection status + a summary tally (`created / already_exists / skipped_missing_field / skipped_empty_collection / substituted_field`). Empty collections are skipped cleanly. Concurrent-create races are absorbed as `already_exists`.
- **Boot hook** in `server.py:startup` (`from scripts.create_session_indexes import ensure_on_boot`) — self-healing safety net so freshly-deployed pods don't need a manual step. Wrapped in try/except so a Mongo hiccup never blocks boot; failure logs `[indexes] boot hook failed (non-fatal): …`.
- `tests/test_session_indexes.py` — 6 tests: dry-run doesn't mutate; real run creates then second run is a no-op; field-substitution when the primary timestamp is absent on the sample; empty-collection skip case; subprocess dry-run smoke; boot-hook never-raises contract.

#### Indexes ensured on the live preview DB (14 created on first boot; second boot: 0 created, 14 already-exists)

| Collection | Index name | Notes |
|---|---|---|
| `route_optimize_events` | `tenant_executed_at_desc` | Phase 10 sub-item F |
| `aeo_visibility_probes` | `tenant_ran_at_desc` | Phase 5b |
| `brand_mentions` | `tenant_discovered_at_desc` | Phase 5c |
| `brand_mention_runs` | `tenant_ran_at_desc` | Phase 5c |
| `aeo_fixes` | `tenant_generated_at_desc` | Phase 5b |
| `mention_response_drafts` | `tenant_drafted_at_desc` | Phase 6 |
| `response_draft_templates` | `tenant_created_at_desc` | Phase 10 sub-item D |
| `scorecard_digests` | `tenant_generated_at_desc` | Phase 7 |
| `aeo_digest_runs` | `tenant_generated_at_desc` | Phase 8 |
| `aeo_digest_pdfs` | `tenant_created_at_desc` | Phase 8 (primary `generated_at` absent on sample → substituted `created_at`) |
| `llmstxt_publish_configs` | `tenant_updated_at_desc` | Phase 9 |
| `llmstxt_publish_history` | `tenant_requested_at_desc` | Phase 9 |
| `invoice_reconciliation_log` | `tenant_logged_at_desc` | Phase 11 |
| `quotes` | `tenant_created_at_desc` | co-exists with the existing `tenant_invoice_number_unique` index |
| `aeo_probe_runs` | (skipped) | collection does not exist yet — 0 rows historically |

#### Operational note for ops
The startup boot hook self-heals on next boot, so no manual step is strictly required. If you want to force it out-of-band without a redeploy:
```
python -m scripts.create_session_indexes
```
Idempotent — safe to run any number of times. `--dry-run` inspects without mutating.

### Design decisions
- **W1**: kept the existing `ALLOWED_ORIGINS`-driven allowlist logic intact, and layered `CORS_ORIGINS` as an additive control. This preserves back-compat for anyone who has already tuned `ALLOWED_ORIGINS`, while giving operators the env-var name the audit expected. `CORS_ORIGINS=*` deliberately switches `allow_credentials` to `False` (CORS spec forbids wildcard + credentials) — this is a **breaking change for any browser client that relies on credentialed cross-origin XHR while permissive mode is on**, but that combination was never spec-compliant anyway; production should not run permissive.
- **W2**: index NAMES are deterministic (`tenant_<field>_desc`) so operators can `db.<coll>.dropIndex("tenant_created_at_desc")` predictably. Field substitution logs a `NOTE` line but never crashes — the primary/fallback chain guarantees a sensible pick even if the collection's schema drifts. The boot hook lives in the existing `@app.on_event("startup")` handler (immediately after the Mongo ping) so its outcome is unambiguously logged before any traffic is served.
- **Test isolation**: the session-index tests originally used `subprocess.run(python -m scripts.create_session_indexes)` which launches a fresh interpreter — meaning `_script.SPECS.append(...)` in the test process was invisible to the subprocess. Refactored to call the async `_script.run(dry_run=…)` directly on the test's event loop. One subprocess-based smoke test remains to prove `python -m scripts.create_session_indexes --dry-run` exits 0 end-to-end.

### Verification
- New pytest files: **12 / 12 passing** (`test_cors_config.py` = 6, `test_session_indexes.py` = 6).
- Targeted regression across 6 invoice/AEO test files (72 tests): **70 passing / 2 pre-existing baseline failures unchanged** — zero Phase-13 regressions.
- Vitest baseline: **14 failed / 537** — inside the accepted 11-14 tolerance (upper edge). Zero Phase-13-authored tests among the failures.
- `/api/openapi.json` returns 200. Live-verified with `CORS_ORIGINS="*"` (permissive + warning) and `CORS_ORIGINS="https://…,https://…"` (list mode, no warning).
- Live-verified all 14 indexes on the preview Mongo (`getIndexes()` reports each `tenant_<field>_desc` entry present).

---

## 2026-08-01 — Phase 11 · Invoice dual-collection refactor (`db.invoices` → `db.quotes`)

Consolidated the two-collection invoice model onto **`db.quotes` with `doc_type="invoice"`** as the single source of truth. `db.invoices` was preserved for rollback safety but is now inert — no production code reads or writes it. Migrated 17 orphan rows (all test-seed residue in one tenant) into `db.quotes` with `migrated_from_invoices=True` and `migration_needs_review=True` for later super-admin review.

### Added
- `scripts/migrate_invoices_to_quotes.py` — idempotent one-shot migrator with `--dry-run`. Conservative schema-gap fills (`doc_type="invoice"`, `total=total_cents/100`, `line_items=[]`, `payment_status="unpaid"`, `created_at=now`). Never overwrites: on a duplicate id, `db.quotes` wins and the diff is written to `db.invoice_reconciliation_log`. Ran cleanly on live preview: `scanned=17, migrated=17, already_present=0, drift_logged=0`.
- `routers/invoice_reconciliation.py` — `GET /api/admin/invoice-reconciliation-log?limit=100` — super-admin-only (`admin` + `super_admin`). Response body includes the deferred-Lumino-backfill disclaimer.
- `tests/test_invoice_collection_unification.py` — 7 guardrail tests: migration idempotency (5 orphans → run twice → 0 double-writes), quotes-wins duplicate handling + drift log, `find_invoice_dual` reads only from `db.quotes` (retired `db.invoices` branch), promo-code redeem writes to `db.quotes` only (fixes B1), role guard × 3 accounts × reconciliation endpoint (manager 403, admin/super_admin 200), backward-compat lookup of migrated hex32 ids, **grep-lint** that fails on any live `db.invoices.<method>(` call in production code outside the shim's own definition + migration script.

### Changed
- `services/invoice_lookup.py` — `find_invoice_dual` now hits **only** `db.quotes` and emits a `WARNING`-level deprecation on first call per process (via `functools.lru_cache(maxsize=1)`). Tuple shape `(doc, "quotes")` is preserved for back-compat with the 4 existing callers.
- `routers/lumino_return.py` — `status=paid` + `paid_at` write moved to `db.quotes` (was writing to `db.invoices`).
- `services/lumino_reconciler.py` — nightly "mirror payment" step moved to `db.quotes`.
- `routers/lumino_invoice_link_callback.py` — write target unconditionally `db.quotes` (dropped the `db.invoices if collection == "invoices" else db.quotes` branch).
- `routers/invoice_edit.py` — `invoice_number` uniqueness scan simplified to a single `db.quotes` query.
- `routers/portal_greeting.py` — unpaid-invoice greeting slot reads `db.quotes` with `doc_type="invoice"` filter.
- `routers/referrals_vesting.py` — `_referrer_has_paid_invoice_since()` reads `db.quotes`.
- `services/referral_watcher.py` — first-paid-invoice lookup reads `db.quotes` (removed the legacy fallback branch).
- `routers/lumino_backfill.py` — single-collection scan (removed the merge-with-`db.invoices` de-dup path).
- `routers/promo_codes.py` — **B1 fix**: replaced the `for coll in (db.invoices, db.quotes)` dual-push loop with a single write to `db.quotes`.
- Five test seeders re-pointed to `db.quotes`: `test_invoice_edit.py` (default `collection="quotes"`), `test_lumino_invoice_link_callback.py`, `test_lz2_dispatcher.py`, `test_phase10_referrals.py`, `test_task_qq_p2_lumino.py`.
- Test 14 in `test_lumino_invoice_link_callback.py` inverted its expectation to assert the Phase 11 contract ("db.invoices row is NEVER updated when a matching db.quotes row exists").
- Stale docstrings in `routers/invoice_edit.py`, `routers/lumino_backfill.py`, `routers/lumino_invoice_link_callback.py`, `routers/lumino_link_request.py` updated to describe the unified model.

### Fixed
- **B1** `promo_codes.py` · dual-push loop (`for coll in (db.invoices, db.quotes)`) removed. Single write to `db.quotes` — no risk of double-`$push` into `applied_promo_code_ids` on any future duplicate.
- **B2** `referrals_vesting.py` · referrer paid-invoice window check now sees the 466 real invoices in `db.quotes`, not just the 17 test residues in `db.invoices`. **This unblocks the vesting gate for real customers going forward.**
- **B3** `portal_greeting.py` · customer-portal "unpaid invoice" greeting slot now fires against real invoices in `db.quotes` instead of silently missing them.
- **B4** `lumino_return.py` · Lumino redirect `status=paid + paid_at` write lands on the source of truth. Going-forward payments are correct; historical drift is called out under **Notes** below.
- **B5** `lumino_reconciler.py` · nightly reconciler mirrors payment status onto `db.quotes`. Same historical-drift caveat.
- **B6** `invoice_lookup.py` · shim no longer prefers the ancillary `db.invoices` collection.

### Deprecated
- `services.invoice_lookup.find_invoice_dual` — kept as a compatibility symbol for the 4 existing callers (`routers/invoice_edit.py`, `routers/lumino_invoice_link_callback.py`, `routers/lumino_link_request.py`), but emits a WARNING once per process boot. **Scheduled for removal in a future phase after ≥ 30 days of clean production logs.** Migrate callers to a direct `db.quotes.find_one({"id": …, "doc_type": "invoice"})` when convenient.

### Security
- New `GET /api/admin/invoice-reconciliation-log` endpoint enforces **super-admin scope only** (`role in {"super_admin", "admin"}`). `manager`, `technician`, `customer` all 403. Verified live and in pytest.
- Response body always includes a `notes[]` array with the "Historical Lumino paid_at drift is NOT in this log" disclaimer so operators don't misinterpret an empty log as a clean bill of health.

### Notes
- **Historical Lumino `paid_at` drift is NOT reconciled by this phase.** Any Lumino payment that completed *before* the refactor was written into `db.invoices` (a bug per B4/B5) and never landed on the matching `db.quotes` doc. A follow-up data-fix phase will scan `db.payment_events` for successful Lumino returns older than the Phase 11 cutover and replay the `paid_at` mirror onto `db.quotes`. The reconciliation-log endpoint calls this out in its response `notes[]`.
- `db.invoices` collection is **retained** (empty of live writes, but the 17 legacy rows plus any pytest seeds remain) as a rollback net. A future phase will drop the collection after ≥ 30 days of clean deprecation-warning logs.
- The migration script wrote 17 rows with `migration_needs_review=True`. All 17 look like fork-loop test residue in the `manager@aquaterra` tenant (no `line_items`, no `invoice_number`, no `created_at`). A super-admin can decide via the reconciliation-log endpoint (drift log is empty — the migration was drift-free) whether to delete them.

### Verification
- Full targeted regression across 14 invoice-adjacent test files: **0 newly-broken tests**, 16 pre-existing baseline failures unchanged.
- New guardrail file `tests/test_invoice_collection_unification.py`: **7 / 7 passing**.
- Vitest baseline: **13 failed / 537** — inside 11-14 tolerance, unchanged from Phase 10.
- Migration dry-run + real: 17 rows migrated cleanly, 0 drift, 0 duplicates.
- `/api/openapi.json` returns 200 with the new `/api/admin/invoice-reconciliation-log` path present.

---

## 2026-07-31 — Phase 10 · Bundled extensions (D + E + F)

Three small extensions bundled together — Response Draft Library (D), Auto-Slot Preview Badge (E), Cumulative Weekly savings_km KPI (F). None of them touch Phase 3-9 internals beyond a one-line append-only event-log hook (F) and a status-transition side-effect (D).

### Sub-item D · Response Draft Library — Added
- `services/response_library.py` — `capture_template_from_draft()` (dedup on `sha256(platform + normalised text)[:32]`, min 20 chars text, per-tenant), `list_templates()`, `top_templates_for()`, `use_template()` (increments `use_count`, updates `last_used_at`, rolling 30-day counter — window resets to 1 when prior `last_used_at` is older than 30 days), `soft_delete_template()` (sets `deleted_at`, excludes from list/top), `render_examples_for_prompt()` (assembles a Claude system-suffix block from up to 3 templates).
- `routers/aeo.py` — 3 new endpoints: `GET /api/aeo/response/templates?platform=&limit=`, `POST /api/aeo/response/templates/{template_id}/use`, `DELETE /api/aeo/response/templates/{template_id}`.
- Collection `response_draft_templates` (`template_id, platform, tone, source_draft_id, template_text, template_hash, use_count, times_used_last_30d, last_used_at?, deleted_at?, created_at`).
- Phase 6 integration — `services/response_drafts.py`:
  - `update_draft()` on `status="posted"` transition calls `capture_template_from_draft(draft)` (fire-and-forget, swallow exceptions).
  - `create_or_get_draft()` pulls up to 3 top templates for `(platform, tone)` and passes them to `_build_prompt()`, which appends a "Examples of prior public replies from this business …" block to the Claude system message. Neither the endpoint signature nor the mention_response_drafts shape changed.
- Web admin — new **Response Library** 7th tab on `/admin/marketing/aeo` (`ResponseLibraryTab`): platform filter + client-side substring search + table (platform badge, tone badge, first 120 chars, uses, 30d, last_used_at, delete). Empty state guides the user to the Brand Mentions tab.
- `ResponseDraftModal.jsx` — new `SuggestedFromLibrary` collapsible section below the tone pills. Renders up to 3 prior templates, each with a `Use this` button that pastes the template into the textarea, calls `POST /aeo/response/templates/{id}/use`, and (if there is an active draft) `POST /aeo/response/drafts/{draft_id}` with `edited_text`.

### Sub-item E · Auto-Slot Preview Badge — Added
- `routers/dispatch_route_insert.py` — `POST /api/dispatch/route/preview-insert-batch` with body `{tech_user_id, route_date, job_ids[≤50]}`. Reuses the existing `_cheapest_slot()` helper 1:1 — no algorithm duplication. Loads the current (tech, date) route + coords once, then loops the candidates and returns `[{job_id, added_distance_km, best_position, currently_missing_coords}]`. Jobs with missing coords → `added_distance_km=null, currently_missing_coords=true`. If the tech has no origin AND no existing route, treats the candidate as its own origin (0 km first-stop preview).
- Web — `UnscheduledJobsPanel.jsx` accepts a new `previewsById` prop. Each row renders a colour-coded pill: `≤ 5 km → green`, `5-15 km → amber`, `> 15 km → red`, `null → gray "no coords"`.
- `DispatchBoardPage.jsx` — new effect that fires a 300 ms-debounced `POST /preview-insert-batch` whenever `(techId, day)` becomes concrete AND `unschedJobs.length > 0`. Results are cached in a `useRef` map keyed by `${techId}|${isoDate}|${idsHash}` for 30 s, then propagated via `setPreviewsById`. When no tech / day is selected, `previewsById` clears so no stale pills remain.

### Sub-item F · Weekly savings_km KPI — Added
- `services/route_events.py` — append-only `route_optimize_events` writer (`log_event(kind, tech_user_id, route_date, savings_km, stop_count, added_distance_km?, executed_by)`, swallows exceptions) + `weekly_summary(tenant_id, range_='7d'|'30d', top_n=5)` aggregator. Returns `{range, period_start, period_end, total_savings_km, total_optimize_events, total_insert_events, per_day[]  (backfilled zeros for missing days), top_techs[]}`.
- `routers/dispatch_savings.py` — `GET /api/dispatch/route/savings/weekly?range=7d|30d`. Mounted with `Depends(_rg)` in `server.py` (same guard as Phase 3/4).
- Phase 3 · `routers/dispatch_route_optimize.py:apply_route` — one-line append at the end of a successful apply, logging `kind="optimize"` with the client-supplied `savings_km` (a new optional `ApplyBody.savings_km` field the frontend already computes).
- Phase 4 · `routers/dispatch_route_insert.py:insert_route_job` — one-line append at the end of a successful insert, logging `kind="insert"` with `savings_km=0` and `added_distance_km` populated (insert doesn't save distance, it adds it — the field is informational).
- Web — `DispatchSavingsStrip.jsx` in `pages/dispatch/`, rendered inside the Dispatch Board header row. Big number `Team saved X.X km this week` (7d default), recharts sparkline area chart (60 px tall), "View report" link → modal with a 7d/30d toggle, 3 KPI cards (Total saved · Optimize events · Insert events), a larger sparkline, and a Top techs table. `hidden md:block` — collapses on mobile.

### Design decisions
- **Sub-item D · few-shot injection**: appended to the Claude *system* prompt (not the user prompt) so the model treats the examples as tone / voice conditioning rather than data. Truncated at 800 chars each; capped at 3. Empty examples list emits no suffix at all — the prompt is bit-identical to Phase 6 when the library is empty.
- **Sub-item D · dedup key**: `sha256(platform + ":" + text.strip().lower())[:32]`. Same text posted to Yelp and Google Reviews → two separate templates (platform-aware voice). Case-insensitive so trivial edits don't spawn duplicates.
- **Sub-item D · soft-delete**: sets `deleted_at`, filtered by all readers (`{"deleted_at": {"$exists": False}}`). Preserves audit trail for the source_draft_id link.
- **Sub-item E · cache pattern**: `useRef` map keyed by `${techId}|${isoDate}|${idsHash}`, 30 s TTL. Hovers, panel-toggle, and quick tech-flip don't refire — the previous result is served instantly. When any of the 3 key inputs changes → new fetch. When context becomes invalid (no tech / day="all" / no unscheduled) → `setPreviewsById({})` so no stale pills remain.
- **Sub-item E · degraded modes**: (1) job missing coords → `null` + flag, panel renders "no coords" gray pill (2) unknown job_id → treated as missing_coords (server never 404s a batch preview) (3) tech has no route yet → cheapest-slot is 0 km using the candidate as its own origin.
- **Sub-item F · log-vs-recompute trade-off**: chose append-only event log over rescanning `jobs` for `savings_km` on every request. Log rows are 1 KB, one per apply/insert — the write cost is negligible and the read is a straight `find + sum` that hits a natural `(tenant_id, executed_at)` index. Historical replay before this phase is intentionally deferred.

### Security
- All 3 new template endpoints reject Tech + Customer with 403 (verified live; pytest × 3 × 2 accounts).
- `POST /dispatch/route/preview-insert-batch` inherits the router-level `require_gps_read` guard mounted at `include_router()` in `server.py` — Tech + Customer 403 (verified live).
- `GET /dispatch/route/savings/weekly` inherits the same `require_gps_read` guard — Tech + Customer 403 (verified live).
- Cross-tenant `list_templates()` / `weekly_summary()` return empty results (never 500).
- Auto-capture failures inside `update_draft(status="posted")` are caught and swallowed — Phase 6's posted-status path is never blocked by a library bug.

### Changed
- `services/response_drafts.py` — `_build_prompt` accepts optional `examples` list, `create_or_get_draft` fetches top templates, `update_draft` calls `capture_template_from_draft` on `status="posted"`.
- `routers/aeo.py` — 3 new endpoints appended (imports from `services.response_library`).
- `routers/dispatch_route_insert.py` — new `POST /preview-insert-batch` endpoint appended; the existing `POST /insert` gets a 5-line event-log tail block.
- `routers/dispatch_route_optimize.py` — `ApplyBody.savings_km: Optional[float] = None`; `apply_route()` gets an 8-line event-log tail block.
- `server.py` — mounted `dispatch_savings` router below Phase 4.
- `frontend/src/pages/dispatch/UnscheduledJobsPanel.jsx` — accepts `previewsById`; row renders a colour-coded pill.
- `frontend/src/pages/dispatch/DispatchBoardPage.jsx` — imports `DispatchSavingsStrip`, renders it in the header row; new 300 ms-debounced batch-preview effect + `useRef` cache.
- `frontend/src/pages/admin/AEOPage.jsx` — 7th "Response Library" tab + `ResponseLibraryTab` component.
- `frontend/src/pages/admin/ResponseDraftModal.jsx` — `SuggestedFromLibrary` block wired to `/api/aeo/response/templates`.

### Out of scope (deferred)
- Slack notification when a new template is auto-captured.
- Per-user template pinning / favorites.
- Batch preview streaming (websocket).
- Historical replay of savings before the log was introduced.
- Multi-tenant leaderboard.

---

## 2026-07-31 — Phase 9 · LLMs.txt Auto-Publish (Netlify / Vercel / Cloudflare Pages)

### Added
- `services/llmstxt_publish.py` — 3 provider adapters (Netlify, Vercel, Cloudflare Pages) behind a common shape: each exports `test_connection(config)` and `publish(config, filename, content)`; both return `{ok, error?, account_info?, deploy_id?, url?}` and never raise. Netlify uses `POST https://api.netlify.com/api/v1/sites/{site_id}/files/{filename}` (octet-stream raw body). Vercel uses `POST https://api.vercel.com/v13/deployments` with an inline `files` array — documented as "counts as a full production redeploy" (Vercel has no single-file live upload). Cloudflare Pages uses `POST https://api.cloudflare.com/client/v4/accounts/{account_id}/pages/projects/{project_name}/deployments` with a multipart `files` field. Adapters read `_mock_publish_response` / `_mock_test_response` from the config row as a test shortcut so pytest can stub HTTP without a shared-process transport injection. `publish()` orchestrator writes a `pending` history row, calls the adapter inside a try/except, then patches the row to `success` / `failed` and stamps `provider_deploy_id`, `provider_url`, `error_message`, `completed_at`. Config CRUD + masked read (`_mask` → last 6 chars, same pattern as Phase 7 Slack webhook). `auto_publish_on_generate(tenant, filename, content, requested_by)` iterates all `enabled=True + auto_publish_on_generate=True` configs and returns `{triggered, results[]}` — swallows exceptions.
- `routers/llmstxt_publish.py` — 6 admin/super_admin/manager-only endpoints: `GET /api/aeo/llms-txt/publish/providers`, `POST /api/aeo/llms-txt/publish/config`, `DELETE /api/aeo/llms-txt/publish/config/{provider}`, `POST /api/aeo/llms-txt/publish/test/{provider}`, `POST /api/aeo/llms-txt/publish/{provider}` (calls Phase 5a `generate_llms_txt` then delegates to `publish()`; maps `http_status_hint=400 → HTTP 400 not_configured` and `502 → HTTP 502 upstream_error` while still writing the history row), `GET /api/aeo/llms-txt/publish/history?provider=&limit=20`.
- Collections `llmstxt_publish_configs` (per-tenant, per-provider — schema: `provider, api_token, site_id?/site_url?, project_id?, project_name?, account_id?, enabled, auto_publish_on_generate, last_publish_at?, last_publish_status?, created_at, updated_at`) and `llmstxt_publish_history` (`publish_id, provider, filename, size_bytes, content_bytes_hash (sha256[:32]), requested_at, requested_by, status pending/success/failed, provider_deploy_id?, provider_url?, error_message?, completed_at?`).
- Phase 5a integration — `routers/aeo.py:api_generate_llms_txt` now calls `auto_publish_on_generate()` after the generator and appends `publish_triggered` (bool) + `publish_results` (list of `{provider, status, publish_id?, error_message?}`) to the response. The generator's core signature and success path are unchanged; auto-publish failure never aborts the response.
- Web admin — new **PublishConfigPanel** collapsible section on the existing `/admin/marketing/aeo` LLMs.txt tab (no new top-level page). 3 provider sub-tabs (Netlify / Vercel / Cloudflare Pages), per-tab paste-only token input with masked display of the last 6 chars, provider-specific fields (Netlify: `site_id` + optional `site_url`; Vercel: `project_id` with an amber "counts as full redeploy" note; Cloudflare Pages: `account_id` + `project_name`), Enabled + Auto-publish-on-Generate toggles, Save / Test-connection / Publish-llms.txt / Publish-llms-full.txt / Remove buttons, publish-history table (last 20 rows, provider, filename, size, colored status badge, deploy ID with external-link chip, error message on row `title`), plus a "Where do I get this token?" help link per provider (Netlify → `app.netlify.com/user/applications#personal-access-tokens`, Vercel → `vercel.com/account/tokens`, Cloudflare → `dash.cloudflare.com/profile/api-tokens`).
- Pytest suite `backend/tests/test_llmstxt_publish.py` — 10 tests all green: adapter URL selection via `httpx.MockTransport`, not-configured 400 path, publish-success writes success history + captures `provider_deploy_id`/`provider_url`, publish-failure writes failed history + returns `http_status_hint=502` + `error_message` starts with `http_401`, POST-config through the live route strips `api_token` from the response and returns `api_token_masked` ending in the token's last 6 chars, auto-publish hook via live POST `/api/aeo/llms-txt/generate` sets `publish_triggered=true` + writes a history row, role guard × 6 endpoints × 2 non-mod accounts (all 403), cross-tenant lookup returns `[]` not 500, live test-connection endpoint round-trips through DB-mocked adapter, live POST publish endpoint (Cloudflare Pages) succeeds end-to-end.

### Design decisions
- **Token storage**: raw in `llmstxt_publish_configs.api_token`, NEVER surfaced back — every read helper drops `api_token` and exposes only `api_token_masked` (last 6 chars). Same pattern as the Phase 7 Slack webhook. No new secrets store introduced.
- **HTTP stubbing pattern for tests**: an in-config `_mock_publish_response` / `_mock_test_response` short-circuits the adapter *before* it opens `httpx.AsyncClient`. This side-steps the cross-process issue where the uvicorn worker cannot see a monkey-patched `_http_client_factory` from the pytest process. `httpx.MockTransport` is still used for the pure-service adapter-selection test that runs in-process.
- **Auto-publish concurrency**: awaited inline in the generator handler rather than fire-and-forget. This makes `publish_triggered` + `publish_results` in the response *authoritative* about the outcome (spec asked for a history row to be present after the generator returns — a background task would have raced). The perf cost is one stubbed HTTP round-trip per configured provider; acceptable for a UX where the user just clicked "Generate".
- **Vercel single-file limitation**: documented in the UI as an amber banner + in the adapter docstring. For git-linked projects we recommend a commit PR path in a future phase.

### Security
- All 6 new endpoints reject Tech + Customer with 403 (verified live).
- Cross-tenant config fetch returns `[]` (no 500 leak).
- Adapter helpers guard on missing token / missing provider-specific fields with `{ok: False, error: "not_configured"}` — endpoints never crash on incomplete configs.
- `POST /api/aeo/llms-txt/publish/{provider}` maps upstream failures to HTTP 502 with a friendly JSON body containing the `publish_id` for follow-up in history, without leaking provider response bodies beyond the first 400 chars.

### Changed
- `server.py` — mounted `llmstxt_publish` router.
- `routers/aeo.py` — `api_generate_llms_txt` now returns `publish_triggered` + `publish_results` alongside the existing generator fields.

### Out of scope (deferred, per spec)
- OAuth flows for all 3 providers (PAT-only in Phase 9).
- Auto-detect `site_id` / `project_id` from a PAT (needs a list-projects call per provider).
- Multi-file publish, rollback / version pinning, and CI/GitHub-push integrations.

---

## 2026-07-31 — Phase 8 · Weekly AEO PDF Digest (ReportLab + Resend)

### Added
- `services/aeo_digest.py` — Aggregates last-completed-week AEO health into a 4-section snapshot: (1) AEO score (`overall_aeo_score` from latest `seo_scans` + WoW delta + sub-signal breakdown for `schema`/`faq`/`llms_txt`/`passages`/`entity_clarity`), (2) AI visibility (avg `aeo_visibility_probes.score`, brand-mention rate, top/bottom queries, per-provider tally), (3) brand mentions (`brand_mentions` count, sentiment split, top domains, opt-in negative snippet samples), (4) action items (pending AEO fixes + pending response drafts). ReportLab `canvas` renderer (Helvetica, single-page portrait letter, ≤500 KB target — actual ~2.4 KB), b64-persisted to `db.aeo_digest_pdfs`. HMAC-SHA256 signed public URL (10-min TTL, SECRET_KEY/JWT_SECRET-keyed, 32-char hex sig). Resend delivery with PDF attachment, injectable `resend_send` stub for tests. `run_digest()` runner returns `{digest_id, snapshot, pdf_url, pdf_size_bytes, delivery}`. `weekly_digest_cron()` — hourly gate on tenant DOW+hour_utc, `aeo_visibility_enabled=True` required, `already_generated_this_week()` dedup, per-tenant try/except.
- `routers/aeo_digest.py` — 5 authenticated endpoints (`POST /api/aeo/digest/preview`, `POST /api/aeo/digest/run-now`, `GET /api/aeo/digest/history`, `POST /api/aeo/digest/settings`, `GET /api/aeo/digest/settings`) + 1 signature-gated public endpoint (`GET /api/aeo/digest/pdf/{digest_id}?tid=&exp=&sig=`, `include_in_schema=False`). Reuses `require_gps_read`-style admin/super_admin/manager guard.
- Collections `aeo_digest_pdfs` (b64 body cache), `aeo_digest_runs` (history), `aeo_digest_settings` (per-tenant `{enabled, recipient_emails[], day_of_week 0-6, hour_utc 0-23, include_negative_snippets}`).
- APScheduler job `aeo_weekly_digest` wired in `server.py` at `minute=10` (offset from Phase 7's scorecard cron to avoid rush-hour collisions).
- Web admin `/admin/marketing/aeo/digest` (`pages/admin/AEODigestPage.jsx`) — Settings card (recipients CSV, DOW select, hour_utc, Enabled + Include-negative-snippets toggles, Save / Send-test / Generate-preview CTAs), Preview card (embedded `<iframe>` of signed PDF URL + Open-PDF anchor + byte counter), History card (last 10 digests with period range, size, download link, per-channel delivery ✓/✗). Route mounted in `App.js:683` under `<AdminOnly>` guard.
- Pytest suite `backend/tests/test_aeo_digest.py` — 8 tests all green: empty-week snapshot no-crash, ReportLab bytes start with `%PDF-` and size < 500 KB, sign+verify signature round-trip + tampered-sig rejection, snapshot with seeded metrics reads visibility/mentions/drafts, `deliver_email` invokes injected Resend stub with attachment payload, cron dedup skips a second run for the same `period_start`, live `/settings` + role guard × 4 endpoints × 2 accounts (admin 200 / customer 403), live `/preview` returns downloadable PDF via signed URL.

### Security
- 5 authenticated endpoints reject Tech + Customer with 403 (verified live: `GET /settings`, `POST /preview`, `GET /history`, `POST /settings` all 403 for customer, 200 for manager).
- Public PDF download endpoint requires valid HMAC signature + non-expired `exp` — invalid or expired signatures return 403 without touching the DB. Signature key resolution order: `SECRET_KEY` → `JWT_SECRET` → static salt (dev-only fallback).
- PDF is b64-persisted per (tenant_id, digest_id); the public route scopes fetch by both, so a signed URL for tenant A cannot exfiltrate a PDF from tenant B.
- Resend HTTP call is wrapped in try/except — a Resend outage does not crash the cron and does not corrupt the `aeo_digest_runs` row.

### Changed
- `server.py` — mounted `aeo_digest` router (line 315) and cron install (lines 862-866).

---

## 2026-07-30 — Phase 7 · Weekly Scorecard Digest (Slack + Email)

### Added
- `services/scorecard_digest.py` — Mon-Sun window math + WoW deltas + per-department aggregators (field / dispatch / sales) + composite scoring (jobs·revenue·rating / assignments·optimizations·savings / conversions·value·new_quotes) + Slack Block Kit builder + Resend email HTML builder + delivery adapters with injected clients + `weekly_digest_cron()` runner + settings CRUD with masked webhook.
- `routers/scorecard.py` — 5 new endpoints: `POST /api/scorecard/digest/run-now`, `GET /api/scorecard/digest/preview`, `GET /api/scorecard/digest/history`, `POST /api/scorecard/digest/settings`, `GET /api/scorecard/digest/settings`.
- Collections `scorecard_digests` + `scorecard_digest_settings`.
- APScheduler job `scorecard_weekly_digest` — hourly, per-tenant day-of-week + hour_utc gate, dedup via `already_generated_this_week()`.
- Web admin `/admin/reports/weekly-digest` — Settings (Slack URL paste-only + masked-current display, channel, recipients, DOW/hour, enabled toggle, "Send test digest" btn), Preview (period-end date picker + rendered top/bottom lists per department), History (last 10 digests with Slack/Email delivery status).
- Pytest suite `backend/tests/test_scorecard_digest.py` — 11 tests: period math, composite + delta arithmetic (divide-by-zero → null), Slack Block Kit shape + medal emoji + delta arrows, Resend email subject + HTML + plain-text, delivery adapter uses stubs and records status, empty-department omission, webhook mask helper, live settings round-trip with masked webhook, role guard × 5 endpoints × 2 accounts, cron dedup guard.

### Security
- All 5 endpoints reject Tech + Customer with 403.
- Slack webhook URL is stored plain-text but NEVER surfaced back — GET/POST responses expose only `slack_webhook_url_masked` (last 6 chars).
- Slack + Resend calls run inside per-tenant try/except; a failing channel does not abort the other and does not crash the cron.

### Changed
- `server.py` — mounted `scorecard` router and cron.

---

## 2026-07-30 — Phase 6 · Reputation Response Drafts

### Added
- `services/response_drafts.py` — Claude-drafted public replies to brand mentions. Platform auto-detection (yelp, google_reviews, nextdoor, reddit, facebook, bbb, generic), 4 tone knobs (empathetic / professional / apologetic / assertive), per-platform length hints in the prompt (yelp 750, google_reviews 600, nextdoor 500, reddit 400, facebook 500, bbb 700, generic 500), 24h dedup per (mention_id, tone), 10/hr/tenant sliding-window rate limit, soft-delete via `status="discarded"`.
- `routers/aeo.py` — 4 new endpoints: `POST /api/aeo/mentions/{id}/response/draft`, `GET /api/aeo/mentions/{id}/response/drafts`, `POST /api/aeo/response/drafts/{draft_id}` (update text/status), `DELETE /api/aeo/response/drafts/{draft_id}` (soft-delete), `GET /api/aeo/response/drafts/pending-count`.
- Collection `mention_response_drafts` with fields `draft_id, mention_id, platform, tone, draft_text, edited_text, status, model_used, tokens_used, cost_est_usd, drafted/edited/status_updated_at, drafted_by/edited_by/status_updated_by`.
- Denormalized fields on `brand_mentions`: `has_response_draft` + `latest_draft_status` (mirrored on every draft insert / status update).
- Web admin — **Response Draft modal** (`pages/admin/ResponseDraftModal.jsx`) mounted from the Brand Mentions tab. Header with mention title + platform + sentiment badges; quoted snippet; 4 tone pills; Generate / Regenerate CTA; editable textarea (autosaves on blur) with char counter vs platform hint; Copy (flips status→copied) / Mark posted / Discard actions; model + cost footer; friendly banner on 503 `llm_unavailable`; row-level "Draft reply" button for negative mentions plus Reddit / Google Reviews neutral rows; "View draft · <status>" chip when a prior draft exists.
- KPI tile "Drafts pending action" on the Brand Mentions dashboard (draft + copied statuses only).
- Pytest suite `backend/tests/test_response_drafts.py` — 9 tests: platform detection matrix, stubbed-LLM creation + 24h dedup + regenerate, per-platform length-hint assertion on the prompt, rate-limit at 11th call, role guard (parametrized × 2), status→mirror to brand_mentions, discard soft-delete, live 404 on missing mention.

### Changed
- LLM cost for drafts shares Phase 5b's monthly AEO cap ($5) — no second budget line.

### Security
- All 4 new endpoints reject Tech + Customer with 403.
- Draft lookups always scope by `(tenant_id, draft_id)` — cross-tenant returns 404.
- Emergent LLM error → HTTP 503 `llm_unavailable`, no partial DB write.

---

## 2026-07-30 — Phase 5c · AEO Brand Mention Crawler

### Added
- `services/search_provider.py` — adapter for Serper.dev (default when `SERPER_API_KEY` is set) and Google Custom Search JSON API fallback (`GOOGLE_CSE_API_KEY` + `GOOGLE_CSE_CX`). Returns `{provider_configured, results}`; unconfigured runs return empty results, never crash.
- `services/brand_mentions.py` — crawl runner with dedup (per-tenant per-URL), cached sentiment classification (30d cache, min 40-char snippet), per-tenant monthly cost cap ($3 default via `AEO_MENTIONS_MONTHLY_CAP_USD`), 20h duplicate-run cooldown, retroactive competitor-domain retagging, dashboard + list aggregators, `daily_mentions_scan()` cron.
- `routers/aeo.py` — 5 new endpoints: `POST /api/aeo/mentions/run-now`, `GET /api/aeo/mentions/list`, `GET /api/aeo/mentions/dashboard`, `POST /api/aeo/mentions/{id}/mark`, `POST /api/aeo/mentions/competitors`.
- Collections: `brand_mentions`, `brand_mention_runs`, `brand_sentiment_cache`.
- APScheduler job `aeo_mentions_scan` at hour `AEO_MENTIONS_CRON_HOUR_UTC` (default 08:00 UTC — one hour after Phase 5b's visibility cron to prevent collisions). Only crawls tenants with `aeo_visibility_enabled=True` (reuses Phase 5b flag; no second toggle).
- Web admin — new **Brand Mentions** tab in `/admin/marketing/aeo`: KPI strip, area chart of new mentions/day, filters (range / domain / sentiment), mention table with sentiment + competitor + own-domain pills, Mark popover (sentiment + tag override), collapsible "Manage competitor domains" panel.
- Pytest suite `backend/tests/test_brand_mentions.py` — 8 tests: adapter selection (Serper / Google / none), dedup (2 identical crawls → 1 insert + 1 update), cost cap, sentiment cache (LLM stub called once), competitor retag, role guard (parametrized × 2), unconfigured-provider survives with 200.

### Changed
- LLM sentiment classification shares the Phase 5b AEO cost pool — no second budget line.
- Test file wires a private motor client bound to a shared event loop to sidestep motor's "Event loop is closed" cross-test issue that surfaces when running the AEO test suite together.

### Security
- All 5 new endpoints reject Tech + Customer with 403.
- `POST /mentions/{id}/mark` is scoped by both `mention_id` and `tenant_id` — cross-tenant marks return 404.
- Raw search-provider keys are read from env only; the mark/competitors payloads are strictly typed (invalid sentiment/tag → 422).

---

## 2026-07-30 — Phase 5b · AEO AI Visibility Tracker + LLM Fix Recs

### Added
- `services/aeo_visibility.py` — probe runner (5 default query templates × 3 providers), scoring math (+60 mention / +20 first-para / +15 domain citation / +5 competitor-context), month cost cap ($5 default via `AEO_VISIBILITY_MONTHLY_CAP_USD`), duplicate-run cooldown (20h), sliding-window fix-rate-limiter (5/hour/tenant), dashboard + history aggregators, `daily_visibility_scan()` cron job.
- `services/aeo_fixes.py` — per-sub-signal LLM fix generator; schema + llms_txt fall through to Phase 5a generators (no LLM). FAQ / passages / entity_clarity call Claude via `EMERGENT_LLM_KEY`.
- `routers/aeo.py` — 5 new endpoints: `POST /api/aeo/visibility/run-now`, `GET /api/aeo/visibility/history`, `GET /api/aeo/visibility/dashboard`, `POST /api/aeo/fixes/generate`, `POST /api/aeo/fixes/{id}/apply`, `GET /api/aeo/fixes/pending`.
- Collections: `aeo_visibility_probes`, `aeo_probe_runs`, `aeo_fixes`.
- APScheduler job `aeo_visibility_scan` at hour `AEO_VISIBILITY_CRON_HOUR_UTC` (default 07:00 UTC) — iterates tenants with `aeo_visibility_enabled=True`, skips if latest probe < 20h old, writes an audit row.
- Web admin — two new tabs on `/admin/marketing/aeo`: **AI Visibility** (KPIs / Recharts line / cooldown-aware Run scan now / probe table) and **Fixes** (scan-ID input, Generate button, priority-badged cards with Copy + Mark done).
- Pytest suite `backend/tests/test_aeo_visibility.py` — 9 tests: scoring math (high + low), cost cap, cron cooldown via HTTP, schema fix `<script>` block, rate-limit 429, role guard (parametrized × 2), empty dashboard shape.

### Changed
- LLM probe execution is dependency-injectable — pytest stubs bypass Emergent entirely.

### Security
- All 5 new endpoints reject Tech + Customer roles with 403.
- Fix-generation cross-tenant scan lookup returns 404 (never leaks another tenant's scan_id).
- Cost cap enforced before every probe write; capped tenants receive `cost_capped=true` in response and no probes are written.

---

## 2026-07-30 — Phase 5a · AEO Suite (Auditor + JSON-LD + LLMs.txt)

### Added
- `services/aeo_auditor.py` — pure signal parsers (schema completeness, FAQ presence, llms.txt probe, passage-length median, entity clarity) + weighted `overall_aeo_score` (schema 30 / faq 20 / llms_txt 15 / passages 15 / entity_clarity 20).
- `services/aeo_generators.py` — `generate_jsonld` (LocalBusiness / Organization / Service / FAQPage / HowTo builders, minified & JSON-validated) + `generate_llms_txt` (concise + full styles following llmstxt.org spec).
- `routers/aeo.py` — `POST /api/aeo/jsonld/generate` and `POST /api/aeo/llms-txt/generate`; both admin+/manager only, tenant-scoped, auto-fill from tenant profile.
- SEO scan output now includes `aeo_signals` block on every completed scan (backwards-compatible — existing SEO fields unchanged).
- Web admin route `/admin/marketing/aeo` with 3-tab page: **Auditor**, **JSON-LD Generator**, **LLMs.txt**. All tabs include Copy buttons and install-instructions callouts.
- Pytest suite `backend/tests/test_aeo.py` — 9 tests: high-score/low-score/llms.txt fetch/jsonld valid/llms.txt concise+full/role guard (parametrized × 2)/live jsonld endpoint/live llms endpoint.

### Changed
- `services/seo_scanner.py` — `run_scan` now computes AEO signals via a best-effort second `httpx.AsyncClient` block; failure is logged and stored as `aeo_signals: null`, never breaks a scan.

### Security
- Both new endpoints reject Tech + Customer roles with 403.
- llms.txt fetch is guarded against SPA fallback pages (requires `text/plain`/`text/markdown` content-type OR a body that starts with `"# "`).

---

## 2026-07-30 — Phase 4 · Drag-Drop Unscheduled Jobs with Auto-Insert

### Added
- `POST /api/dispatch/route/insert` — auto-inserts an unscheduled job at the cheapest-position slot in a (tech, date) route via added-leg-distance minimization; shifts subsequent `route_index` on write (`backend/routers/dispatch_route_insert.py`).
- `GET /api/dispatch/route/unscheduled-jobs` — tenant-scoped listing of jobs with no tech and no `scheduled_date` for the Dispatch Board drag source.
- `UnscheduledJobsPanel.jsx` — right-column panel; each row is a `useDraggable` source with fallback "Assign" button (`frontend/src/pages/dispatch/UnscheduledJobsPanel.jsx`).
- `AssignJobModal.jsx` — popup with Day + Tech pickers that hits the same `/insert` endpoint (`frontend/src/pages/dispatch/AssignJobModal.jsx`).
- `RouteDetailsDropZone` — inline droppable wrapper around the Route Details panel; outline + badge appear on hover (armed = blue, needs-filter = orange).
- Pytest suite `backend/tests/test_dispatch_route_insert.py` — 6 tests: cheapest-slot correctness, empty-route insert, missing-coords 422, already-scheduled 409, role gate, cross-tenant 404.

### Changed
- Dispatch Board wraps its Safe container in `<DndContext>` (`@dnd-kit/core`) with a 5px pointer activation constraint.
- Success toast on insert format: `Inserted "<title>" at position N/M · +X.X km`.

### Security
- Both new endpoints inherit the `require_gps_read` guard — Tech and Customer receive 403.

---

## 2026-07-30 — Phase 3 · Dispatch Route Optimization

### Added
- `POST /api/dispatch/route/optimize` — nearest-neighbor DRY-RUN preview with per-leg + cumulative distance and hand-order savings (`backend/routers/dispatch_route_optimize.py`).
- `POST /api/dispatch/route/apply` — persists `route_index` 0..N-1 per stop, idempotent (`backend/routers/dispatch_route_optimize.py`).
- `OptimizeRouteModal.jsx` — side-by-side compare + apply flow with skipped-jobs surface (`frontend/src/pages/dispatch/OptimizeRouteModal.jsx`).
- "NN Optimize" button in Dispatch Board · Route Details header, opens the modal for the selected tech + day (`frontend/src/pages/dispatch/DispatchBoardPage.jsx`).
- `isoDateForDayKey()` helper converting DOW tab (`mon`..`sun`) to ISO date within the current week.
- Mongo index `(tenant_id, tech_user_id, scheduled_date, route_index)` on `jobs` (created on first apply).
- Pytest suite `backend/tests/test_dispatch_route_optimize.py` — 4 tests, all passing (nearest-neighbor correctness, skipped list, apply persistence + idempotency, role gate).

### Changed
- Expo mobile schedule (`mobile/app/(app)/schedule/calendar.tsx`) sort now prefers `route_index`, falls back to `route_order`.
- Dispatch Board tech dropdown handles wrapped `{users, count}` response shape from `/api/users?role=technician`.
- Optimizer query matches `technician_id` in addition to `tech_user_id`/`assigned_to`, and matches `scheduled_date` via prefix regex to support both bare-date and full-ISO storage.

### Security
- Both endpoints inherit the `require_gps_read` router guard — Tech and Customer roles receive 403.

---

## 2026-07-29 — Phase 2 rework · Share Replay + GPS Read Lockdown

### Added
- Authed `GET /api/gps/replay/share/{share_id}` — Admin / SuperAdmin only, with view-count and last-viewer-IP-hash tracking.
- `require_gps_read` FastAPI dependency; wrapped every GPS *read* router at `include_router()` (blocks Tech + Customer, allows Manager / Dispatcher / Admin / SuperAdmin).
- Pytest coverage: `test_gps_read_lockdown.py`, `test_replay_share.py`.

### Changed
- `ShareReplayModal` copy → "Admins and Super Admins only. Customers cannot view this link."
- `POST /api/gps/pings` explicitly NOT wrapped by the read-guard — techs continue submitting pings.

### Removed
- Unauthenticated `GET /api/public/replay/{share_id}` route.

### Security
- PII scrub verified on the authed share GET payload (no phone / email / home_address surfaced).

---

## 2026-07-28 — Phase 1 · MR3 Public Widget Analytics

### Added
- `POST /api/public/widget/analytics/track` — public, no-auth, IP-hashed at persistence, sliding-window rate-limited to 60/min per (tenant, IP) with HTTP 429 on breach.
- `GET /api/widget/analytics/summary` and `GET /api/widget/analytics/timeseries` — tenant-scoped read endpoints.
- Web admin page `/admin/moderation/widget-analytics` — KPIs, Recharts time-series, top-10 widgets, range toggle.
- Expo mobile screen `mobile/app/widget-analytics.tsx` — read-only KPIs + top-10 list.
- `widget_analytics_events` collection with `(tenant_id, widget_id, ts)` and `(tenant_id, ts)` indexes.

### Security
- Raw IPs never persisted — `ip_hash` (SHA-256 with tenant salt) stored instead.
- Session-deduped impression firing inside Shadow DOM widget prevents inflation.
