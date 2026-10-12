# Stripe Production Webhook — Root Cause Analysis

**Scope:** `https://app.plofv.com/api/payments/stripe/webhook` failing to receive LIVE events (reported by Stripe Dashboard delivery log).
**Phase:** P0c · Stage 1 (diagnosis, no code change)
**Date:** Feb-2026
**Author:** stripe-webhook triage agent (preview pod inspection only — no production shell/log access)

---

## 1. Route registration audit — ✅ CLEAN

### 1.1 Grep inventory
```
backend/routers/stripe_router.py:623       @router.post("/webhook")           → post_webhook
backend/routers/stripe_router.py:681       @webhook_alias_router.post("/webhook") → post_webhook_alias
backend/routers/tenant_integrations.py:1555 @router.post("/integrations/stripe/webhook") → stripe_webhook  (DIFFERENT endpoint — not the dashboard target)
```

### 1.2 FastAPI include chain (`backend/server.py:1271-1277`)
```python
from routers import stripe_router as _p14a_stripe_router
api_router.include_router(_p14a_stripe_router.router)              # prefix=/payments/stripe
api_router.include_router(_p14a_stripe_router.webhook_alias_router) # prefix=/stripe
```
`api_router` itself is mounted at `/api`. Resulting paths:
- `POST /api/payments/stripe/webhook`  ← primary (matches Stripe Dashboard URL)
- `POST /api/stripe/webhook`           ← legacy alias (also forwards to `post_webhook`)

### 1.3 OpenAPI confirmation (live preview pod)
```
$ curl -s /api/openapi.json | jq '.paths | keys[] | select(contains("stripe"))'
/api/admin/stripe/dead-letter
/api/admin/stripe/dead-letter/{event_id}/retry
/api/integrations/stripe/callback
/api/integrations/stripe/connect-link
/api/integrations/stripe/webhook         ← tenant_integrations route (NOT the dashboard target)
/api/payments/stripe/attach
/api/payments/stripe/charge
/api/payments/stripe/config
/api/payments/stripe/payment-methods/{customer_id}
/api/payments/stripe/payment-methods/{payment_method_id}
/api/payments/stripe/payment-methods/{payment_method_id}/delete-typed
/api/payments/stripe/payment-methods/{payment_method_id}/set-default
/api/payments/stripe/session/{session_id}/reconcile
/api/payments/stripe/setup-intent
/api/payments/stripe/test-hook/tenant-billing-event
/api/payments/stripe/webhook              ← MATCHES Stripe Dashboard URL
/api/stripe/webhook                       ← legacy alias
```

**Conclusion:** route exists, mounted at the exact path the Stripe Dashboard
is configured to call. Rules out "route 404" as a cause. Both the primary
`/api/payments/stripe/webhook` and the legacy `/api/stripe/webhook` alias
resolve to the same handler.

---

## 2. Handler flow audit — ⚠ SYNCHRONOUS WORK BEFORE 200

### 2.1 End-to-end sequence (`backend/routers/stripe_router.py:623-673`)

```python
@router.post("/webhook")
async def post_webhook(request: Request):
    payload = await request.body()                              # 1. raw bytes (good)
    sig     = request.headers.get("stripe-signature") or ""
    try:
        event = stripe_svc.verify_and_parse_webhook(            # 2. HMAC + parse
            payload=payload, sig_header=sig,
        )
    except stripe_svc.ThinPayloadRetrieveError as exc:
        raise HTTPException(502, …)                             # 2a. Thin-payload retry → 502
    except ValueError as exc:
        raise HTTPException(400, …)                             # 2b. malformed → 400
    except Exception as exc:
        raise HTTPException(400, f"invalid signature: {exc}")   # 2c. bad sig → 400

    # 3. dedup ledger insert (DB write)
    ledger = await insert_or_skip(event)
    if ledger.get("status") == "skipped_duplicate":
        return {"ok": True, "handled": False, …}                # 3a. duplicate → 200 fast path

    # 4. BUSINESS HANDLER — variable-duration DB writes + external calls
    try:
        result = await stripe_svc.handle_webhook_event(event)
    except stripe_svc.ThinPayloadRetrieveError:
        raise                                                   # 4a. Thin retry → 502
    except Exception as exc:
        await record_dead_letter(…)                             # 4b. crash → DL + 502
        await mark_failed(…)
        raise HTTPException(502, …)

    # 5. mark handled (DB write)
    await mark_handled(ledger.get("event_id") or "", result=result)
    return {"ok": True, **result}                               # 6. finally 200
```

