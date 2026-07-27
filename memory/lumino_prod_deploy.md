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

For each of these Lumino events, create a Zap:
- `subscription.renewed`
- `subscription.canceled`
- `payment.refunded`
- `dispute.opened`
- `dispute.resolved`

Zap action: **Webhooks by Zapier → POST**
- URL: `https://app.plofv.com/api/webhooks/lumino/zapier`
- Header: `x-zapier-shared-secret: <SHARED_SECRET>` (generate fresh; do not reuse)
- Body (JSON):
  ```json
  {
    "event_id": "{{lumino.event_id}}",
    "event_type": "{{lumino.event_type}}",
    "occurred_at": "{{lumino.occurred_at}}",
    "data": { … per-event Lumino payload … }
  }
  ```

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
