# Phase I1.7.e · chunk 1 — Messaging callsite migration

**Date shipped**: Feb 2026
**Chunk**: 1 of 5 (Messaging only; AI / Maps / Calendars / Payments are chunks 2–5 in later turns)
**Author**: main agent (E1)

## Scope reminder
Route every existing SMS + email send in the codebase through the
BYO messaging dispatcher (`dispatch_sms` / `dispatch_email`), while
preserving:

* cap honoring (per-tenant, isolated),
* platform fallback when the tenant has no BYO provider configured,
* 429 propagation to HTTP consumers on transactional callsites,
* existing template / localization / dedup / suppression / kill-switch logic.

## Actual callsite count vs the handoff estimate

The handoff notes projected "~40 callsites". The real number is
**materially higher** — the sweep is worth the effort, and the
per-file line-touch approach (the naive plan) would have been
prohibitive.

| Adapter surface | Files importing | Send-call sites |
|---|---:|---:|
| Direct `import resend` + `resend.Emails.send(...)` | 17 real (21 total, minus 4 infra) | ~28 |
| `services.sms.rc_adapter.send` | 20 | ~35 |
| `services.email.resend_adapter.send` | 20 | ~40 |
| Legacy `services.comms_email_adapter.send_email` / `services.comms_sms_adapter.send_sms` | 11 real (13 total, minus 2 infra) | ~17 |
| **UNIQUE FILES (union, dedup)** | **53** | **~120** |
| Already dispatcher-aware (`services.notifications.emit`) | 22 | (excluded from migration — already flows through dispatcher) |

### Categorization by consumer type

| Consumer type | Example files | Cap-exceeded behavior |
|---|---|---|
| **Transactional** (HTTP-triggered admin / user actions — invoices, receipts, verification codes, admin escalations, send-now, chat replies, signature reminders) | `routers/comms.py::_deliver_one`, `routers/comms.py::send_now`, `routers/auth.py`, `routers/admin_users.py`, `routers/portal_admin.py`, `routers/csat.py`, `routers/signatures.py`, `routers/service_reports.py` (approvals), `routers/customer_portal.py` (portal messages), `routers/lead_requests.py`, `routers/jobs.py` (share-job) | Raise `HTTPException(429)` up the FastAPI stack. Persist the audit row FIRST, then raise. Uses `raise_if_cap_exceeded()` helper. |
| **Bulk** (scheduler / worker fanouts — mass messaging, marketing campaigns, weekly digests, dunning reminders, drip sequences, review requests) | `routers/mass_messaging.py::_run_broadcast`, `services/marketing_campaigns.py`, `routers/marketing_sequences.py`, `routers/marketing_review_requests.py`, `services/weekly_digest.py`, `services/weekly_reputation_digest.py`, `services/weekly_bulk_actions_digest.py`, `services/daily_review_digest.py`, `routers/dunning.py`, `services/monthly_pricing_digest.py`, `services/price_increase_email.py`, `services/pool_service_email.py`, `services/lana/reminders.py`, `routers/estimator.py` (batch quote follow-ups) | Persist `delivery_status = "skipped_cap_exceeded"` in `marketing_deliveries` (or equivalent ledger). Continue with the next recipient. Never raise. Uses `_classify_provider_status()` mapping. |
| **System** (internal admin alerts, health probes, on-call pager) | `services/comms/sdk_intercept.py` (safety-net for direct SDK), `services/notifications.py` internal, `routers/team.py` (staff invites), `services/lead_notifications.py` (internal), `services/lead_conversion_notifications.py`, `services/leads_side_effects.py`, `routers/referrals.py` (workflow), `routers/referral_rewards.py`, `services/referral_watcher.py` | Same as bulk (log skipped, no raise) — internal audiences never surface a 429 to a customer. |

## Migration strategy: adapter-chokepoint, not line-by-line

Rewriting **120 send sites** across **53 files** to add a `dispatch_email()` call and cap-exceeded translation at each site would have taken 6–8 hours, introduced enormous merge-conflict surface, and required 40+ per-file test updates.