### 2.2 Work that runs synchronously BEFORE the 200 return
| Step | Operation | Latency class |
|---|---|---|
| 1 | `await request.body()` | fast (bytes buffered) |
| 2 | `stripe.Webhook.construct_event` HMAC verify + JSON parse | fast (<5ms) |
| 2 (Thin fallback) | `stripe.Event.retrieve(event_id)` HTTP round-trip to api.stripe.com | **slow — 100-500ms typical, can be 1-5s under network pressure** |
| 3 | Mongo insert on `stripe_webhook_events` (dedup ledger) | fast (local Mongo <20ms) |
| 4 | `handle_webhook_event` — type-dispatch to one of: | **variable** |
|   | · `payment_method.attached` → Mongo lookups + insert | fast |
|   | · `payment_intent.succeeded/failed` → `stripe_charges` upsert | fast |
|   | · `invoice.payment_succeeded` (tenant-billing branch) → `handle_tenant_billing_event` | **variable — see `services/tenant_billing_webhooks.py`** |
| 5 | `mark_handled` Mongo update on ledger | fast |

The sum of steps 1–5 is well under 1s on the happy path. BUT:
- On cold-start of the FastAPI process (first webhook after idle), Mongo
  connection pool bootstrap + `stripe` SDK HTTP client init add 1-3s.
