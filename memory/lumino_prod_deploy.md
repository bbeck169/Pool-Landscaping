# Lumino production cutover runbook — Feb 2026

**Preview is mock-only. Every step below runs on prod ONLY.**

## Pre-flight

- [ ] Confirm all preview pytest + Jest suites green (last: 85+ pytest, 134 Jest; Task QQ Phase 2 additions: 12 pytests in `tests/test_task_qq_p2_lumino.py` + `tests/test_task_qq_p2_hydrate.py`).
- [ ] Confirm `PAYMENT_PROVIDER=stripe` in the preview `.env` (unchanged).
- [ ] Confirm no live secrets ever entered preview `.env`.
- [ ] Confirm the nightly reconciler cron is installed in preview boot logs: `lumino_reconciler: nightly cron registered (03:00 UTC)`.

## Step 1 — Fresh Lumino secret

1. Log into Lumino dashboard as owner.
2. **Rotate** the previous live secret (paranoid — the failed chat-paste attempt is compromised regardless of whether it leaked).
3. Generate a new live secret. Copy once.

## Step 2 — Zapier configuration

The bridge accepts `event_type` from an **HTTP header** first
(Phase 2.5, Feb 2026). If the header is missing or its value is
not in the allow-list, the backend infers `event_type` from
`data.status` in the JSON body and records
`resolution_source="inferred"` on the stored `payment_events` doc
so operators can spot a misconfigured Zap.

### Shared secret

Generate a **fresh** shared secret at cutover — never reuse any
value that has been pasted in chat, email, log, ticket, or PR
description (they are compromised regardless of whether they
actually leaked):

```
openssl rand -hex 32
```

Set the output as `LUMINO_ZAPIER_SHARED_SECRET` in the prod pod's
secure env manager (Step 3). In preview `.env` this stays **empty**
so the bridge fails closed with `401 shared secret not configured`.

**Never paste the shared secret in chat, email, or logs.** If it
does end up somewhere insecure, rotate immediately.

### Per-Zap configuration

7 Zaps total. All share the same Action (Webhooks by Zapier →
POST) and the same URL / auth header — only the `event_type`
header differs.

**Common to every Zap**
- URL: `https://app.plofv.com/api/webhooks/lumino/zapier`
- Method: `POST`
- Header `x-zapier-shared-secret`: `<value from openssl rand>`
- Header `Content-Type`: `application/json`
- Body (JSON):
  ```json
  {
    "event_id": "{{lumino.event_id}}",
    "occurred_at": "{{lumino.occurred_at}}",
    "data": { … per-event Lumino payload … }
  }
  ```
  (Note: `event_type` is no longer required in the body — the
  header carries it. If included in the body it will be ignored;
  header wins.)

**Per-Zap `event_type` header**

| Zap name | Lumino trigger | `event_type` header value |
|----------|----------------|---------------------------|
| New Payment | Payment.Succeeded | `payment.created` |
| Updated Payment | Payment.Updated | `payment.updated` |
| Refunded Payment | Payment.Refunded | `payment.refunded` |
| Subscription Renewed | Subscription.Renewed | `subscription.renewed` |
| Subscription Canceled | Subscription.Canceled | `subscription.canceled` |
| Dispute Opened | Dispute.Opened | `dispute.opened` |
| Dispute Resolved | Dispute.Resolved | `dispute.resolved` |

### Zap destinations (approved by user Feb 2026)

**Each of the 3 payment Zaps (New Payment, Updated Payment,
Refunded Payment) has exactly ONE Action step — the POST to
`https://app.plofv.com/api/webhooks/lumino/zapier`. No secondary
email / Slack / Sheets steps.** If audit-trail visibility is
needed later, add them as **extra Action steps on the same Zap**
— do NOT create new Zaps (a second Zap on the same trigger would
double-fire the webhook and, thanks to `event_id` dedupe, the
second call would 200 as `deduped:true` but pollute
`payment_events` traffic metrics).

The same one-Action rule applies to the 4 subscription / dispute
Zaps for consistency.

### Pre-enable checklist

- ☐ Confirm each Zap has ONE Action step only before enabling.
- ☐ Confirm each Zap's `event_type` header matches the table above.
- ☐ Confirm the shared secret is set in prod pod env (Step 3) BEFORE
      enabling any Zap — otherwise every event 401s and Zapier will
      auto-disable the Zap after N failures.
- ☐ Send one manual test event through each Zap and verify
      `db.payment_events.find({"lumino_event_id": <test id>})`
      contains `resolution_source: "header"`.

## Step 3 — Prod pod env vars (secure)

Set in the prod pod's secret manager (**not** in any file in git):

```
LUMINO_API_URL=https://api.lumino.com/v1
LUMINO_API_TOKEN=<fresh live secret from step 1>
LUMINO_ZAPIER_SHARED_SECRET=<fresh secret from step 2>
LUMINO_RETURN_URL=https://app.plofv.com/portal/payment-method/return
PAYMENTS_TEST_ALLOWLIST_CUSTOMERS=          # keep empty for prod
```

**Keep `PAYMENT_PROVIDER=stripe` for now.** The flip happens in Step 6.

## Step 4 — Migration dry-run report

From the prod pod shell:
```
python /app/backend/scripts/migrate_stripe_to_lumino.py \
  --dry-run-report-only --tenant-id <PROD_TENANT_ID>
```

Inspect the printed plan. Confirm expected N customers / N payment methods / N subscriptions.

## Step 5 — Live migration

```
python /app/backend/scripts/migrate_stripe_to_lumino.py \
  --live --tenant-id <PROD_TENANT_ID> \
  --i-know-this-is-production
```

Type `YES` at the confirmation prompt.

Verify a sample of migrated records now carry `lumino_customer_id` / `lumino_payment_method_id` / `lumino_subscription_id`.

## Step 6 — Flip the provider

Set `PAYMENT_PROVIDER=lumino` in prod pod env. Restart backend.

## Step 7 — Smoke test

Use exactly one opted-in real customer (Brian). Test:
- Add card → confirm Lumino hosted checkout, complete, return-URL renders success.
- Pay Now on a $1 test invoice → confirm success.
- Cancel-then-reactivate a subscription → confirm Zapier event lands in `payment_events`.

## Step 8 — Monitor 48h

- Watch `payment_events` collection growth.
- Watch `reconciliation_log` — errors should be zero after 24h.
- If any anomaly → **immediate rollback (Step 9)**.

## Step 9 — Rollback

- Set `PAYMENT_PROVIDER=stripe` in prod pod env.
- Restart backend.
- Existing Stripe subscriptions (never migrated because the migration was one-way) continue billing as they did before.
- Newly-Lumino-only customers may need a manual card re-entry — communicate before rollback.

## Step 10 — Wider rollout

After the 48h Brian window is clean:
- Communication to customer base: brief email + in-portal banner (Task QQ Phase 3 scope).
- Gradually shift more tenants onto Lumino by tenant_id.
