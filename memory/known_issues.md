# Known Issues (rolling)

## Mobile schedule countdown pills — reverted per user request (Feb-2026)
The N/M SERVICES / N/M REPAIRS countdown pills that briefly shipped
on the mobile tech schedule (`mobile/app/(app)/schedule/calendar.tsx`,
directly below `<JobTrackerTiles>`) were removed at the user's
explicit request. Only the mobile surface was reverted — the web
admin Workstream page still renders the pills unchanged.

Preserved for potential future reuse (do NOT delete):
* `mobile/components/JobCountPill.tsx` — mobile pill component.
* `mobile/lib/jobCategory.ts` — shared classifier (still used by the
  jest unit test at `mobile/__tests__/JobCountPill.test.tsx`).
* `frontend/src/components/JobCountPill.jsx` — web pill (still mounted
  on the admin Workstream page).
* `frontend/src/lib/jobCategory.js` — shared classifier (web).

Regression guard: `mobile/__tests__/schedule-no-count-pills.test.ts`
source-inspects `calendar.tsx` to fail-loudly if a future refactor
re-imports `JobCountPill` / `computePillCounts` or re-adds the
`schedule-count-pills` container. If pills need to come back on
mobile, delete that regression test in the same commit.



## Mobile schedule map — deferred to follow-up (Feb-2026)
Web admin schedule now renders a Google-Maps stops map at the top
of the Grid view (see ``frontend/src/pages/schedule/ScheduleMap.jsx``).
Mobile tech schedule parity was scoped in the same task but is
DEFERRED because:

* Mobile's map infrastructure is ``@rnmapbox/maps@^10.1.34``, whose
  native module requires a dev-client rebuild per
  ``mobile/EXPO_GO_RUNBOOK.md`` — plain Expo Go crashes if the
  module is imported top-level. The existing ``LiveTechPinsMap.tsx``
  works around this with a dynamic ``require`` + try/catch in the
  parent; replicating that pattern for the schedule surface is a
  clean but non-trivial follow-up.
* ``react-native-maps@1.20.1`` is also in ``mobile/package.json`` but
  no existing mobile screen uses it, so adopting it would introduce
  a second, unproven map dep on the schedule surface. Not worth the
  divergence for a nice-to-have.

Resume-notes for the next agent:
1. Port ``ScheduleMap.jsx`` to ``mobile/src/components/schedule/ScheduleMap.tsx``.
2. Follow the dynamic-require + parent-side try/catch pattern from
   ``mobile/src/components/dispatch/LiveTechPinsWrapper.tsx``.
3. Data source: ``job.location_lat`` / ``job.location_lng`` on each
   job (backend projection was already added — see
   ``backend/routers/jobs.py::list_jobs`` on the ``customers`` join).
4. Colour token: reuse ``techColorMap`` the calendar builds; falls
   back to ``#94A3B8`` (slate-400) on unassigned. Same tokens as web.
5. Testing: extend ``mobile/__tests__/`` with a component test that
   mocks ``@rnmapbox/maps.PointAnnotation`` so plain Jest can run
   without the native module.



## Comms gate — production-bypass fix is preview-verified only (Feb-2026 P0)
The layer-2 comms whitelist gate at `services/comms/gate.py::is_comm_allowed`
was silently blocking real customers on production because it required
`is_demo_account=True` on every recipient (whitelist policy locked in
Feb-2026 P0 dispatch). Root cause was the code-side gate, not just the
`APP_ENV` env-guard.

Fix applied (Feb-2026, preview only):
* `services/comms/gate.py` — added early `if is_production(): return True`
  short-circuit at the top of `is_comm_allowed`. Preview / dev / staging
  keep the whitelist active (developer / QA activity still fail-safe).
* `services/comms/gate.py` — rewrote `is_comm_allowed_sync` to run on a
  worker-thread ThreadPoolExecutor so the Resend SDK monkey-patch no
  longer fails-closed when invoked from inside an already-running event
  loop. Logs the exception class + message on the fail-closed path so
  the failure surfaces loudly.