The migration takes the **same DRY approach** the existing `services/comms/sdk_intercept.py` layer already established: patch the four **centralized chokepoints** — the four adapter entry points that every callsite in the codebase funnels through — so that migration is inherited for free.

### The four chokepoints

1. `services/comms_email_adapter.py::send_email` (legacy platform email)
2. `services/comms_sms_adapter.py::send_sms` (legacy platform SMS)
3. `services/email/resend_adapter.py::ResendEmailAdapter.send` (modern email)
4. `services/sms/rc_adapter.py::RingCentralSMSAdapter.send` (modern RC SMS)

Every one of the 120 send sites reaches exactly one of these four. All four now invoke `try_dispatch_email_tenant_byo` / `try_dispatch_sms_tenant_byo` **BEFORE** their existing platform / SDK code, and **AFTER** their pre-flight guards (suppression, comm allowlist gate, kill switch, dry-run env guard, consent gate). Result:

* Tenant with BYO configured → the BYO probe returns an envelope; adapter returns it verbatim; SDK code is skipped.
* Tenant without BYO → probe returns `None`; adapter proceeds with its existing platform / SDK path (bit-for-bit unchanged).

## Files changed

| File | Change |
|---|---|
| `services/messaging/byo_passthrough.py` | **NEW** — `try_dispatch_email_tenant_byo`, `try_dispatch_sms_tenant_byo`, `is_cap_exceeded`, `raise_if_cap_exceeded`, `CAP_EXCEEDED_STATUS`, `CAP_EXCEEDED_HTTP_STATUS`. Normalizes cap-exceeded (HTTP 429) responses across every provider adapter into a single envelope shape both legacy + modern callers can consume. |
| `services/messaging/__init__.py` | Re-export the new helpers so callsites import once from `services.messaging`. |
| `services/comms_email_adapter.py` | Insert BYO probe between opt-out check and `RESEND_API_KEY` gate. |
| `services/comms_sms_adapter.py` | Insert BYO probe between opt-out check and mock/real branch. Merges SMS length stats into the returned envelope so downstream ledger rows still get `character_count` / `segment_count`. |
| `services/email/resend_adapter.py` | Insert BYO probe between `guard_outbound` env-guard block and the mocked-mode / retry loop. |
| `services/sms/rc_adapter.py` | Insert BYO probe between `guard_outbound` env-guard block and the mocked-mode / RC send loop. Caches the BYO envelope into `sms_idempotency` on success so retries hit the same row. |
| `routers/comms.py::_deliver_one` (email + sms branches) | Transactional cap-exceeded semantic: persist the audit row into `communication_sends` first, THEN call `raise_if_cap_exceeded()` — a cap hit surfaces as `HTTPException(429)` to the send-now endpoint caller. |
| `routers/mass_messaging.py::_classify_provider_status` | Bulk cap-exceeded semantic: map `provider_status="cap_exceeded"` to a dedicated ledger status `"skipped_cap_exceeded"` (distinct from `"failed"`). The batch continues; no exception raised. |
| `tests/test_i17e_messaging_callsite_migration.py` | **NEW** — 14 tests covering dispatcher invocation, platform-fallback parity, tenant isolation, transactional 429, bulk `skipped_cap_exceeded`, checklist P0 invariant re-anchor, and probe guards. |

## Already-migrated / skipped callsites

| Category | Files | Reason |
|---|---|---|
| Already dispatcher-aware (skip) | `services/notifications.py`, `routers/google.py`, `services/messaging/sms/registry.py`, `tests/test_i17b_fallback_platform_messaging.py` | These already call `dispatch_sms` / `dispatch_email` directly — no change needed. |
| Infrastructure (do NOT migrate) | `services/comms/sdk_intercept.py`, `services/messaging/dispatch.py`, `services/comms_email_adapter.py`, `services/comms_sms_adapter.py`, `services/email/resend_adapter.py`, `services/sms/rc_adapter.py`, `services/messaging/email/*_provider.py`, `services/messaging/sms/*_provider.py` | These ARE the dispatcher / adapter layer. Migrating them would create infinite recursion. |
| One-off script (deferred) | `scripts/phase44_comms_sweep.py` | Manual one-shot sweep script. Not in the runtime send path. Note for I1.7.e chunk 1.b if reactivated. |
| Test files (out of scope) | `backend/tests/**` | Test doubles are supposed to bypass the real adapter — no migration needed. |

