# Phase K43 · ACH Bank Verification / Financial Connections — SHIPPED

**Feb-2026 · P1 · Backend test fixes only · No shape/contract changes**

---

## Context

K43 was paused after backend endpoints, migration, and frontend UI
(`StripeAddBankForm`, `AdminCardCapturePanel`) had been added but
`tests/test_k43_ach_verification.py` had three failing cases. This ship
addresses those failures without changing any production code, request
shapes, or DB schemas.

## Failures fixed

### 1. `test_k43_charge_ach_on_file_passes_verified_bank_through` (2 bugs)

**Bug 1a — Dup-key on `stripe_charges_pi_unique`**

The sparse-unique index at `stripe_charges.stripe_payment_intent_id`
treats an explicit `null` as "field present" for uniqueness purposes.
A prior test crash left both a `pi_TESTK43` row AND a null-PI failure
row in the collection, so:

- The happy-path insert (with `pi_TESTK43`) dup-keyed.
- The exception handler's fallback insert (with `payment_intent_id=None`)
  also dup-keyed on the leaked null-PI row.

**Fix:** purge `stripe_charges` rows tagged with this test's customer_id
+ any leaked `pi_TESTK43` row at both start-of-test AND in the
`finally` block.

**Bug 1b — Wrong return-dict key**

Test asserted `res["intent_id"] == "pi_TESTK43"` but
`services.payments.stripe_charge.charge_ach_on_file` returns
`payment_intent_id` (not `intent_id`). Simple test typo.

**Fix:** `res["intent_id"]` → `res["payment_intent_id"]`.

### 2. `test_k43_bulk_charge_skip_row_carries_customer_id` (2 bugs)

**Bug 2a — Wrong collection**

Test inserted into `_db.invoices` but the bulk-charge router reads
from `db.quotes` (with `doc_type: "invoice"` filter). Result:
router returned `skip_reason=not_found`, never reaching the
`bank_unverified` branch that the K43 contract needs.

**Fix:** insert into `_db.quotes` with `doc_type: "invoice"`.

**Bug 2b — Wrong balance fields**

`_ach_eligibility_and_pm` reads dollar-denominated `total` +
`amount_paid` fields (not `total_cents` / `amount_paid_cents`). Test
only supplied the `_cents` variants, so eligibility short-circuited
at `zero_balance` before the verification-status check.

**Fix:** seed both `total: 15.0 / amount_paid: 0.0` AND the
`_cents` variants so the test asserts against the real code path.

### 3. `test_k43_charge_ach_on_file_skips_unverified_and_emits_audit`

Was already passing; verified still green.

## Test evidence

```
$ cd /app/backend && python -m pytest tests/test_k43_ach_verification.py
collected 13 items
tests/test_k43_ach_verification.py ......s...s..                         [100%]
======================== 11 passed, 2 skipped in 0.91s =========================
```

(The 2 skipped cases are `pytest.skip("bulk-charge-ach endpoint not
mounted here")` guards for preview environments that don't mount the
router — unchanged by K43.)

## Non-goals / out of scope

- **No production code changes.** All fixes are contained to
  `backend/tests/test_k43_ach_verification.py`. The router, service,
  migration, and frontend UI added in the paused K43 iteration remain
  as-is.
- **Cross-module test-isolation bug.** Running
  `test_k43_ach_verification.py` alongside `test_stripe_indexes_bootstrap.py`
  causes the latter to fail because `test_k43`'s module-level
  `_install_async_db()` mutates `services.payments.stripe_charge.db`
  for the rest of the pytest session. **This is pre-existing** —
  the identical 6-test failure set appears with K43 test file
  reverted (verified via git stash + rerun). Out of K43 scope; will
  be tracked separately as a test-hygiene task.

## Files changed

```
 M backend/tests/test_k43_ach_verification.py
```

## Queue status

- [x] **K45** — Mobile white screen on Schedule. Shipped.
- [x] **K43** — ACH bank verification / Financial Connections. Shipped (this phase).
- [ ] **K41d** — Bulk Operations audit tile. Resuming now.