* `routers/google.py` — new admin/manager endpoint
  `GET /api/settings/integrations/health/comms` returning `{app_env,
  is_production, gate_policy, resend_api_key_configured, resend_from,
  resend_verified_domains, ringcentral_configured, rc_outbound_enabled_env,
  rc_outbound_enabled_mongo, rc_outbound_enabled_effective, rc_mode,
  sms_mock_mode, sms_will_mock, monkey_patch_installed,
  startup_banner_last_seen, notes[]}` — one-curl replacement for the
  Mongo-shell walkthrough.

Verified on preview via `pytest tests/test_comms_gate_prod_bypass.py
tests/test_health_comms_endpoint.py` — 9 passed, 1 skipped (no
technician demo account on this preview; test skips gracefully).

**Production status: requires redeploy to take effect on `app.plofv.com`.**
Preview response body currently reports `gate_policy="demo_only"` because
`APP_ENV=preview` here — that's expected. After redeploy, hit
`GET https://app.plofv.com/api/settings/integrations/health/comms` and
confirm `gate_policy="prod_bypass"` before the fix is considered live.
Owner: user to trigger redeploy from the Emergent dashboard.



## Tech-id fragmentation across `users` / `technicians` / job docs (Feb-2026)
When a user has both a row in `users` and `technicians` (or was seeded as
one and later imported as the other), the same person can carry three
different ids:
* `users._id` / `users.id`
* `technicians.id`
* `job.technician_id` (may point at either of the above depending on
  which import path created the job)

