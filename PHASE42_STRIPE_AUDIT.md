# Phase 42.1 · Stripe Compat Audit (Feb 2026)

**Status:** READ-ONLY audit. No code has been modified.
**Next step:** operator ack, then Phase 42.2 (env verification) + 42.3 (SDK bump + fixes).

---

## 1. Current wiring inventory

### SDK version + api_version

| Item | Value | Location |
| --- | --- | --- |
| SDK pin | `stripe>=13.0.0,<15.0.0` | `backend/requirements.txt` |
| `stripe.api_version` set | **NEVER** — SDK uses whichever version the Stripe dashboard has set for the account | (no source) |
| `stripe.api_key` set | Lazy, per-call via `_init_api_key()` from `_select_secret_key()` | `backend/services/payments/stripe_charge.py:109` |

### Env vars consumed

| Env var | Purpose | Fallback |
| --- | --- | --- |
| `STRIPE_MODE` | `"live"` or `"test"` — controls key selection | `"test"` |
| `STRIPE_SECRET_KEY_LIVE` | Live secret key | falls back to `STRIPE_API_KEY` then hardcoded `sk_test_emergent` |
| `STRIPE_SECRET_KEY_TEST` | Test secret key | falls back to `STRIPE_API_KEY` then hardcoded `sk_test_emergent` |
| `STRIPE_API_KEY` | Platform-injected sandbox key | ← last-resort before hardcode |
| `STRIPE_WEBHOOK_SECRET_LIVE` | Live webhook signing secret | falls back to `STRIPE_WEBHOOK_SECRET` |
| `STRIPE_WEBHOOK_SECRET_TEST` | Test webhook signing secret | falls back to `STRIPE_WEBHOOK_SECRET` |
| `STRIPE_PUBLISHABLE_KEY_{LIVE,TEST}` | Frontend publishable key returned by `GET /stripe/config` | logs warning if missing |

### Production Stripe SDK calls (5 sites)

| Method | File · line | Purpose |
| --- | --- | --- |
| `stripe.Customer.create` | `stripe_charge.py:144` | Provision provider customer on first setup-intent |
| `stripe.SetupIntent.create` | `stripe_charge.py:161` | Card-on-file save flow |
| `stripe.PaymentMethod.attach` | `stripe_charge.py:210` | Belt-and-suspenders in case client-side `stripe.confirmSetup` didn't attach |
| `stripe.PaymentMethod.retrieve` | `stripe_charge.py:222` | Enrich local mirror row after attach |
| `stripe.PaymentMethod.detach` | `stripe_charge.py:310` | Delete-card flow |
| `stripe.PaymentIntent.create` | `stripe_charge.py:390` | Off-session charge with `confirm=True` + idempotency key |
| `stripe.Webhook.construct_event` | `stripe_charge.py:494` | Signature-verified webhook parsing |

### Webhook event types handled (4)

| Event | Behavior |
| --- | --- |
| `payment_method.attached` | Idempotent mirror insert into `payment_methods` |
| `payment_method.detached` | Delete mirror row |
| `payment_intent.succeeded` | Upsert `stripe_charges` row `status=succeeded` |
| `payment_intent.payment_failed` | Upsert `stripe_charges` row `status=failed` + error message |

### Router surface (`backend/routers/stripe_router.py`)

- `GET  /stripe/config` — returns publishable key + mode.
- `POST /stripe/setup-intent` — creates SetupIntent.
- `POST /stripe/attach` — attaches PM to customer (client-side backup).
- `GET  /stripe/payment-methods/{customer_id}` — local mirror listing.
- `DELETE /stripe/payment-methods/{payment_method_id}` — detach + delete mirror.
- `POST /stripe/charge` — off-session PI create.
- `POST /stripe/webhook` — signature-verified.

Idempotency keys are used correctly on `PaymentIntent.create` (`idempotency_key=idempotency_key or f"charge:{charge_row_id}"`). `SetupIntent.create` does NOT pass one — retryable but at low blast radius (a duplicate SI is a nuisance, not a double-charge).

---

## 2. Stripe SDK & API version deltas since the pinned version

**Current stable (Feb 2026):** `stripe-python@15.3.0` — pins API version `2026-03-25.dahlia`. Current default API version on Stripe dashboards is `2026-06-24.dahlia`.

