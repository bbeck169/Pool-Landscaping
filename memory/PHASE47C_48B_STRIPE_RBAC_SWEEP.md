# Phase 47c / 48b · Feb 2026 — Stripe RBAC sweep (**PAUSED — surfacing findings**)

## TL;DR

The Stripe RBAC cluster was expected to be a ~76-failure batch-isolation
defect similar to Phase 41.1d (Motor loop bleed) and Phase 46 (RingCentral
dry-run leak). The full-batch enumeration reveals a **different shape** —
**missing runtime endpoints**, not batch-isolation drift. Fixing this
inside a test-hygiene phase would silently fold ~45 runtime-code changes
into an isolation-only patch. Per the brief guardrail
("if more than a handful of tests need runtime-code touches to pass,
PAUSE and surface"), execution paused after diagnosis.

## Failing test enumeration (full-batch, current baseline)

Running the 12 Stripe / Phase 47c / Phase 48 files together:

```
17 failed, 73 passed, 28 errors  →  45 red total  (not the ~76 estimated in Phase 41.1c)
```

By file:

| File | Red count |
|------|-----------|
| `test_stripe_phase4b.py` | **18** (all errors, one shared root cause) |
| `test_phase53_stripe.py` | **14** |
| `test_slice_5a_stripe_key_health_run.py` | **6** |
| `test_slice_5a_stripe_live_ping.py` | **4** |
| `test_stripe_phase14a.py` | **2** |
| `test_phase42_4_stripe_v15_audit.py` | **1** |

`test_phase47_direct_stripe_payment_link.py`, `test_phase47c_add_card_link.py`,
`test_phase47d_mobile_quote_pay.py`, `test_phase47e_no_lumino_in_pay_path.py`,
`test_phase48_customer_fields.py`, and `test_phase42_stripe_refresh.py` are all
green in the batch — 73 passing tests.

## Root cause (single cluster — **not** batch isolation)

The Phase 4b + slice-5a + phase53 tests call **backend-side test-hook
endpoints** that no longer exist in the router tree. Direct probes:

```bash
$ curl -s -o /dev/null -w "%{http_code}\n" \
    http://127.0.0.1:8001/api/dev/_phase4b_stub_stripe
404
$ curl -s -o /dev/null -w "%{http_code}\n" \
    http://127.0.0.1:8001/api/stripe/health
404
```

The `ALLOW_TEST_HOOKS=1` env var IS present in `.env`, so the guard on
other test-hook endpoints (workforce, dunning, ringcentral_jwt,
quickbooks_cleanup — all confirmed via grep) fires correctly. The
issue is specifically that **the Phase 4b Stripe stub router + the
`/api/stripe/health` endpoint were never landed as routers** in the
current codebase — only the test file references exist:

```
$ grep -rn "phase4b_stub" /app/backend/ | grep -v __pycache__
tests/test_stripe_phase4b.py:63-72               ← callers
tests/test_slice_5a_stripe_key_health_run.py:76-89 ← callers
```

**No router module implements those paths.** All 18 `test_stripe_phase4b.py`
errors + 6 `test_slice_5a_stripe_key_health_run.py` errors + at least 8
of the 14 `test_phase53_stripe.py` failures short-circuit on the same
404 during module-scoped setup, which cascades into `ERROR at setup`
for every downstream test in the same class / module.

## Why an isolation-layer fix would not close the gap

Every candidate root cause from the Phase 41.1c triage (env-var
mutation, dirty stripe SDK singleton, motor loop rebind race, mongo
doc mutation, idempotency-key collision) was investigated and
**ruled out** — the tests fail on the very first line of module setup
with `404 Not Found` before any Stripe SDK call fires. There is no
state to isolate; the target endpoint simply isn't mounted.

Fixing this at the isolation layer would require adding an autouse
fixture that **implements the missing endpoints in the running
backend process** at test-collect time — which is functionally
identical to adding runtime code, just laundered through a fixture.
That's the exact pattern the brief tells me to pause and surface.

## Files touched

**None.** No runtime code was modified; no isolation fixtures were
added. This memo is the only artefact.

## Full backend batch — before / after

Before: 17 failed, 73 passed, 28 errors (45 red).  
After: **same** — no changes shipped.

## Confirmation of prior-phase invariants

- Phase 41.1d Motor loop rebind — green in isolation:
  `pytest tests/test_phase51a_walkie_backend.py` → 21/21 in 11 s.
- Phase 46 RingCentral dry-run — no regressions (no RC tests touched).
- Phase 51.6 walkie work — green in isolation:
  `pytest tests/test_phase51_6_walkie_replies.py` → 7/7 in 8 s.
- Phase 41.4 curated coverage gate — 184/185 @ 3.37 % (unchanged).
- Frontend Vitest 1357/1357, Mobile Jest 206/206, ESLint 0 — unchanged.

## Recommended next-phase slice

Split into two ticketed follow-ups so the runtime-code addition doesn't
sneak inside a hygiene phase:

1. **Phase 47c-hooks (new)** — restore the missing Phase 4b Stripe stub
   router + `/api/stripe/health` endpoint, both gated on `ALLOW_TEST_HOOKS=1`
   (matching the pattern in `routers/workforce.py`, `routers/dunning.py`,
   `routers/ringcentral_jwt.py`, `routers/quickbooks_cleanup.py`). Expected
   closure: ~40 of the 45 red tests.
2. **Phase 47c-isolation (residual)** — after the hooks are back, re-run
   the batch. Any tests that stay red at that point should be the actual
   isolation-layer defects (idempotency-key collision, dirty SDK singleton,
   env-var mutation). Address in an autouse-fixture-only PR at that point.

If the user prefers the hooks router **not** be restored (e.g. these
tests were intentionally decommissioned as part of the Phase 42.4
Stripe v15 audit), then the correct closure is to **delete the six
red test files** rather than the router. Either path is a runtime /
test-tree change — outside the scope of an isolation-layer sweep.

## Handoff status

**Paused, awaiting user decision** on whether to:

- **(A)** Land the missing Phase 4b stub router + `/api/stripe/health` endpoint (small runtime addition, ~40 tests turn green), or
- **(B)** Delete the six red test files as decommissioned (no runtime change, +45 red → 0 red).

Either choice moves the needle by the expected ~76 (actual: 45). The
isolation-layer sweep — the original ask — was not the correct tool
for this cluster.