Downstream impact: client-side filters that key on a single id (e.g. the
legacy Routes tab's `x.technician_id === techId`) can silently miss the
tech's jobs. The new Routes tab wiring dodges this by delegating to
`GET /api/routes/{techId}/stops`, which does the union server-side.

Feb-2026 update — enrichment endpoint hardening:
* `GET /api/routes/{techId}/stops` now falls back to the `technicians`
  collection for `name` + `display_color_hex` when the users lookup
  misses (so passing the `technicians._id` form that `/api/technicians`
  serves still yields a populated `tech_name` / `tech_color_hex`).
* Same endpoint's job query now matches on either `scheduled_start`
  (post-optimizer datetime) OR the flat `scheduled_date` ISO string
  (legacy seeds + recurring-generator writes) — the enrichment path
  no longer silently drops non-optimized jobs.

Follow-up (owner: TBD): reconcile in a dedicated pass — one canonical
id per human, back-fill `job.technician_id` accordingly, and delete the
double-lookup once the store is consistent.

## `backend/.env.example` ships preview-posture defaults (Feb-2026)
`/app/backend/.env.example` — the tracked template — currently seeds
production deploys that follow the `cp .env.example .env` shortcut with
the following preview-only values:

* `SHOW_DEMO_LOGINS=true` (appears twice — duplicated seed sections).
* `APP_ENV=preview` (comms whitelist, Zillow guardrails, Lumino test
  gates all key off this — non-allowlisted recipients drop silently
  in preview mode).
* `STRIPE_MODE=test` (test-mode cards silently accepted).
* `CORS_ORIGINS=*` (too permissive for a customer domain).

This is the drift that caused the `app.plofv.com` demo-tiles leak on
Feb-2026. The client-side hostname gate now blocks the demo-tiles
render regardless, but every other flag above still needs an
independent audit before production.

Follow-up: create a companion `backend/.env.production.example` with
the safe-in-prod defaults inverted, and document a checklist for
promoting a preview deploy to production.


## `/api/payments/stripe/config` returns both `mode` and `stripe_mode` (Feb-2026)
FIX 4 of the Stripe reconciliation batch aligned the config key with
what newer callers expect. The endpoint now returns BOTH `mode`
(legacy) and `stripe_mode` (new canonical) for one release cycle so
existing customer-portal + admin-console builds keep working.

Deprecation: remove `mode` after the next mobile + web build is out
in prod (~Mar 2026). Search for `stripe_mode ||` in the JS/TSX
tree before dropping to catch stragglers.

## RESUME · Feb-2026 — Stripe primary / Lumino manual-only revert (Phase 2 deferred)

Phase 1 investigation complete. Current preview state is ALREADY
"Stripe primary" for every customer-facing pay path — no
auto-failover to Lumino exists. The revert is a naming / surfacing
cleanup + new manual admin button, NOT a hot rewrite.

**Zero in-flight Lumino charges** on preview (no `lumino_*`
collections, zero `quotes.payment_provider=lumino`). Safe to execute
Phase 2 without reconciliation.

### Phase 2 delta (execute in a single follow-up turn)

1. **Backend — dead-hard-code removal (~15 LOC)**
   - `services/payments/provider_factory.py:24-38` — the block that
     always returns `LuminoProvider` regardless of env. Replace with
     a real switch on `PAYMENT_PROVIDER` env (default `"stripe"` →
     raise `NotImplementedError` since only Lumino has a concrete
     `PaymentProvider` subclass today; alternatively return `None`
     and force callers to import `stripe_charge` directly).
   - Update the two live callers (`services/lumino_reconciler.py`,
     `routers/lumino_return.py`) to instantiate `LuminoProvider`
     directly since they are lumino-specific by design.

2. **Backend — new manual-charge endpoint (~40 LOC)**
   - Add `POST /api/payments/lumino/manual-charge` in a new
     `routers/lumino_manual_charge.py`.
   - Body: `{invoice_id}`. Reads invoice + customer, calls
     `LuminoProvider.create_hosted_session()` (or the current Lumino
     link generator). Returns `{payment_url, session_id}`.
   - Role gate: super_admin | admin | manager (403 else).
   - Tenant-scoped invoice lookup.
   - Audit log: `db.audit_log.insert_one({type:"manual_lumino_charge_initiated",
     actor_id:user.id, invoice_id, tenant_id, at:now_iso()})`.

3. **Frontend web — add admin button (~20 LOC)**
   - In `pages/quotes/QuoteInvoiceDetail.jsx` admin actions dropdown
     (already gated to admin roles), add "Charge via Lumino" that
     POSTs the new endpoint and opens `payment_url` in a new tab.
   - `data-testid="invoice-charge-via-lumino"`.

4. **Backend tests — new file `tests/test_payments_primary_stripe.py` (~150 LOC)**
   - Auto-charge path (POST `/invoices/{id}/request-payment-link`)
     invokes `stripe_svc.create_invoice_checkout_session` — mock
     assert. LuminoProvider NOT called.
   - Manual endpoint: super_admin / admin / manager return 200.
   - Manual endpoint: technician / customer return 403.
   - Manual endpoint: tenant isolation (foreign invoice → 404).
   - Manual endpoint: audit log row written on success.
   - Stripe failure on auto-charge → 502
     `payment_gateway_unavailable`; LuminoProvider NOT invoked as
     fallback.

5. **Vitest (~40 LOC)** — Charge-via-Lumino button visible on admin
   invoice detail; NOT rendered on customer portal invoice page.

6. **Mobile** — skip. Grep clean, no Lumino UI in the app.

### Files that DO NOT need changes (verified)
- `services/payments/provider_mode.py` — already defaults to
  `"stripe_direct"`; leave in place as a documented kill switch.
- `services/payments/stripe_charge.py` — already sole pay-path.
- `components/PaymentForm.jsx` — already Stripe-only.
- `routers/lumino_link_request.py` — despite the filename, already
  uses Stripe Checkout. RENAME is cosmetic; skip to save churn.
- Customer portal / `PortalPaymentReturn.jsx` — return-URL landing
  only, no initiation UI. Keep.
- `LuminoBackfillPage.jsx` — super-admin-only backfill tool. Keep.

### Estimated time to execute Phase 2
~1 focused turn (60-90 min of tool calls including tests + 2
screenshots).

### Screenshots owed
- Admin invoice detail with "Charge via Lumino" visible.
- Customer portal invoice page — Lumino NOT visible.
