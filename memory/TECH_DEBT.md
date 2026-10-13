# Tech Debt — Feb-2026 Code-Review deferred items

Created **Feb-2026** as part of the Phase O4 · Offline Sync Backend Idempotency Sprint post-triage. All items below were flagged by an external code review, triaged against the codebase, and confirmed as real work — but NOT worth carving out a dedicated refactor sprint for. Each is small enough to fold into a natural change reason the next time we touch the surrounding area.

**Rule of thumb:** Do not ship any of these as standalone refactors. When a future ticket already needs to modify the target file, take the opportunity to also land the refactor below. If N months pass with no natural touch and the debt is compounding, escalate to a dedicated ticket.

For the linter-noise-suppression rationale (why we're NOT chasing the reviewer's 221 undefined-variable / 54 secret / 2,395 complexity findings), see the header comment in [`/app/backend/pyproject.toml`](/app/backend/pyproject.toml).

---

## Extraction refactors (circular-import cleanup)

### TD-F7-1 · Extract shared `<LineItemsEditor>` primitive
- **Current state:** Two editors with converging feature sets:
  - `frontend/src/pages/jobs/LineItemsSection.jsx` (job side, K2 + F7 additions — category picker, editable unit_price + custom-price hint, pricebook_writeback checkbox, row-level 4xx error surfacing).
  - `frontend/src/components/invoices/InvoiceEditModal.jsx` (invoice side, same feature set + more — expressed inline inside a larger modal).