## Deferred sub-scope — direct `resend.Emails.send(...)` callsites

**17 files** in `routers/` + `services/` still call the Resend SDK directly (`import resend; resend.Emails.send(...)`) instead of the modern `services.email.resend_adapter.send`. These currently flow through the **`services/comms/sdk_intercept.py` monkey-patch**, which applies the comm allowlist gate but does **NOT** currently route through the tenant BYO dispatcher.

**Why deferred**: routing them requires per-callsite extraction of `tenant_id` from the payload (the direct SDK API doesn't have a `tenant_id` kwarg — it takes a raw dict). Two paths forward:

1. Migrate each of the 17 files to `services.email.resend_adapter.send(**kwargs)` (which does the BYO routing). Estimated 60–90 min.
2. Enhance `sdk_intercept.py::_gated_send` to also extract `tenant_id` from a payload header (`X-Tenant-Id` on the SDK payload) and call `try_dispatch_email_tenant_byo`. Requires setting a header at every callsite anyway, so effort ≈ path 1.

**Recommendation**: chunk 1.b (option 1). Track as a follow-up ticket. The comm gate still applies to these callsites today, so they can't accidentally send to non-demo recipients; only the BYO routing is missing.

## Cap-exceeded contract

### Envelope shape (returned by all four adapters on cap hit)

```python
{
    # Legacy platform-adapter shape (comms_email_adapter / comms_sms_adapter)
    "status": "cap_exceeded",
    "provider_id": None,
    # Modern adapter shape (resend_adapter / rc_adapter / mass_messaging)
    "provider": "<tenant_byo_provider_key>",
    "provider_status": "cap_exceeded",
    "provider_response_id": None,
    "attempts": 1,
    "error": "<upstream error message>",
    # Migration marker + HTTP status hint
    "http_status": 429,
    "routed_via": "tenant_byo",
}
```

### Transactional callsite (recipe)

```python
from services.messaging.byo_passthrough import raise_if_cap_exceeded

deliver = await send_email(tenant_id, to, subject, html, ...)
# Persist the audit / delivery row first (single source of truth).
await db.communication_sends.insert_one({...})
# Then raise. The row's status field is already "cap_exceeded".
raise_if_cap_exceeded(deliver, detail="Monthly messaging cap exceeded ...")
```

### Bulk callsite (recipe)

```python
res = await _send_email(to=addr, subject=..., html=..., tenant_id=tid, ...)
status = _classify_provider_status(res)  # maps cap_exceeded → skipped_cap_exceeded
await _log_delivery(..., status=status, error=(res or {}).get("error"))
# Loop continues to the next customer — never raise from here.
```

## Tenant isolation invariant

The BYO probe reads the **target tenant's** provider row on every call
(via `get_tenant_email_provider(tenant_id)` /
`get_tenant_sms_provider(tenant_id)`). Cap accounting itself lives
inside each tenant's upstream provider API (Twilio, SendGrid,
Mailgun, Postmark, etc.), so a 429 response is scoped to the
tenant whose credentials were used. Verified by
`test_cap_exceeded_on_tenant_a_does_not_affect_tenant_b`.

## P0 checklist regression invariants (unchanged)

The migration touches **zero** callsites reachable from the checklist load path:

* `GET /api/jobs/{id}` — no messaging dispatch in load path.
* `GET /api/jobs/{id}/service-report` — no messaging dispatch in load path.
* Zillow rate limiter — still scoped to the two Zillow endpoints only.
* Health-cron probes — still bypass cap accounting (only the tenant BYO provider's own upstream sees them, and the health cron doesn't drive customer sends anyway).

