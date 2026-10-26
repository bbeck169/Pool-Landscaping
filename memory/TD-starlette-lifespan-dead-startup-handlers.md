# TD-starlette-lifespan-dead-startup-handlers

**Classification:** P2
**Status:** NOT STARTED — triage memo only
**Filed:** Feb 2026, surfaced during Q (`td-stripe-webhook-400-every-event`) recon

---

## Discovery

While wiring the Stripe webhook boot-check into the `lifespan()`
function for Ticket Q, I confirmed via code reading + a runtime log
sweep that `app.router.lifespan_context = lifespan` at
`backend/server.py:6666` **replaces every `@app.on_event("startup")`
and `@app.on_event("shutdown")` handler**. Under Starlette's modern
lifespan protocol, when `lifespan_context` is set the legacy event
hooks are completely bypassed and silently never fire.

This is codified by a REPO-INTERNAL guardrail test that is **CURRENTLY
FAILING** and has been silently red:

```
backend/tests/test_p21_async_startup.py::
    test_p21_source_lint_no_on_event_decorators
    FAILED — "P21 regression: found @app.on_event decorator: ..."
```

The P21 test was explicitly built to prevent exactly this bug.
Its red state means it has been treated as a pre-existing failure
and ignored.

---

## Grep output

```
$ grep -rn "@app.on_event" backend/ --include="*.py"
backend/server.py:1951:@app.on_event("startup")
```

**One** `@app.on_event` registration in production code. Every
other hit in the earlier grep lands in test files, source
comments, or docstrings referencing the pattern — not live
registrations.

---

## Per-hit impact assessment

### `backend/server.py:1951` · `_preview_isolation_boot_audit`

**Dead code.** Four distinct boot checks live inside this handler.
Impact of each one being silently dropped on every pod boot:

| # | Call | Purpose | Impact of dead-code status |
|---|---|---|---|
| 1 | `_assert_pii_registry_coverage(app)` | Preview-only hard-fail if a PII-ingress route is missing from the registry (P0 Stage 3 Commit F) | **Preview boot guard is dead.** A route added without a registry entry no longer crashes preview boot — contradicts the Stage 3 Commit F posture. On prod it's a no-op anyway (`is_production_env()` short-circuit inside the helper), so no prod safety impact. |
| 2 | `_asyncio.create_task(_preview_scrub(db))` | Fire-and-forget preview-only data scrubber (24h dedup + localhost-only Mongo guard inside `run_once`) | **Preview scrubber never spawns.** On prod it's a no-op (same `is_production_env()` guard). Preview DB can accumulate stale PII fixtures that the scrubber was supposed to clean. |
| 3 | `check_stripe_mode_consistency()` | Stripe mode/secret consistency boot log + inconsistency ERRORs | **ALREADY FIXED by Ticket Q.** Moved into `lifespan()` at `backend/server.py:6572-6591` with the TD-stripe-webhook-400-every-event explanatory comment. No action required on this one. |
| 4 | `assert_no_orphan_credit_writes()` | Preview-boot hard-fail if any writer bypasses `services.customer_balance.mutate_credit` (P0b Stage 2 S2-1 credit-write-guard) | **Preview static-scan guardrail is dead.** A new router that writes directly to `customers.credit_balance` no longer crashes preview boot. On prod it logs ERROR but doesn't fail boot anyway — so prod has no safety regression, but preview CI loses the chokepoint enforcement. |

### `perf_customers_v3` (Ticket K index work) — SAFE

Specifically checked per operator ask: `_run_perf_customers_v3_boot`
is called from `_run_boot_sequence` (`backend/server.py:4326`)
which is itself invoked INSIDE `lifespan()` at `backend/server.py:6495`
(`await _run_boot_sequence()`). **Ticket K indexes land on every
boot as intended on both preview and prod.** No remediation needed
for `perf_customers_v3`.

---

## Severity

**P2** — not P1 — because:

* `perf_customers_v3` is SAFE (critical fallback behavior intact).
* The Stripe boot-check (which operator cares most about) was
  already lifted into `lifespan()` by Ticket Q.
* The three remaining dead calls are preview-only guardrails;
  prod boot semantics are unaffected.
* The P21 guardrail test is red but has been red for a while
  without an observed prod impact.

Upgrade to **P1** if a future audit finds that `_assert_pii
_registry_coverage` was masking an actual PII-ingress gap that
has since surfaced, OR if the credit-write-guard dead state
coincides with the discovery of an orphan credit writer in a
later ticket.

---

## Proposed fix shape (DO NOT ACT — operator triage next cycle)

Three-step surgical fix, modeled after the Ticket Q posture:

1. **Lift the 3 remaining calls into `lifespan()` body** at
   `backend/server.py:6572-6591` right next to the already-lifted
   `check_stripe_mode_consistency()` call. Order:
   * `_assert_pii_registry_coverage(app)` FIRST — on preview this
     may raise and we want it to raise BEFORE the pod binds the
     listener. Match the P0 Stage 3 Commit F posture exactly.
   * `_asyncio.create_task(_preview_scrub(db))` SECOND — same
     fire-and-forget semantics.
   * `assert_no_orphan_credit_writes()` THIRD — matches the P0b
     Stage 2 S2-1 posture (raise on preview, log on prod).

2. **Delete the `@app.on_event("startup")` decorator + function**
   `_preview_isolation_boot_audit` at `backend/server.py:1951`.
   Everything inside it is dead; deleting the shell removes the
   confusion for future readers.

3. **Add the P21 guardrail green-check** to the atomic commit so
   `test_p21_source_lint_no_on_event_decorators` goes from red
   to green AT the moment of the fix. This re-arms the invariant
   enforcement so a future accidental re-add of `@app.on_event`
   fails CI immediately.

**Scope budget:** Single BE commit; ~40 line diff in `server.py`;
no new files; `test_p21_source_lint_no_on_event_decorators` flips
from red to green as the fix's regression lock. ~20 min edit→commit.

---

## Operator-facing runbook

No prod runtime action required — this is a dead-code cleanup +
preview-only guardrail restoration. On apply:

* Preview boot gains back the three guardrails (PII registry
  coverage, scrubber task, credit-write-guard).
* Prod boot is byte-for-byte identical (all three were prod no-ops
  already).
* No DB migration. No sentinel. No CLI ladder.

---

## Breadcrumbs

* Discovery: Ticket Q · `td-stripe-webhook-400-every-event` ·
  commit `471b8af4c`
* Grep timestamp: Feb-2026
* P21 guardrail test file:
  `backend/tests/test_p21_async_startup.py:347`
  (`test_p21_source_lint_no_on_event_decorators`)
* Related memos: none — standalone.
