# Phase 47c-hooks + 47c-B · Feb 2026 — Stripe test-hooks restore + decommissioned-test sweep

Follow-up to `PHASE47C_48B_STRIPE_RBAC_SWEEP.md` — the previous memo
paused after diagnosis. This one lands the two-part closure the user
locked in (A: restore hooks · B: delete residuals).

## Phase A — hooks restored

New router `backend/routers/stripe_test_hooks.py`, mounted from
`server.py` only when `ALLOW_TEST_HOOKS=1` (matching the pattern
already in use by `workforce.py`, `dunning.py`, `ringcentral_jwt.py`,
`quickbooks_cleanup.py`). The `APP_ENV=production` guard further down
in `server.py` force-clears the flag to `0` before this module ever
imports, so a stale `.env` cannot leak the hooks into prod.

| Route | Method | Behaviour |
|-------|--------|-----------|
| `/api/dev/_phase4b_stub_stripe` | POST | Installs the in-process `_FakeStripe` singleton via `services.payments.stripe_charge.set_stripe_client(...)`. Returns `{ok, installed:true, mode}`. |
| `/api/dev/_phase4b_unstub_stripe` | POST | Restores the real `stripe` SDK (`set_stripe_client(None)`). |
| `/api/dev/_phase4b_stub_account_ok` | POST | Flips `_FakeAccount._mode = "ok"` (Account.retrieve → healthy dict). |
| `/api/dev/_phase4b_stub_account_raise` | POST | Flips `_FakeAccount._mode = "raise"` (Account.retrieve → AuthenticationError with masked message). |
| `/api/dev/_phase4b_env_set` | POST | Body `{key,value}` → sets `os.environ[key]=str(value)` inside the backend process. Missing/None value clears the key. |
| `/api/stripe/health` | GET | Compact shape: `{ok:true, mode:"test"|"live", checked_at:<ISO>}`. Legacy fat shape (`configured`, `key_authenticates`, ...) intentionally NOT restored — decommissioned callers were deleted in Phase B. |

Runtime probe post-restart:

```
$ curl -s http://localhost:8001/api/stripe/health
{"ok":true,"mode":"test","checked_at":"2026-02-15T..."}
$ curl -s -X POST http://localhost:8001/api/dev/_phase4b_stub_stripe
{"ok":true,"installed":true,"mode":"ok"}
```

Both hooks return 404 when `ALLOW_TEST_HOOKS != "1"` — belt-and-braces
`_require_flag()` check runs on every request in addition to the
mount-time gate.

## Phase A delta on the 6-file scope

- **Before**: 17 failed + 28 errors = **45 red**, 24 passed
- **After hooks only**: 45 failed, 24 passed  
  (the 28 `ERROR at setup` collapses converted to individual `FAILED`
  hits because module-scoped fixtures now install cleanly — the tests
  then hit the runtime endpoints that were deleted in Phase 42.4 and
  fail at 404.)

