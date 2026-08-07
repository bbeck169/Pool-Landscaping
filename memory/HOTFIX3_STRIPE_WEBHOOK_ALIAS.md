# P1 Hotfix #3 — Stripe Webhook Legacy-URL Alias

**Date:** 2026-02
**Severity:** P1 — Stripe Dashboard reported webhook delivery failures blocking payment status updates.
**Status:** LANDED. Verified end-to-end against live preview URL by testing subagent (100% backend success, 0 issues, `retest_needed: false`).

---

## 1. Root Cause (one paragraph)

Stripe Dashboard was historically configured to POST webhooks to `https://poolscape-audit.preview.emergentagent.com/api/stripe/webhook`, but the FastAPI router that handles Stripe webhooks lives at `backend/routers/stripe_router.py` with `prefix="/payments/stripe"` — so the real endpoint mounts at `/api/payments/stripe/webhook`. Every Stripe delivery attempt hit `/api/stripe/webhook`, got a `404 Not Found` response, and Stripe (correctly) treated the 404 as a delivery failure. Stripe retries failed deliveries with exponential back-off and eventually surfaces the failure to the operator via email. Backend supervisor logs at `/var/log/supervisor/backend.err.log` confirm the pattern — repeated `POST /api/stripe/webhook HTTP/1.1" 404 Not Found` from IP `10.79.142.69` (the Stripe webhook delivery pool). Signature verification, secret selection (`_select_webhook_secret`), and handler dispatch (`handle_webhook_event`) are all correct; the bug was purely routing. Fix: add a thin alias router at `/stripe` with a single `POST /webhook` route that delegates to the primary handler, so both the historical `/api/stripe/webhook` URL and the intended `/api/payments/stripe/webhook` URL resolve to the same code. Zero operator action required — no Stripe Dashboard change needed.

## 2. Files Touched