**Our pin:** `stripe>=13.0.0,<15.0.0`. The `<15` upper bound was already set intentionally — someone was aware of the v15 breaking changes and chose not to cross it. Good hygiene, bad currency.

### v15 breaking changes (from the official migration guide)

| # | Change | Our exposure |
| - | --- | --- |
| A | **`StripeObject` no longer inherits from `dict`.** `.get()`, `.items()`, `.update()`, `.setdefault()` on Stripe response objects all raise `AttributeError`. | **HIGH** — our production code uses `.get()` on Stripe responses in ≥6 places (`intent.get("status")`, `intent.get("id")`, and every `data.get(...)` inside `handle_webhook_event`). Every single one breaks on v15. |
| B | `decimal_string` response fields now typed `decimal.Decimal`, not `str`. | **LOW** — we only touch `amount` fields, which are `int` cents. No decimal-typed fields hit. |
| C | Webhook parsing errors if the wrong helper is used (`Webhook.construct_from` vs `Webhook.construct_event`). | **LOW** — we use `construct_event` correctly. |
| D | Some method arg names normalized. | **LOW** — spot-check of our 5 call sites shows current argument shapes still supported. |

### API version deltas (`2024-04-10` default → `2026-03-25.dahlia` if we pin v15)

| # | Change | Our exposure |
| - | --- | --- |
| E | `payment_intent.payment_failed` webhook — `last_payment_error.payment_method.card.brand` shape stable but nested response object now typed. | **LOW** — we only read `last_payment_error.message`; deeply-nested reads are read-only and defensive. |
| F | New required `automatic_payment_methods` object semantics for PaymentIntent in newer API versions. When `payment_method` is passed explicitly (our case), no change. | **LOW** — we always pass `payment_method` explicitly for the off-session charge flow. |
| G | `setup_intent.usage` defaults may shift. We don't set `usage` — Stripe defaults to `off_session`. | **LOW** — off-session is what we want. |
| H | Stripe accounts on old `api_version` will silently return old response shapes even with a new SDK. | **HIGH** — because we don't pin `stripe.api_version`, the response shape depends on whoever last touched the account dashboard. Non-deterministic. |

### The `sk_test_emergent` fallback

`stripe_charge.py:97` falls back to a hardcoded string `"sk_test_emergent"` when no env var resolves.

- Impact: production silently proceeds with an invalid key; requests fail at Stripe with `Invalid API key`, not at startup.
- Preferred: fail-fast at startup (or on first use) if no real key resolves. Log a clear operator-facing error.

---

## 3. Triage — recommended actions

| # | Item | Risk | Effort | Recommendation | Blocks bump? |
| - | --- | --- | --- | --- | --- |
| **A** | `.get()` on Stripe response objects (~6 sites) | **H** | Medium (~20 LOC + tests) | Rewrite as `getattr(obj, "field", None)` OR gate all reads through `obj.to_dict()` first. Wrap in a small helper `_asdict(resp)` for readability. | **YES** — must fix before crossing to v15 |
| **B** | `decimal_string` typing | L | 0 LOC | No exposure — spot-verified. | No |
| **C** | Webhook parsing helper | L | 0 LOC | Already using `construct_event`. | No |
| **D** | Method arg renames | L | 0 LOC | Spot-checked, no renames touch our 5 call sites. | No |
| **E** | Webhook error-shape reads | L | 0 LOC | Defensive `.get()` chains already handle missing fields; convert to attr-access same time as A. | Coupled with A |
| **F** | Automatic PM semantics | L | 0 LOC | We always pass `payment_method` explicitly. | No |
| **G** | `setup_intent.usage` | L | 0 LOC | Stripe default is fine for our flow. | No |
| **H** | `api_version` not pinned | **H** | 1 LOC | Add `_stripe.api_version = "2026-03-25.dahlia"` inside `_init_api_key()`. Makes response shape deterministic regardless of dashboard config. | **YES** — must fix before bump |
| **I** | Hardcoded `sk_test_emergent` fallback | **M** | ~10 LOC | Replace with `_UnconfiguredStripeError` raised on first call. Startup log line `[stripe] configured for API version X · key ends in …last4` per spec. | No (independent) |
| **J** | Missing idempotency key on `SetupIntent.create` | L | 3 LOC | Add `idempotency_key=f"si:{customer_id}:{tenant_id}"`. Nice-to-have; not strictly required. | No |