- **Why deferred:** Feature-add now, dedupe later — the cost of divergence stays low as long as we track it. Slice K2 already shipped the job-side editor; F7 only extended it in-place. Extraction would double the effort of F7 without new capability.
- **When to ship:** When a **third consumer** lands (e.g. Estimates line-items redesign), OR when a **fourth feature** diverges (e.g. a new pricing dimension the invoice side wants but the job side doesn't). At that point extract to `frontend/src/components/lineitems/LineItemsEditor.jsx` (or similar), have both existing consumers import it, and delete the duplication.
- **Cross-refs:** The backend already extracted the writeback into `services/pricebook/writeback.py` and the category validator into `routers/income_categories.py::validate_line_item_categories`, so the two frontend editors already share both server-side hooks — only the presentation layer diverges.

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

### TD-07 · WP host sgcaptcha bot-challenge blocks Soshie autopilot publish (**operator action item**)
- **Current state:** The WordPress adapter (`services/social/wordpress_adapter.py`) succeeds up to the HTTP layer, but the target host (SiteGround) returns an sgcaptcha HTML bot-challenge with HTTP 202 instead of accepting the post. The app handles this correctly — the action row flips to `status="failed"` with the captcha response surfaced on `result.error` — but real autopilot publishes to WordPress will continue to fail until the operator resolves it host-side.
- **Priority:** P1 (blocks real WP flows in production).
- **App-side impact:** None right now. The scheduler treats the failure like any other adapter error; retries are user-driven from the Review Queue.
- **Resolution options (any one):**
    - (a) Whitelist the app-server egress IP on SiteGround's Web Application Firewall.
    - (b) Update the WP adapter to send a browser-like User-Agent + retry-on-challenge with the sgcaptcha token echoed back.
    - (c) Migrate the WP site behind a different edge that doesn't gate REST-API POSTs behind a bot-check.
- **When to ship:** Pending operator action — logged as an operator ticket, not a dev refactor. Do NOT ship option (b) app-side until the operator confirms (a) and (c) are both off the table.
- **Status:** Pending operator (Feb-2026).

### TD-08 · Admin branding upload UI (BrandLogo tenant override)
- **Current state:** The Feb-2026 UI Polish Addendum wired `BrandLogo` in the app shell to read `tenant.branding.logo_url` (with a fall-through to legacy `tenant.logo_url`) and to render `/brand/logo.png` (or `/brand/logo-icon.png` for the icon variant) as the local placeholder. The backend accepts the field via `PATCH /api/tenants/mine/brand` and `PATCH /api/tenants/business-card`, so branding is fully editable via API today.
- **Why deferred:** A dedicated admin surface for **uploading** the logo (image validation, S3/asset URL persistence, live preview) was explicitly out-of-scope for the polish sprint. The existing `TenantsAdminPage` supports a URL input as a stop-gap.
- **When to ship:** Bundle with the next admin-settings UI iteration — reuse `BrandLogo` for the live preview so the same fallback semantics apply. Also swap the placeholder PNGs in `/app/frontend/public/brand/` for the customer's real asset at that point.
- **Priority:** P2.
- **Status:** Deferred (Feb-2026 UI Polish sprint follow-up).

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

---

## P2 #4 + P2 #5 follow-ups (Feb-2026, added during P2 #5)

- **P2 #4** — `test_lead_create_quote.py::_patch_db_everywhere` omits `routers.income_categories` from its loop re-pin list; running `test_lead_create_quote.py` together with any sibling file that boots its own event loop fails one case with `RuntimeError: Task got Future attached to a different loop` at `routers/income_categories.py:92`. Each file still passes standalone. One-line fix: add `"routers.income_categories"` to the module tuple in that patcher. Priority: P3.
- **P2 #5** — SMS thread aggregation deferred. Needs cross-collection join (`marketing_deliveries` ∪ `lead_communications` outbound + `sms_inbound`) matched on `(tenant_id, phone number)` within a time window to reconstruct inbound/outbound SMS conversations in the detail modal. Priority: P2.
- **P2 #5 hardening** — Gate remote-image loads in `CommunicationDetailModal` email iframe behind a user opt-in toggle (default off). Currently the sandboxed iframe will fire tracking pixels / remote `<img>` loads when the modal opens; adding `Content-Security-Policy` meta or stripping remote-src tags server-side would close the privacy gap. Priority: P3.

## P2 #6 follow-ups (Feb-2026, added during P2 #6)

- **P2 #6 follow-up — mobile parity** — mirror the `service_category` dropdown on Mobile CustomerDetail (`e1_expo_frontend_dev`). The underlying PATCH /customers/{cid}/service-category contract is unchanged; mobile just needs the UI control. Priority: P3.
- **P2 #6 follow-up — exports/reports column** — add a `service_category` column to the admin customer CSV export at `routers/reports.py` (and any similar export shaper under `pages/reports/`). Minor flag during audit; deferred to avoid a drive-by refactor of the export machinery. Priority: P3.
- **P2 #6 operator action — run backfill** — when ready to populate the ~48 unset-and-matchable customer rows in prod, run `python3 backend/scripts/backfill_customer_service_category_from_jobs.py --commit`. Dry-run first (default). The script emits one batch audit row per invocation (`customer.service_category_backfill_run`); first-write-wins — never overwrites an already-set category. Idempotent on repeat runs. Priority: P2 (operator-gated, same posture as the P0 duplicate-user enumeration).

## P2 interrupt follow-ups (Feb-2026, added during Quick Access edit-mode UX)

- **Mobile parity — Quick Access edit-mode UX** — if/when the Quick Access rail is ported to mobile (`e1_expo_frontend_dev`), port the long-press (500 ms, >10 px cancel, pointercancel/pointerleave clear, primary-button only) → edit-mode UX alongside, including the Done button, click-outside / Escape exits, jiggle animation (± 1.5°, respect `prefers-reduced-motion`), and the ARIA live region. Web implementation lives in `frontend/src/components/nav/QuickPinsRail.jsx` as a reference. No mobile counterpart exists today — no action required until mobile adds its own rail. Priority: P3.

- **TD-09 · Downgrade pre-K75 WARN at `backend/routers/auth.py:665` to `email_sha8=%s`** — the P0 Commit-2 observability WARN still logs raw `email=%s`; the Feb-2026 login-selection patch (commit `365ad10e7`) landed on `email_sha8=%s` discipline, so the two signals now diverge. Not fixed in `365ad10e7` to keep that patch single-concern. When to ship: next natural touch of `backend/routers/auth.py` around line 665, or when PII posture across both signals needs a consolidation pass. Priority: P3.

## P2 #7 follow-ups (Feb-2026, added during Mass Messaging Card-on-file + Portal-login filters)

- **TD-10 · "Has card on file" semantics divergence across three call-sites** — `backend/routers/quotes.py:415-445` runs a strict exp-date-aware scan of `db.payment_methods`; `backend/services/auto_invoice.py:164` has a `_has_card_on_file(tenant_id, customer_id)` helper (not grepped for exp-date behavior); `backend/routers/mass_messaging.py::_resolve_audience` now reads the `customers.has_card_on_file` denorm (ignores exp-date). All three are semantically "has a card" but with divergent strictness. **When to ship:** if/when a fourth consumer lands, extract `backend/services/payments/has_card_predicate.py` with a single shared function (plus a strict vs loose mode flag), migrate all three sites. **Priority:** P3.

- **Mobile parity — Mass Messaging composer filter checkboxes** — the full composer UI is web-only today; `/app/mobile/src/components/dashboard/MassMessagingCard.tsx` is a lightweight dashboard entry card (no composer). If a mobile composer is ever built, port the Card-on-file + Portal-login checkbox pair alongside — `customers.has_card_on_file` denorm is zero-friction; `has_portal_login` uses a users-scan set-build matching `routers/quotes.py:415-445`. Web implementation lives in `frontend/src/components/mass-messaging/MassMessagingComposeDialog.jsx` + `backend/routers/mass_messaging.py` as reference. **Priority:** P3.

## P2 #8 follow-ups (Feb-2026, added during RECURRING-ALL-FAILURE-RETRY-GUARD)

- **TD-11 · Cron-failure alerting bridge (push notification surface)** — the P2 #8 halt guard mints an `audit_logs` row with `action="recurring_job.cron.batch_failure_halt"` on cross-tenant cron batch failure, but there is no push-notification bridge today (email/Slack/webhook). Ops currently discovers a halted run by querying `GET /admin/audit-log` for the action prefix. **When to ship:** if/when a general cron-failure alerting surface is built (not scoped to this ticket because it opens a new infra question — recipient routing, severity dedup, cooldown — that no single feature should own). The P2 #8 audit row would be a first-class consumer of such a bridge. Pattern-match the existing `services/notifications` dispatcher. **Priority:** P3.

## P2 #10 follow-ups (Feb-2026, added during Transactional-template editor rollout)

- **TD-16 · Transactional-template wiring sweep — 2 remaining unwired slugs** — `password_reset_email` (`routers/auth.py` reset flow) and `portal_chat_admin_notify_sms` (`services/portal_chat_sms_bridge.py:147`) still render from hardcoded strings; migrate both to `get_template_by_code(..., tenant_id)` with hardcoded fallback intact. **When to ship:** next natural touch of either file, or as a follow-up P2 #10b ticket. **Priority:** P2.

- **TD-17 · Transactional template test-send endpoint + UI button** — rate-limited `POST /marketing/templates/{tid}/test-send`, admin-facing "Send to me" button on the editor, K72 real-tenant block aware. **Priority:** P2 (medium-value admin verification UX).

- **TD-18 · Multi-locale transactional templates** — extend `marketing_templates` row with `locale: 'en' | 'es' | 'fr'` + resolver prefers tenant-locale match → en fallback. D5 locale resolution is already live. **Priority:** P3 (post-launch, demand-driven).

- **TD-19 · ~~P2 #10d automation-gate wiring sweep — 3 remaining service entry points~~** — **RESOLVED in P2 #10e (SHA `eaf4dcc6e`)** — `completion_followup_sms_enabled` (`routers/service_reports.py::_bg_send_completion_sms`, gated via `services/completion_sms_template.py::should_send_completion_followup_sms` async helper), `invoice_past_due_enabled` and `estimate_reminder_enabled` (both in `emailer.py`, inline `automation_enabled` call at top of each entry point) now all short-circuit when their tenant flag is False. Pre-send gate is the first substantive statement after the doc-type guard; no DB / deny-list / Resend / RC send work runs when disabled. Coverage: `backend/tests/test_p2_10e_service_wires.py` (6 cases, both directions of each gate). Admin UI landed in parallel at `frontend/src/pages/settings/NotificationPrefs.jsx::TenantAutomationTogglesSection` with the 4 toggle rows + "Customize templates →" deep-link. Gate location note: the user spec pointed at `services/completion_sms_template.py`; because `build_completion_sms_body` is a pure sync helper (8+ direct-import test sites, breaking that contract was out of scope), the gate shipped as an async pre-send helper on the same module, consumed at the call site in `_bg_send_completion_sms`. Net effect — the kill switch gates the send, which is what the toggle promises. **Original ticket text:** _`completion_followup_sms_enabled` (`services/completion_sms_template.py`), `invoice_past_due_enabled` + `estimate_reminder_enabled` (both in `emailer.py`) still fire regardless of their tenant flag. The schema (`TenantSettingsUpdate`), read path (`GET /tenants/mine/settings`), and the shared helper (`services/tenant_automation_gates.py::automation_enabled`) are all in place from Commit 4; this ticket is purely wire the `if not await automation_enabled(...)` one-liner at the top of each entry point._

- **TD-20 · `/app` volume headroom thin — blocks commits** — **STATUS UPDATE (P2 #10e):** Operator remediation unblocked the volume between the last session's STOP and this one — current state is **3.1GB free / 70% used** with `.git/objects` already consolidated into a single 505MB pack (zero loose objects, `git repack` is a no-op). The P2 #10e commit landed without disk pressure. **Remaining concern:** The baseline footprint (3.5GB `frontend/node_modules` + 1.4GB `mobile/node_modules` + 487MB `.git/objects` + 21MB `.git/index`) still consumes ~5.4GB on the 9.8GB volume, leaving ~3GB headroom for runtime scratch + future commits. Status is **MITIGATED, not resolved** — a dedicated `node_modules` purge discipline (or volume resize) is still the right long-term fix if the baseline resumes growing. **Original ticket text:** _9.8GB mount with `/app/frontend/node_modules` (3.5GB) + `/app/mobile/node_modules` (1.4GB) + `/app/.git/objects` loose (1019MB, 2523 objects) + `/app/.git/index` (21MB) consuming ~5.9GB baseline. During the P2 #10e attempt the volume reached 182MB free, under the operator-set 200MB stop-threshold, and `git repack` could not consolidate loose objects because it needs ~1GB scratch space to write the new pack before deleting the old. Successfully reclaimed 126MB via `git prune --expire=now` + 25MB via `__pycache__` cleanup, but the baseline growth keeps re-filling. When to ship: needs human intervention — either (a) volume resize to ≥20GB, or (b) deliberate `node_modules` purge + yarn-install cycle with the agent paused, or (c) move `.git` to a separate larger volume._ **Priority:** P2 (operational, blocks future commits).

- **TD-21 · `list_quotes` `view` Query-default-object leaks `Query` sentinel into direct-call tests** — `routers/quotes.py::list_quotes` declares `view: Optional[str] = Query(None)`; when a direct-call test (`test_fin_parity_b_list_quotes_payment_status_filter.py`) omits the `view=` kwarg, FastAPI's `Query(None)` default object is passed instead of `None`, and the handler's `(view or "").strip().lower()` at `quotes.py:347` raises `AttributeError: 'Query' object has no attribute 'strip'`. 9 pre-existing failures confirmed on parent SHA `c7a523c28` (prior to the PERF-HOTFIX flight) — NOT a regression. **Fix candidates:** (a) one-liner `view = view or None` normalizer at the top of `list_quotes` to coerce the sentinel to None (safest, zero-breakage); (b) migrate `test_fin_parity_b_*` to the FastAPI TestClient contract so Query defaults are evaluated by the framework. **Priority:** P3 (test-only; no runtime impact — real HTTP callers always get the Query-resolved `None`).

## P2 #9 follow-ups (Oct-2026, added during MOBILE-SCHEDULE-DAY-VIEW-TIMESTAMP-FILTER-BUG)

- **TD-12 · Web tenant TZ missing from `/auth/me`** — web falls back to America/Phoenix regardless of actual tenant TZ. Priority: P2 (affects start-time-only job placement near midnight for non-Phoenix tenants). Evidence: `GET /api/auth/me` returns neither `tenant_timezone` nor `tenant.timezone`; `GET /api/tenants/mine/settings` returns `America/New_York` for the preview tenant. Web reads `user?.tenant?.timezone || user?.tenant_timezone || TENANT_TZ_FALLBACK` (`CalendarSchedule.jsx` L437-440).
- **TD-13 · Possible web local-midnight-to-tenant day shift (unverified)** — `getTenantISODate(local-midnight date, tz)` may slip when browser is east of tenant TZ. Priority: P3 (needs targeted repro). Site: `CalendarSchedule.jsx` L1258 `focusISO = getTenantISODate(date, tenantTz)`.
- **TD-14 · Mobile tech-readable tenant TZ missing** — techs get 403 on tenant settings endpoint, so mobile always falls back to Phoenix. Needs backend change (`/auth/me` to include `tenant_tz`, or a tech-readable minimal settings projection). Priority: P2. Evidence: `GET /api/tenants/mine/settings` → 403 for `mike@aquaterra.com`; mobile `src/utils/tenantTime.ts` cache is only set from `app/settings/tenant.tsx`. P2 #9 `jobDayKey` uses `tenantTz()` only for the `scheduled_start` fallback (2 rows in the preview window).
- **TD-15 · Mobile UTC-date pattern elsewhere (18 call sites, 17 files)** — same `toISOString().slice(0, 10)` bug class exists in dashboard, timesheets, job/new, reports. Sweep candidate. Priority: P3 (not actively bugged in reported flows, but the fuse is lit). Note: P2 #9 removed the Schedule screen's occurrence, so 17 sites in 16 files remain (`app/(app)/index.tsx` ×2, `src/lib/offline/cache.web.ts`, `src/components/LandscapingClockWidget.tsx`, `app/timesheets.tsx`, `app/share-replay.tsx`, `app/reports/revenue-by-service.tsx`, `app/reports/forecast.tsx`, `app/os/sprints.tsx`, `app/maintenance.tsx`, `app/landscape-time-clock.tsx`, `app/job/new.tsx`, `app/job/[id].tsx`, `app/income-by-category.tsx`, `app/finance/vendor-bills.tsx`, `app/customer/[id].tsx`, `app/business-reports.tsx`).

- **TD-22 · Credit auto-apply long-tail invoice-create callsites not wired** — the Feb-2026 credit-auto-apply feature wired the 5 primary invoice-insert sites (`routers/quotes.py:3352`, `routers/invoices_mp15.py:351`, `routers/finances.py:538, 1106`, `routers/estimates.py:545`). The long-tail paths (`routers/estimator.py:784`, `routers/reports.py:700, 702`, `routers/mobile_sync.py:558, 578`, `routers/finances.py:177` — the chem-draft fallback branch) are NOT wired. Impact: a customer with an existing credit balance who gets an invoice created via one of these paths will see their credit applied on the NEXT credit-issue trigger OR on the next backfill run — not in the same request. Non-regression (prior behavior was the same). **When to ship:** either as a dedicated TD-22 sweep or when any of these callsites is next modified for an unrelated reason. **Priority:** P3.

- **TD-23 · PDF importer: operator opt-out for Phase 33 auto-create** — the Feb-2026 Carroll 31-row 422 fix (SHA pending) added paid-metadata auto-heal + structured per-row 422 but intentionally preserved Phase 33 Step B's auto-create-on-unknown-customer behavior. User's phase-3 spec implied unknown-customer rows should return a 422 `customer_not_matched` for operator review instead of silently auto-creating. Shipping that semantics change would regress `test_phase33_pdf_import_response_shape.py` and `test_phase33_*_pending.py`. **When to ship:** add an opt-in `strict_customer_match=True` flag to `_CommitOptions` (defaults False — preserves current auto-create behavior; True returns the structured 422). Requires a minor FE handshake once introduced. **Priority:** P3.