| File | Purpose |
|---|---|
| `backend/routers/stripe_router.py` | Added `webhook_alias_router = APIRouter(prefix="/stripe", tags=["stripe-webhook-alias"])` and one new endpoint `POST /webhook` (aliased to the same `post_webhook` handler as the primary route). Handler code, signature verification, secret selection: unchanged. |
| `backend/server.py` | Added `api_router.include_router(_p14a_stripe_router.webhook_alias_router)` immediately after the existing `api_router.include_router(_p14a_stripe_router.router)`. Both routers inherit the `/api` prefix so `/stripe/webhook` mounts at `/api/stripe/webhook`. |
| `backend/tests/test_stripe_webhook_route_hotfix3.py` | **NEW** — 8-test regression suite: 3 route-existence guardrails (alias returns 400 not 404, primary still returns 400, both produce byte-identical envelopes), 4 parametrized event-type tests (`payment_intent.succeeded`, `checkout.session.completed`, `invoice.paid`, `charge.refunded` all return 2xx via mocked `stripe.Webhook.construct_event`), and 1 unhandled-event-type guard (unknown types still return 2xx so Stripe doesn't retry). |

**No changes:**
- `backend/services/payments/stripe_charge.py` — signature verification / secret selection untouched.
- `backend/.env` / `backend/.env.example` — no secret rotation, no env changes. All Stripe keys (`_TEST` and `_LIVE` variants) remain as-is.
- Phase 41.1d stashed WIP (`stash@{0}: phase-41.1d-wip-post-hotfix-3`) not touched.
- Both prior hotfixes (`/api/config/public` + `/portal/login` variant) not touched.

## 3. Env Config Audit (no secrets leaked)

- `STRIPE_MODE`: present (defaults to `test` when unset).
- `STRIPE_SECRET_KEY_TEST` / `STRIPE_SECRET_KEY_LIVE`: both present.
- `STRIPE_WEBHOOK_SECRET_TEST` / `STRIPE_WEBHOOK_SECRET_LIVE`: both present.
- `STRIPE_PUBLISHABLE_KEY_TEST` / `STRIPE_PUBLISHABLE_KEY_LIVE`: both present.

No key rotation was performed. No env values printed in this report. The mode-based secret-selection helper (`services/payments/stripe_charge.py::_select_webhook_secret`) is correct and unchanged.

## 4. Curl Verification (Before / After)

**Before fix (recovered from backend logs):**
```
POST /api/stripe/webhook HTTP/1.1  →  404 Not Found
```

**After fix (local + live preview URL):**
```
$ curl -X POST http://localhost:8001/api/stripe/webhook -d '{}'
{"detail":"invalid signature: Unable to extract timestamp and signatures from header"}
HTTP 400

$ curl -X POST http://localhost:8001/api/payments/stripe/webhook -d '{}'
{"detail":"invalid signature: Unable to extract timestamp and signatures from header"}
HTTP 400
```

Testing agent confirmed the SAME 400 response from the live preview URL `https://poolscape-audit.preview.emergentagent.com/api/stripe/webhook` — proving the fix is deployed and reachable end-to-end. Envelopes are byte-identical between the alias and primary routes (verified in `test_both_routes_share_the_same_handler`).

## 5. Log Excerpts (Original Failures)

From `/var/log/supervisor/backend.err.log` prior to the fix:
```
INFO:     127.0.0.1:49914 - "POST /api/stripe/webhook HTTP/1.1" 404 Not Found
INFO:     10.79.142.69:40766 - "POST /api/stripe/webhook HTTP/1.1" 404 Not Found
INFO:     127.0.0.1:44548 - "POST /api/payments/stripe/webhook HTTP/1.1" 400 Bad Request
```

Note: `10.79.142.69` is the Stripe webhook-delivery source IP. `127.0.0.1` is localhost curl probes. The primary URL was returning `400 Bad Request` (correct signature-error response for a bogus payload); the alias URL was returning `404 Not Found` — the actual failure Stripe was reporting.

## 6. Regression Test Details

**File:** `backend/tests/test_stripe_webhook_route_hotfix3.py` (8 tests, all passing solo)

| # | Test | Assertion |
|---|---|---|
| 1 | `test_alias_route_returns_signature_error_not_404` | `POST /api/stripe/webhook` with bogus payload → 400, `"invalid signature"` in body. Guard: explicit `assert r.status_code != 404` with message referencing this hotfix. |
| 2 | `test_primary_route_returns_signature_error_not_404` | `POST /api/payments/stripe/webhook` → same 400 envelope. |
| 3 | `test_both_routes_share_the_same_handler` | Bogus payload to both routes → byte-identical `json()` responses + same status code. Proves the alias forwards to the same handler. |
| 4–7 | `test_common_event_types_return_2xx[...]` (parametrized) | Mocked `stripe.Webhook.construct_event` via `_FakeWebhook`. Each of `payment_intent.succeeded`, `checkout.session.completed`, `invoice.paid`, `charge.refunded` → 2xx + `{"ok": True, ...}`. |
| 8 | `test_unhandled_event_type_still_returns_2xx` | Unknown event type `"some.new.event.type.stripe.invented"` → 2xx. Guards Stripe from retrying unknown events forever. |

## 7. Operator Action Required

**None.** The Stripe Dashboard URL does NOT need to change — the alias makes the historical URL keep working. For future integrations, the canonical URL to configure is `/api/payments/stripe/webhook`, but both URLs are supported indefinitely.

## 8. Invariants Confirmed Green (per testing agent report `/app/test_reports/iteration_18.json`)

| Gate | Result |
|---|---|
| New regression suite `test_stripe_webhook_route_hotfix3.py` | **8/8 passed** ✅ |
| Testing subagent backend success rate | **100%** ✅ |
| `retest_needed` | `false` ✅ |
| Live preview URL `POST /api/stripe/webhook` | 400 invalid signature (was 404) ✅ |
| Live preview URL `POST /api/payments/stripe/webhook` | 400 invalid signature ✅ |
| Envelopes identical between alias and primary | ✅ |
| `/api/config/public` regression | Still returns `{show_demo_logins, app_env}` HTTP 200 ✅ |
| Phase 41.1d stash | Still `stash@{0}: phase-41.1d-wip-post-hotfix-3` — not touched ✅ |
| Prior hotfixes (login variant, /portal/login) | Not regressed ✅ |

**End of P1 Hotfix #3 report.**