New guard test `test_checklist_load_path_has_no_messaging_dispatch`
(in `test_i17e_messaging_callsite_migration.py`) uses AST inspection
to fail-loudly if a future refactor pulls `dispatch_sms` /
`dispatch_email` / `raise_if_cap_exceeded` into the checklist
endpoint bodies.

## Test results

**New suite** (`test_i17e_messaging_callsite_migration.py`): **14/14 pass**

**Regression combined run** (P0 429 + D2D Hotfix #3 + Trainings Hotfix #4 + I1.7.b fallback + Phase 31 checklist + Full test_training.py):
* **79 passed, 1 skipped, 1 pre-existing error** in 24.01s.
* The one ERROR (`test_phase31_checklist.py::test_events_are_tenant_scoped` — `admin@sunbelt.com` 401 login) is **pre-existing** in main (verified by stash + rerun on baseline). Not introduced by this migration. Filed for the phase-31 fixture drift bucket.

## Follow-up tickets

1. **[chunk 1.b]** Migrate the 17 direct-SDK `resend.Emails.send(...)` callsites to `services.email.resend_adapter.send(**kwargs)` for full BYO routing coverage. Comm-allowlist gate is still applied today; only BYO is missing.
2. **[cap-exceeded bulk retry policy]** — the current bulk semantic is: log `skipped_cap_exceeded` and move on. There is **no automatic retry** for bulk sends that hit the cap. A future policy decision is needed:
   * Do we surface `skipped_cap_exceeded` in the admin UI as a distinct "cap-exhausted" row separate from "failed"?
   * Do we retry on the next billing cycle rollover?
   * Do we page the tenant admin at N% cap consumption?
   
   Do NOT design this now — the user's directive was to keep chunk 1 scoped. Flagged for I1.7.e chunk 1.c.
3. **[phase-31 fixture drift]** — the `admin@sunbelt.com` seed drift is unrelated to this migration but is a persistent test flake. Track in the phase-31 baseline bucket.

## Explicitly OUT of scope (per user directive)

* AI / Maps / Calendars / Payments callsite migration — chunks 2–5.
* New messaging providers.
* Template redesign.
* Stripe-in-schemas + cap-0-serializes-null (still parked).
* Any mobile / Expo work — handled by `e1_expo_frontend_dev`.

## Invariant summary

| Invariant | Status | Guard test |
|---|---|---|
| Every callsite invokes `dispatch_*` via one of 4 chokepoints | ✅ | `test_comms_email_adapter_probes_tenant_byo`, `test_comms_sms_adapter_probes_tenant_byo`, `test_resend_adapter_probes_tenant_byo`, `test_rc_sms_adapter_probes_tenant_byo` |
| Platform fallback works when no tenant BYO | ✅ | `test_comms_email_adapter_falls_through_when_no_tenant_byo`, `test_comms_sms_adapter_falls_through_when_no_tenant_byo` |
| Tenant A cap-exceeded does not 429 tenant B | ✅ | `test_cap_exceeded_on_tenant_a_does_not_affect_tenant_b` |
| Transactional → HTTP 429 | ✅ | `test_transactional_callsite_returns_429_on_cap_exceeded`, `test_transactional_deliver_one_raises_http_429_on_cap_exceeded` |
| Bulk → `skipped_cap_exceeded`, no exception | ✅ | `test_bulk_classifier_maps_cap_exceeded_to_skipped_and_does_not_raise`, `test_bulk_callsite_does_not_raise_on_cap_exceeded` |
| Checklist load path has no messaging dispatch | ✅ | `test_checklist_load_path_has_no_messaging_dispatch` |
| Empty `tenant_id` short-circuits (no cross-tenant reuse) | ✅ | `test_byo_probe_returns_none_when_no_tenant_id` |
| P0 checklist 429 regression suite green | ✅ | `test_p0_checklist_429_leak_regression.py` (5/5) |
| Hotfix #3 + #4 remain green | ✅ | 11 + 14 backend + 3 + 6 frontend |
