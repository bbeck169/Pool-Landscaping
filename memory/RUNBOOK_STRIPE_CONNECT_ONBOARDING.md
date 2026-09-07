# Runbook · Stripe Connect (Standard) Onboarding · Phase I1.7.a

Reference for on-call + support when a tenant hits the Bring-Your-Own-Stripe flow.

## Preconditions
* Platform Stripe env is populated in `backend/.env`:
  * `STRIPE_SECRET_KEY_TEST` / `STRIPE_SECRET_KEY_LIVE`
  * `STRIPE_WEBHOOK_SECRET_TEST` / `STRIPE_WEBHOOK_SECRET_LIVE`
  * `STRIPE_CONNECT_CLIENT_ID` (the `ca_…` id from Stripe Dashboard → Settings → Connect settings → OAuth settings).
* `TENANT_SECRETS_KEK_B64` is set (32 raw bytes base64-encoded).
* `STRIPE_PLATFORM_FALLBACK_ENABLED=true` while at least one legacy tenant is still on the platform key.

## Happy path (tenant admin)
1. Sign in as `role ∈ {admin, super_admin}`.
2. Go to **Settings → Integrations**.
3. In **Bring your own providers**, click **Connect Stripe** on the Stripe card.
4. Complete Stripe's OAuth flow (sign in / create account / grant access).
5. Stripe posts back to `/api/integrations/stripe/callback?code=…&state=…`.
6. Backend exchanges the code, persists the access token + `stripe_user_id` via `services.secrets` (encrypted at rest), redirects to `/settings/integrations?connect=success`.
7. The card now renders `Connected · acct_…xxxx · Token · last 4: ••••xxxx`.
8. Click **Test connection** → backend does `stripe.Account.retrieve(api_key=<tenant token>)` and returns `ok: true` on success.

## Pod / dev path (no Stripe network)
Set the following in `backend/.env` (already configured in preview):
```
STRIPE_TESTMODE_MOCK_CONNECT=true
STRIPE_MOCK_CHARGES=true
```
Then **Connect Stripe** short-circuits to a synthetic `acct_test_…` account without leaving the pod. Charges also stub to `ch_mock_…`.

## Failure modes
| Symptom | Cause | Fix |
| --- | --- | --- |
| `503 STRIPE_CONNECT_CLIENT_ID is not set` on connect-link | Env missing | Set the var and restart backend |
| Callback redirects with `?connect=error&reason=state_unknown` | Old link replayed after TTL | Ask tenant to retry — TTL is 15 min |
| Callback redirects with `?connect=error&reason=state_expired` | User waited too long on Stripe's screen | Retry |
| Callback redirects with `?connect=error&reason=exchange_failed` | Stripe rejected the auth code | Check platform key + Connect client id match the same Stripe account |
| Callback redirects with `?connect=error&reason=missing_fields` | Stripe returned a token payload without `access_token` / `stripe_user_id` | Investigate Stripe dashboard event log — usually a Connect settings misconfiguration |
| `Test connection` returns `ok:false · Stripe probe failed: AuthenticationError` | Tenant revoked access in their Stripe dashboard | Ask tenant to reconnect |
| Webhook returns 400 `verify_failed` | Wrong endpoint on Stripe side, or the platform webhook secret rotated | Verify signing secret on Stripe dashboard matches `STRIPE_WEBHOOK_SECRET_*` in `.env` |

## Disconnect
Admin clicks **Disconnect** in the card → confirms → `DELETE /api/tenants/me/integrations/stripe`. The row is removed. Every subsequent charge routes to the platform key while `STRIPE_PLATFORM_FALLBACK_ENABLED=true` and appends to `platform_stripe_fallback_log`.

## Audit
* Every fallback call → `platform_stripe_fallback_log` (tenant_id, op, at).
* Every OAuth exchange failure → `tenant_secrets.error_log` (capped 20 entries).
* Every webhook → `stripe_webhook_events` (dedupe by `event_id`).

## Rotating a tenant's token
Tenants rotate by revoking in Stripe → the next probe will flip `connected_status` to `error`. They then click **Connect Stripe** again; `put_secret` overwrites the row atomically (new IV + new ciphertext, old plaintext unrecoverable).

## Rotating the platform Stripe key
Update the `STRIPE_SECRET_KEY_*` env var, restart backend. Tenant tokens are unaffected — they are stored per-tenant. Only the platform-fallback path uses the platform key.

## Rotating the KEK (`TENANT_SECRETS_KEK_B64`)
`crypto.py` supports a rolling KEK header prefix in `dek_wrapped`. Change the env var + run `POST /api/admin/migrations/rewrap-tenant-secrets` (follow-up phase I1.7.e — not shipped in I1.7.a; today rotation requires re-connect).

## Health check
```
$ curl -X GET  $API/api/tenants/me/integrations   -H "Authorization: Bearer $TOK"
$ curl -X POST $API/api/tenants/me/integrations/stripe/test -H "Authorization: Bearer $TOK"
```
Both should return 200 for a signed-in admin whose tenant has a live connection.