**Net Phase 42.3 patch estimate:** ~40 LOC production + ~120 LOC tests. Well within the 100-LOC-per-item PAUSE gate.

**Recommended target versions:**
- `stripe>=15.3.0,<16.0.0` in `backend/requirements.txt` — pin the minor floor to what's on PyPI today, keep the major upper bound so a hypothetical v16 with fresh breaking changes doesn't slip in on `pip install -U`.
- `stripe.api_version = "2026-03-25.dahlia"` — matches the SDK's own pinned version at v15.0.0. Every SDK release after this bumps the vendored default, but freezing at the SDK-shipped default insulates us from account-dashboard drift.

---

## 4. Phase 42.2 · env verification (audit findings — no code change yet)

Already discovered above:

- ✅ Every Stripe env var IS consumed via `os.environ.get(...)`. No hard-coded key exists anywhere EXCEPT the `sk_test_emergent` fallback string (triaged as item I above).
- ❌ **No startup log line** confirming which api_version + which key-tail is loaded. Phase 42.2 will add: `[stripe] configured for API version <X> with secret key ending in …<last4>`.
- ✅ Webhook route validates signature via `stripe.Webhook.construct_event` (not raw JSON parse) — see `stripe_charge.py:494`. Router catches `ValueError` / `SignatureVerificationError` and converts to HTTP 400 (`stripe_router.py:259` — spot-verified).
- ❓ **No pytest currently asserts wrong-signature → 400.** Phase 42.2 will add one.

### Phase 42.2 deliverables (to execute after operator ack)

1. Add lazy startup log inside `_init_api_key()` — logs api_version + last-4 of secret key on first call per-process. Idempotent guard.
2. New pytest `backend/tests/test_phase42_stripe_refresh.py::test_webhook_wrong_signature_returns_400`.
3. Add `backend/scripts/verify_stripe_config.py` — masked env var dump + `stripe.Balance.retrieve()` diagnostic. **Not run** from CI; operator invokes manually.

---

## 5. Phase 42.3 · SDK bump + code fixes (execution plan — pending ack)

Based on §3 triage:

1. **`backend/requirements.txt`** — `stripe>=13.0.0,<15.0.0` → `stripe>=15.3.0,<16.0.0`.
2. **`stripe_charge.py:97`** — remove `sk_test_emergent` fallback. Raise `_UnconfiguredStripeError` on `_init_api_key()` if no real key resolves.
3. **`stripe_charge.py:109`** — pin `stripe.api_version = "2026-03-25.dahlia"` inside `_init_api_key()` (once per process; idempotent).
4. **All `.get()` on Stripe responses** — audit + rewrite via a small `_asdict(stripe_resp)` helper. Sites to fix:
   - `stripe_charge.py:401` — `intent.get("status")` + `intent.get("id")`
   - `stripe_charge.py:513–598` — every `data.get(...)` inside `handle_webhook_event` (~8 sites)
5. **`SetupIntent.create`** — add `idempotency_key=f"si:{tenant_id}:{customer_id}"`.
6. **Tests** — `backend/tests/test_phase42_stripe_refresh.py`:
   - Mocked `PaymentIntent.create` + confirmation.
   - Mocked `SetupIntent.attach`.
   - Signed webhook event delivery + signature validation.
   - Wrong-signature returns 400 (from 42.2).
   - Idempotency-key threading through the retry path.
   - Response object treated as attribute-access, not dict-access.

**No breaking change surfaces > 100 LOC.** Cleared to proceed once 42.1 + 42.2 are ack'd.

---

## 6. Rollback plan

If 42.3 breaks production charges:

1. Pin `stripe>=13.0.0,<15.0.0` (revert requirements.txt).
2. Remove the `stripe.api_version` assignment.
3. Keep the log line + wrong-signature test — they're independent improvements.

The `_asdict(resp)` helper is backward-compatible on v13 as well (StripeObject IS a dict there — `.get()` still works), so those code changes can stay in place through the rollback.

---

**Audit end. Awaiting operator ack for Phase 42.2.**