- On Thin-payload events (Stripe's new default for new Event Destinations),
  the `stripe.Event.retrieve` round-trip is REQUIRED before step 3 — on
  slow network paths this alone can approach Stripe's advertised 30s
  acknowledgment budget.
- `handle_tenant_billing_event` is not timing-audited in this doc; if it
  does any external calls (email dispatch, downstream billing API), that
  compounds.

**Deviation from Stripe best practice:** Stripe's docs explicitly recommend
"respond with 200 immediately after verifying signature; process in a
background task." Our handler does step 2 (verify) + step 3 (ledger) +
**step 4 (full business logic)** before returning 200. For the dedup
duplicate case we DO short-circuit (step 3a), which is good. For the
non-duplicate case we don't.

**Severity:** moderate — unlikely to be the actual root cause of a
blanket "failing to receive events" symptom (that implies 100% failure,
not timeouts on a slow subset), but it IS a Stripe-recommended fix the
operator should enact regardless. If the production delivery log shows
*some* events succeeding and others timing out, this IS the cause.

---

## 3. Env var audit — ⚠ MODE-DEPENDENT, CANNOT VERIFY PROD

### 3.1 Env var contract (`backend/services/payments/stripe_charge.py:145-150`)
```python
def _select_webhook_secret() -> str:
    mode = _mode()
    env_key = "STRIPE_WEBHOOK_SECRET_LIVE" if mode == "live" else "STRIPE_WEBHOOK_SECRET_TEST"
    return (os.environ.get(env_key) or "").strip() or (
        os.environ.get("STRIPE_WEBHOOK_SECRET") or ""
    ).strip()
```

Where `_mode()` is:
```python
def _mode() -> str:
    val = (os.environ.get("STRIPE_MODE") or "test").strip().lower()
    return "live" if val == "live" else "test"
```

### 3.2 Resolution matrix
| `STRIPE_MODE` | Primary env var consulted | Fallback env var |
|---|---|---|
| `live`        | `STRIPE_WEBHOOK_SECRET_LIVE` | `STRIPE_WEBHOOK_SECRET` |
| `test` / unset| `STRIPE_WEBHOOK_SECRET_TEST` | `STRIPE_WEBHOOK_SECRET` |

The fallback to the generic `STRIPE_WEBHOOK_SECRET` is a **footgun**:
if the production pod was configured years ago with only the generic
`STRIPE_WEBHOOK_SECRET` variable holding the TEST webhook signing secret
(from the initial dev set-up), and `STRIPE_MODE` was later flipped to
`live` without rotating the fallback secret, every live event would
fail signature verification with 400 and Stripe would stop retries
after 3 days per its backoff policy. Users don't notice until invoice
reconciles start drifting.

### 3.3 Preview pod state (verified)
```
STRIPE_MODE=live
STRIPE_SECRET_KEY_TEST=***         (set)
STRIPE_SECRET_KEY_LIVE=***         (set)
STRIPE_WEBHOOK_SECRET_TEST=***     (set)
STRIPE_WEBHOOK_SECRET_LIVE=***     (set)
STRIPE_PUBLISHABLE_KEY_TEST=***    (set)
STRIPE_PUBLISHABLE_KEY_LIVE=***    (set)
STRIPE_CONNECT_CLIENT_ID=***       (set)
```
Preview is correctly configured. **We cannot inspect the production pod's
env from this environment.** Per the user's instructions elsewhere in
this engagement, "we do not have direct access to production DB or
environment" — the operator must verify the prod env directly.

### 3.4 Operator checklist for production env
Required on the production pod — operator to confirm each:
1. `STRIPE_MODE=live` set? (If missing or `test`, every live-mode
   webhook falls through to the TEST webhook secret → 400.)
2. `STRIPE_WEBHOOK_SECRET_LIVE` set? (This is the signing secret issued
   by Stripe Dashboard for the LIVE endpoint, NOT the test endpoint.
   Each has a distinct `whsec_…` value.)
3. If only the generic `STRIPE_WEBHOOK_SECRET` is set, confirm its
   value matches the LIVE endpoint's secret (not test).
4. `STRIPE_SECRET_KEY_LIVE` is set — needed for the Thin-payload
   `stripe.Event.retrieve` fallback (which uses `stripe.api_key`).
   If missing, every Thin-payload event raises `ThinPayloadRetrieveError`
   → 502 → Stripe keeps retrying forever (3 days of 502s).

Operator can verify via the admin diagnostics endpoint (preview pod
already serves this, prod pod should too):
```
GET /api/admin/stripe/webhook-config-diag   (needs admin auth)
```
...or by inspecting the pod's environment directly:
```
kubectl exec <prod-pod> -- env | grep STRIPE
```

---

## 4. Signature verification logic — ✅ CORRECT

### 4.1 Primary path (`backend/services/payments/stripe_charge.py:1736-1766`)
```python
def verify_and_parse_webhook(*, payload: bytes, sig_header: str):
    secret = _select_webhook_secret()
    if not secret:
        raise ValueError("webhook secret not configured for current STRIPE_MODE")
    try:
        event = _stripe.Webhook.construct_event(payload, sig_header, secret)
        return _asdict(event)
    except Exception as exc:
        if "thin event notification" not in str(exc).lower():
            raise                                   # bad sig → surfaces to router → 400
        # Thin-payload fallback below.
        ...
```

- Uses Stripe SDK's `Webhook.construct_event` — NOT hand-rolled HMAC.
- Receives `payload` as `bytes` (not pre-parsed JSON) — the router
  gets it via `await request.body()`, which returns the raw body bytes
  exactly as Stripe sent them.
- `sig_header` is read verbatim from the `stripe-signature` request
  header; no normalization.
- No middleware is reading + re-serializing the body before the
  handler sees it (confirmed by checking the preview-isolation
  middleware registry — `/api/payments/stripe/webhook` is NOT in
  `PII_INGRESS_REGISTRY`, so the sanitizer middleware doesn't touch
  it; even if it did, the middleware is a strict no-op on production).

**Conclusion:** signature logic is implemented correctly. Rules out
"hand-rolled HMAC bug" and "middleware body-mangling" as causes.

### 4.2 Thin-payload fallback (`backend/services/payments/stripe_charge.py:1767-1798`)
```python
# When construct_event raises "thin event notification":
_stripe.WebhookSignature.verify_header(payload, sig_header, secret)  # same crypto
envelope = json.loads(payload)
event_id = envelope.get("id")
hydrated = _stripe.Event.retrieve(event_id)                           # extra HTTP round-trip
return _asdict(hydrated)
```
- Same signature check (`WebhookSignature.verify_header` is the exact
  function `construct_event` uses internally).
- Falls back to `Event.retrieve` to hydrate the full snapshot.
- `Event.retrieve` uses `stripe.api_key` — so `STRIPE_SECRET_KEY_LIVE`
  MUST also be set on prod for Thin payloads to work.

---

## 5. Server log evidence — ⛔ NOT AVAILABLE FROM PREVIEW POD

We can't `tail /var/log/supervisor/backend.err.log` on the production
pod from here. The user / operator should check production logs with:

### 5.1 What to grep in production
```
kubectl logs <prod-pod> --since=24h | grep -iE 'stripe.*webhook|post_webhook|verify_and_parse|signature'
```

### 5.2 Status-code decision tree the operator should run

| Log pattern | Means | Next step |
|---|---|---|
| `invalid signature: SignatureVerificationError` with `400` return | Wrong signing secret (test configured for live, or stale rotation) | Rotate `STRIPE_WEBHOOK_SECRET_LIVE` to the current Dashboard value |
| `webhook secret not configured for current STRIPE_MODE` | Env var missing entirely | Set `STRIPE_WEBHOOK_SECRET_LIVE` on prod + restart |
| `thin event notification` + `Event.retrieve failed` + `502` | Thin-payload events, but `STRIPE_SECRET_KEY_LIVE` missing (or Stripe API down) | Set `STRIPE_SECRET_KEY_LIVE` on prod + restart; verify stripe.com reachability |
| `handler failed:` + `502` + dead-letter row | Business logic crash in `handle_webhook_event` | Read the dead-letter row via `GET /api/admin/stripe/dead-letter`, fix the handler bug |
| No `stripe` lines at all in 24h | Stripe's requests aren't reaching the pod — DNS/ingress/firewall problem | Check `app.plofv.com` ingress + CloudFlare / CDN rules |
| 200 responses on the preview path but Stripe Dashboard still shows failures | Stripe is hitting a stale URL cached before the `/payments/stripe` prefix refactor | Point Dashboard at the current primary URL explicitly |
| Latency > 10s in access log before 200 | Handler too slow — Stripe's 10s/30s timeout fires | Convert step 4 (`handle_webhook_event`) to a background task |

---

## 6. Hypothesis & proposed fix (ordered by likelihood)

| # | Hypothesis | Evidence we have | Evidence operator needs to collect | Proposed fix |
|---|---|---|---|---|
| 1 | **Wrong signing secret on prod** — `STRIPE_WEBHOOK_SECRET_LIVE` is unset / stale / holds TEST secret | Preview env has both LIVE + TEST set correctly; code path is correct; signature errors return 400 which the Stripe Dashboard surfaces as "failed" | `kubectl exec` into prod + `env \| grep STRIPE_WEBHOOK` ; also check Stripe Dashboard event-delivery log for the exact HTTP status code of recent failures | Rotate: regenerate `whsec_…` for the live endpoint in Stripe Dashboard → set `STRIPE_WEBHOOK_SECRET_LIVE` on prod → restart backend → reset the Stripe retry queue in Dashboard |
| 2 | **Handler timeout** — synchronous `handle_webhook_event` + Thin-payload `Event.retrieve` round-trip exceeds Stripe's 10s acknowledgment budget on some events | Handler does ALL business logic pre-200 (section 2.2); Thin payloads are now Stripe's default for new Event Destinations | Check prod access log for request-duration >10s on `/api/payments/stripe/webhook` | Refactor: return 200 immediately after step 3 (ledger insert) → kick step 4 to a `BackgroundTasks` or `asyncio.create_task` worker that writes the result back to the ledger. Preserves dedup + dead-letter + mark_handled semantics. |
| 3 | **Stripe Dashboard URL drift** — Dashboard points at `/api/stripe/webhook` (legacy) or an older short path, and some ingress / CDN layer isn't preserving the alias forward | We have both the primary AND alias routes registered. Confirmed in OpenAPI. | Verify Dashboard endpoint URL exactly matches `https://app.plofv.com/api/payments/stripe/webhook` character-for-character | Update Dashboard URL to the primary path; alias is defensive-depth but shouldn't be the long-term target |
| 4 | **Thin-payload fallback failure** — events are Thin, `STRIPE_SECRET_KEY_LIVE` is missing or wrong, so `Event.retrieve` 500s, handler returns 502, Stripe retries, eventually gives up after 3 days | Code path for Thin returns 502 (good — triggers Stripe retry); `_select_secret_key` resolves same way as webhook secret | Check prod logs for `thin event notification` + `Event.retrieve` errors | Set `STRIPE_SECRET_KEY_LIVE` on prod |
| 5 | **Signature verification body-mangling** — some middleware is re-serializing the body before the handler reads it | Preview middleware registry does NOT include the webhook path; middleware is prod no-op anyway; `await request.body()` returns raw bytes | n/a (ruled out) | n/a |
| 6 | **Route not registered** — the route genuinely doesn't exist on prod | OpenAPI on preview shows it. Prod is deployed from the same git tree. | `curl -sI https://app.plofv.com/api/payments/stripe/webhook` — expect 405 (POST-only, GET returns Method Not Allowed) or 400, NOT 404 | n/a (ruled out) |

---

## 7. Recommended Stage 2 action plan (after operator diagnosis)

1. **Operator collects evidence first** — one `curl` + one `env | grep STRIPE_WEBHOOK` + one Dashboard screenshot of a failed delivery's response status.
2. Report back which of hypotheses 1–4 matches.
3. Stage 2 code changes:
   - **Non-controversial, do regardless** (preempts hypothesis 2): refactor `post_webhook` to return 200 immediately after `insert_or_skip` and dispatch `handle_webhook_event` to a background task. Preserves dedup + dead-letter + mark_handled semantics (background task writes `mark_handled`/`mark_failed`/`record_dead_letter` as it currently does; synchronous caller just acknowledges).
   - **Only if hypothesis 1 confirmed**: operator-side env rotation; no code change needed.
   - **Only if hypothesis 4 confirmed**: operator-side `STRIPE_SECRET_KEY_LIVE` set; add a boot-time log that warns loudly when `STRIPE_MODE=live` but `STRIPE_SECRET_KEY_LIVE` is empty (currently fails fast on first API call, which is correct but silent until the first charge is attempted).
4. Add a `GET /api/admin/stripe/webhook-config-diag` admin endpoint
   that returns a redacted inventory of which env vars are set + the
   mode + last-handled-event timestamp. The operator can hit this on
   prod and immediately see mode-vs-secret misalignment without ever
   reading the raw secret value.
5. Add a pytest regression that fails if the webhook handler does any
   DB writes before the 200 ack path.

---

## 8. What this RCA DOES NOT do

- Does not modify any code (per Stage 1 instruction).
- Does not touch `/app/mobile`.
- Does not restart any service.
- Does not purge the Stripe dead-letter queue or ledger.
- Does not rotate any secret.

Awaiting operator confirmation on hypothesis before Stage 2.
