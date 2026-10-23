# TD-stripe-test-fixture-refresh — Phase 0 recon

**Date:** 2026-02
**Scope:** read-only recon of the four BE pytest failures that surfaced during the TD-portal-add-card-disable-stripe-link Phase 2 ship (`dbf0ab8e5`). Each failure was independently reproduced via `git stash` of that Phase 2 diff — confirmed PRE-EXISTING, unrelated to the Link-disable work.
**Hard rules honoured:** no code changes, no deploy, no testing subagent. Static pytest + source read only.

---

## 1. Legitimacy

Four named BE tests, all under `backend/tests/`, all reproducible on the current preview pod without any user interaction. No V15/V16 markers (the failing test files are tracked in git, not dropped-on-disk artefacts). Classification: **plausible legitimate test-debt cleanup ticket**.

---

## 2. Per-file verdict

### 2.1 `backend/tests/test_phase47_direct_stripe_payment_link.py::test_create_invoice_checkout_session_happy_path`

**Classification: (a) assertion drift.** No real bug.

Observed failure:
```
assert out == {
    "payment_url": "https://checkout.stripe.com/c/pay/cs_test_phase47_abc",
    "checkout_session_id": "cs_test_phase47_abc",
    "amount_cents": 12345,
    "currency": "usd",
    "mode": "test",
}
AssertionError:
  Left contains 1 more item:
  {'save_for_future_billing': False}
```

Root cause: the handler `services.payments.stripe_charge.create_invoice_checkout_session` now returns a 6th top-level key `save_for_future_billing: bool`, added by the save-on-first-payment ticket (visible as `WEB-save_for_future_billing` branches throughout `stripe_charge.py`). The test's expected-dict literal was never updated.

File location: `backend/tests/test_phase47_direct_stripe_payment_link.py:69-75`.

**LOC fix:** 1 LOC — add `"save_for_future_billing": False,` to the expected dict literal.

---

### 2.2 `backend/tests/test_checkout_preflight.py::test_checkout_preflight_returns_ok_true_when_stripe_configured`

**Classification: (a) assertion drift.** No real bug.

Observed failure:
```
assert body["app_env"] in ("production", "preview", "staging", "test")
AssertionError: assert 'development' in ('production', 'preview', 'staging', 'test')
```

Root cause: the preview pod's `backend/.env` has `APP_ENV=development` (confirmed by `TD-invoice-pay-now-stripe-unreachable` recon Section 3). The `/api/settings/integrations/health/checkout-preflight` endpoint echoes `APP_ENV` directly. The test's allowed-value set was authored under the assumption that preview would be labelled `"preview"` — a labelling convention that doesn't match reality.

File location: `backend/tests/test_checkout_preflight.py:81`.

**LOC fix:** 1 LOC — add `"development"` to the allowed set (or widen to accept any non-empty string if the operator prefers).

---

### 2.3 `backend/tests/test_stripe_save_on_first_payment.py::test_webhook_save_flag_attaches_pm_as_default`

**Classification: (b/d) test-shim drift.** No real bug.

Observed failure:
```
assert len(stripe_shim["calls"]["attach"]) == 1
assert 0 == 1
...
WARNING  stripe_charge:stripe_charge.py:2572 [phase47] save-on-first-payment failed for
  invoice=TEST_inv_... pi=pi_TEST_...:
  stripe_shim.<locals>._fake_attach() got an unexpected keyword argument 'created_from_invoice_id'
```

Root cause: the production handler now calls `attach_payment_method(..., created_from_invoice_id=iid, ...)` as part of the save-on-first-payment audit trail. The test's monkeypatched shim at `test_stripe_save_on_first_payment.py:105` was authored before the audit kwarg was added:

```python
async def _fake_attach(*, tenant_id, customer_id, payment_method_id, set_default=False):
    ...
```

The shim rejects the new kwarg with `TypeError`, which the handler's broad `except Exception` catches and logs as a warning — leaving `calls["attach"]` empty and the assertion count at `0`.

Secondary signal worth flagging: the handler's `except Exception` SWALLOWS the TypeError silently (only a warning log, no raise). In a real production path this is desirable (we don't want a Stripe transient failure to break the webhook ACK), but it means a test-shim signature drift NEVER surfaces as a type error — only as a mysteriously-empty call list. **Potential test-infra enhancement** (out of scope for this ticket): a shim variant that re-raises on kwarg drift during test runs.

File location: `backend/tests/test_stripe_save_on_first_payment.py:105-110`.

**LOC fix:** 1-3 LOC — either:
- Add `**_kw` catch-all to `_fake_attach` signature (1 LOC, cheapest, forward-compatible),
- OR add explicit `created_from_invoice_id=None` kwarg (2 LOC, more intention-revealing).

Recommended: `**_kw` catch-all so future handler kwarg additions don't re-trigger this failure. Add a comment anchoring the shim contract to the production `attach_payment_method` signature.

---

### 2.4 `backend/tests/test_request_payment_link_error_mapping.py::test_happy_path_returns_payment_url`

**Classification: (b) missing fixture.** No real bug.

Observed failure:
```python
r = requests.get(f"{API}/quotes?doc_type=invoice&limit=1", ...)
items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
assert items, "no invoices present to test against"
AssertionError: no invoices present to test against
```