Runtime endpoint delta is what the tests need to actually turn green,
and per the brief guardrail ("Do NOT touch runtime Stripe code beyond
the two hook endpoints") that path is closed. Phase B carries the
closure.

## Phase B — decommissioned tests deleted

Every deletion targets a test file whose only failure mode is calling
a runtime endpoint that was removed in Phase 42.4 (Stripe v15 audit)
or Phase 47/48 (Lumino retirement + Stripe surface consolidation
onto `/api/payments/stripe/*`). No surviving code path exercises the
routes these files probe.

| Deleted file | Red count closed | One-line rationale |
|--------------|------------------|--------------------|
| `tests/test_stripe_phase4b.py` | 18 | Probes `/api/payments/create-payment-intent`, `/api/payments/refund`, `/api/webhooks/stripe`, `/api/invoices/{id}/full-magic`, `/api/dev/stripe-config-check`, `/api/config/public#stripe_publishable_key` — all removed in Phase 42.4 v15 audit / Phase 47 pay-path consolidation. Superseded by `test_phase47_direct_stripe_payment_link.py` + `test_stripe_phase14a.py`. |
| `tests/test_phase53_stripe.py` | 14 | Probes `/api/stripe/checkout/session`, `/api/stripe/products`, and expects the legacy fat `/api/stripe/health` payload with `configured`/`key_authenticates` — all removed in Phase 42.4 v15 audit. Superseded by `test_phase42_4_stripe_v15_audit.py`. |
| `tests/test_slice_5a_stripe_key_health_run.py` | 6 | Probes `/api/dev/stripe-key-health-run` — the manual cron trigger was removed alongside the daily Stripe key-alert scheduler in Phase 42.4 v15 audit. No replacement — Stripe key health is now monitored by the platform's outage-detection layer. |
| `tests/test_slice_5a_stripe_live_ping.py` | 4 | Probes `/api/dev/stripe-live-ping` — decommissioned in Phase 42.4 v15 audit. The `/api/stripe/health` endpoint restored in Phase A carries the same "is Stripe reachable" signal in a simpler shape. |

**Total closed in Phase B: 42 red**

## Combined Phase A + B delta (6-file scope)

- Before: 45 red, 24 passed, 65 total
- After: **3 red, 20 passed, 23 total** (4 files removed → smaller
  total)
- **Net closure: 42 out of 45 red tests** (matches the memo's
  target of ~40).

The 3 residual failures all live in `test_stripe_phase14a.py` +
`test_phase42_4_stripe_v15_audit.py` — files kept because they test
CURRENT runtime code, not decommissioned surface:

| Residual failure | Root cause | Category |
|------------------|-----------|----------|
| `test_stripe_phase14a.py::test_router_setup_intent_admin_flow` | Test skip condition (`if not STRIPE_SECRET_KEY_TEST.startswith("sk_test_"): pytest.skip`) doesn't fire because that env var IS set — but the router uses the LIVE key from `STRIPE_SECRET_KEY_LIVE`, so real Stripe returns a real `seti_1...` id instead of the fake `seti_test_...` the assertion expects. Env-config mismatch; predates Phase 47c-hooks. |
| `test_stripe_phase14a.py::test_router_charge_admin_success_returns_intent` | Same root cause — router runs against real Stripe, PM id `pm_rt_charge` doesn't exist, 502 returned. Env-config mismatch. |
| `test_phase42_4_stripe_v15_audit.py::test_webhook_handler_survives_v15_shaped_event` | Motor loop bleed (`Future ... attached to a different loop`). Phase 41.1d isolation defect — the test creates its own event loop and calls into `handle_webhook_event` whose `db` reference is bound to the FastAPI startup loop. |

Both categories are properly addressed by the "Phase 47c-isolation
(residual)" ticket the previous memo already flagged — not by
this hooks/decommission phase.

## Full-batch verification (surviving Stripe files)

Running the 9 surviving Stripe files together (post-A+B):

```
9 files · 80 tests · 4 failed · 76 passed
```

The 4 failures are:
- 3 residuals listed above (2× phase14a + 1× phase42_4).
- `test_stripe_webhook_route_hotfix3.py::test_common_event_types_return_2xx[payment_intent.succeeded-event_object0]` —
  first parametrized instance fails when the file runs inside a batch
  after another Stripe file; passes 8/8 in isolation. Pre-existing
  in-file state-bleed defect, not a Phase 47c-hooks regression
  (deleting stripe_test_hooks and re-running reproduces the same
  cross-file failure; `test_stripe_webhook_route_hotfix3` is not in
  the memo's original 6-file baseline). Deferred to the same
  Phase 47c-isolation ticket.

## Files touched

| File | Kind | Change |
|------|------|--------|
| `backend/routers/stripe_test_hooks.py` | NEW | 6 test-hook endpoints (see table above). |
| `backend/server.py` | MOD | Conditional import + include_router of `stripe_test_hooks` under `ALLOW_TEST_HOOKS=="1"`. |
| `backend/tests/test_stripe_phase4b.py` | DELETE | Decommissioned in Phase 42.4 v15 audit (see rationale table). |
| `backend/tests/test_phase53_stripe.py` | DELETE | Decommissioned in Phase 42.4 v15 audit. |
| `backend/tests/test_slice_5a_stripe_key_health_run.py` | DELETE | Decommissioned in Phase 42.4 v15 audit. |
| `backend/tests/test_slice_5a_stripe_live_ping.py` | DELETE | Decommissioned in Phase 42.4 v15 audit. |

## Guardrails held

- Phase 42.4 `_asdict()` migration untouched.
- Existing `services.payments.stripe_charge` runtime code untouched.
- Existing `routers/stripe_router.py` (production `/api/payments/stripe/*`
  surface) untouched.
- Stripe webhook alias router (`webhook_alias_router` @ `/api/stripe/webhook`) untouched.
- The three P0/P1 hotfix code paths untouched.
- Phase 49/50/51/53/54 code untouched.
- ALLOW_TEST_HOOKS remains the sole switch that mounts the hooks —
  `APP_ENV=production` force-clears it before the router imports.

## Frontend + mobile invariants

- Vitest: **1445 / 1445** (unchanged)
- Mobile Jest: **252 / 252** (unchanged)
- `yarn lint`: **exit 0**

## Deviations from scope

None. Phase A restored the two hook families the brief called out
(`_phase4b_stub_stripe` plus its four siblings the callers actually
depended on: `_unstub_stripe`, `_stub_account_ok`, `_stub_account_raise`,
`_env_set`; and `/api/stripe/health`). Phase B deleted exactly the
four files whose ONLY failure surface was decommissioned runtime code.
The two files kept in the scope (`test_stripe_phase14a.py`,
`test_phase42_4_stripe_v15_audit.py`) test current runtime and have
residual failures that are pre-existing isolation defects, not
decommission targets.

## Handoff

Ready for the Phase 52.1 sliced brief (WebRTC walkie live-streaming
with locked product decisions).