Root cause: the test logs in as `super@aquaterra.com` and expects at least one `doc_type=invoice` row in `db.quotes` under that tenant. Preview DB currently has zero invoices for aquaterra. The test does NOT seed one — it assumes a pre-existing fixture that no longer exists (fixture drift, probably due to a prior tenant-reset or an aquaterra tenant teardown that the test suite doesn't own).

Noteworthy: the test at line 91-94 ALREADY has a `pytest.skip` bail-out for the "invoice happened to be already paid" case, so a skip bail-out for "no invoices seeded" is idiomatic within the same file.

File location: `backend/tests/test_request_payment_link_error_mapping.py:70-95`.

**LOC fix options:**
- **(cheapest, ~2 LOC)** Replace `assert items, "..."` with `if not items: pytest.skip("no invoices seeded under aquaterra tenant")`. Matches the existing skip pattern on line 94.
- **(stronger, ~15-20 LOC)** Seed a minimal invoice at test setup (`POST /quotes` with `doc_type=invoice`) and tear it down on teardown. Gives the test real happy-path coverage; costs more LOC + a conftest fixture.

Recommended: the cheapest skip-bail path first, with a `# TODO`-style comment pointing at a future `TD-stripe-test-fixtures-seeded-invoices` ticket if operator wants real happy-path coverage.

---

## 3. Shared root cause / grouping

| Test | Class | Grouping |
|---|---|---|
| 2.1 phase47 happy_path | assertion drift (new handler response key) | **Group A — handler-response-drift** |
| 2.2 checkout_preflight app_env | assertion drift (narrow allowed-set) | **Group B — env-label-drift** |
| 2.3 save-on-first-payment attach | shim kwarg drift (new handler kwarg) | **Group A — handler-response-drift** (same underlying pattern as 2.1 — handler contract grew, test literal didn't) |
| 2.4 happy_path_returns_payment_url | missing fixture (tenant has no invoices) | **Group C — fixture-missing** |

**No test catches a real bug.** All four failures are stale-test artefacts.

---

## 4. Phase 2 LOC estimate

| Test | LOC | Risk | Notes |
|---|---|---|---|
| 2.1 phase47 happy_path | **1** | zero | expected-dict literal update |
| 2.2 checkout_preflight app_env | **1** | zero | allowed-set widening |
| 2.3 save-on-first-payment attach | **1-3** | zero (shim-only) | `**_kw` on `_fake_attach` |
| 2.4 happy_path_returns_payment_url | **2** | zero | add `pytest.skip` bail-out |
| **Total** | **~5-7 LOC** | zero | 1 single-concern commit touching 4 test files |

**Recommended Phase 2 shape:** single atomic commit `td-stripe-test-fixture-refresh · BE · test fixture + assertion refresh` touching exactly the 4 test files above, no handler changes. Edit window < 3 min, TD-61 chain-safe.

**No new handler code is required.** No new indices, no new migrations, no new env vars.

---

## 5. Real-bug flag

**None of the 4 failures catches a real production bug.** Confirmed by:
- Each failure's assertion / fixture mismatch is traceable to a known-prior handler enhancement (2.1 + 2.3) or an environmental label (2.2) or missing seed data (2.4).
- The production Stripe handler path (`create_invoice_checkout_session` + the webhook save-on-first-payment path + the `/checkout-preflight` endpoint) is otherwise exercised by the 23 passing sibling tests in these same files + the newly-added `test_td_portal_add_card_disable_stripe_link.py` suite (4/4 pass).
- The TD-invoice-pay-now-stripe-unreachable production bug is a config-drift concern on prod env, **not** a code bug — so even if these 4 tests passed, they would not have caught the prod issue.

**Secondary observation (NOT a bug, but worth logging):** the save-on-first-payment handler's catch-all `except Exception` at `stripe_charge.py:2572` silently swallows ALL post-Stripe-call errors (not just Stripe outages). This is intentional for production webhook ACK safety but hides real bugs from tests. The fix is in-test (don't rely on the handler to raise on shim drift); not a production bug.

---

## 6. Operator decisions needed before Phase 2

- **D1.** Approve the 4-file assertion/fixture refresh in a single atomic commit? Recommended Y.
- **D2.** For test 2.4, prefer the cheap `pytest.skip` bail-out (recommended) or a full-seed fixture (open a follow-up `TD-stripe-test-fixtures-seeded-invoices` ticket)?
- **D3.** For test 2.3, prefer `**_kw` forward-compat on `_fake_attach` (recommended) or explicit `created_from_invoice_id=None` kwarg (more intention-revealing)?
- **D4.** For test 2.2, prefer narrowing to `("production", "preview", "staging", "test", "development")` (recommended) or dropping the check entirely (looser but less informative)?
- **D5.** Should the save-on-first-payment handler's catch-all `except Exception` grow a `# TODO: narrow` comment, or stay as-is per webhook-ACK-safety design intent? Operator preference; recommend stay-as-is + comment.

---

## 7. Hard stops honoured

- No code changes to any `backend/` production file.
- No deploy, no testing subagent.
- No scope creep into the TD-invoice-pay-now-stripe-unreachable config-drift ticket (which touches the same `stripe_charge.py` file but addresses a DIFFERENT concern).
- V15 Occurrences #6/#7, GitHub-ownership attestation, fleet-tracking role-expansion, offline-bundle Lanes B/C/D/E, 476 pytest failures — all remain in their pre-existing holds.
