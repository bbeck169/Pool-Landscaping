# Phase I1.7.a · Feb-2026 — Tenant Integrations (Stripe Connect + BYO scaffolding)

## Scope
* Encrypted secret storage (AES-256-GCM at rest) in `backend/services/secrets/`.
* Abstract `TenantPaymentProvider` adapter in `backend/services/payments/tenant_base.py`.
* Stripe Connect **Standard** OAuth implementation in `tenant_stripe.py` with platform-Stripe fallback preserved via `STRIPE_PLATFORM_FALLBACK_ENABLED`.
* Provider registry / factory (`tenant_registry.py`).
* Settings → Integrations page (`/settings/integrations`) surfaces a working Stripe card + six "Coming soon" placeholders (SMS, Email, AI, Maps, Calendars, Storage).
* Backend Pytest + Frontend Vitest coverage.

## Files shipped

### Backend
| File | Purpose |
| --- | --- |
| `backend/services/secrets/models.py` | `TenantSecret`, `ConnectionType`, `ConnectionStatus`, `ConnectionSummary` |
| `backend/services/secrets/crypto.py` | AES-256-GCM encrypt/decrypt + wrapped DEK helpers |
| `backend/services/secrets/store.py` | Motor-async CRUD (never returns plaintext outside the encryption boundary) |
| `backend/services/payments/tenant_base.py` | `TenantPaymentProvider` abstract interface + result dataclasses |
| `backend/services/payments/tenant_stripe.py` | Stripe Connect Standard adapter + OAuth exchange + webhook verify |
| `backend/services/payments/tenant_registry.py` | Provider registry / factory (`get_provider`, `UnknownProvider`) |
| `backend/routers/tenant_integrations.py` | HTTP contract for `/api/tenants/me/integrations` + `/api/integrations/stripe/*` |

### Frontend
| File | Purpose |
| --- | --- |
| `frontend/src/components/settings/TenantIntegrationsCard.jsx` | BYO providers card (Stripe live, six placeholders) |
| `frontend/src/pages/settings/IntegrationsPages.jsx` | Mounts the BYO card above the legacy env-based grid |

### Tests
| File | Scope |
| --- | --- |
| `backend/tests/test_i17a_secret_storage.py` | Encrypt / decrypt / rotate / error-log cap / masking |
| `backend/tests/test_i17a_payment_provider_interface.py` | Adapter contract + registry |
| `backend/tests/test_i17a_stripe_connect_flow.py` | Connect-link + callback (with `STRIPE_TESTMODE_MOCK_CONNECT=true`) |
| `backend/tests/test_i17a_stripe_webhook.py` | Signature verify + dedupe |
| `backend/tests/test_i17a_integrations_endpoint.py` | HTTP contract + role gating + masked-summary shape |
| `backend/tests/test_i17a_fallback_platform_stripe.py` | Platform-fallback audit log |
| `frontend/src/test/i17a-integrations-page.test.jsx` | UI contract + role-gate + plaintext-safety |

## API Contract (public)

### `GET /api/tenants/me/integrations`
```json
{
  "tenant_id": "…",
  "integrations": [
    {
      "provider_key": "stripe",
      "connection_type": "oauth_stripe_connect",
      "connected": true,
      "last_4": "beef",
      "connected_account_id_masked": "acct_…9xyz",
      "last_used_at": "2026-02-01T12:00:00Z",
      "connected_status": "connected",
      "error_log_count": 0,
      "last_error": null
    }
  ]
}
```
NEVER echoes plaintext. Read gate: `admin` / `manager` / `super_admin`.

### `POST /api/tenants/me/integrations/{provider_key}/test`
Runs a lightweight probe (Stripe: `Account.retrieve`). Returns `ConnectionHealth`. Write gate.

### `DELETE /api/tenants/me/integrations/{provider_key}`
Removes the row. Idempotent. Write gate.

### `GET /api/integrations/stripe/connect-link`
Mints an `oauth_pending` state (TTL 15 min) and returns Stripe's OAuth authorize URL. When `STRIPE_TESTMODE_MOCK_CONNECT=true` short-circuits to the callback with a synthetic `code`.

### `GET /api/integrations/stripe/callback`
Exchanges the OAuth `code`, persists via `services.secrets`, redirects back to `/settings/integrations?connect=success|error&reason=…`.

### `POST /api/integrations/stripe/webhook`
Public. Verifies signature (`stripe.Webhook.construct_event`), dedupes by `event.id` on `stripe_webhook_events`. Returns `400 verify_failed` on bad signature; `200 { received, duplicate }` on ok.

## Encryption Boundary

Plaintext lives ONLY between:
* `crypto.encrypt` and the caller passing plaintext into `put_secret`.
* `crypto.decrypt` inside `get_secret` and the immediate provider-adapter call (`api_key=<plaintext>` into the Stripe SDK).

Guardrails:
* `put_secret` rejects empty plaintext.
* `list_connections` / `connection_summary` NEVER read the ciphertext.
* `log_error` message is truncated to 400 chars and capped at 20 entries per row.
* `get_secret` bumps `last_used_at` best-effort (fire-and-forget update).
* No logger in `tenant_stripe.py` includes the api_key — errors log the exception TYPE only.

## Env Vars

| Var | Required for | Default |
| --- | --- | --- |
| `STRIPE_MODE` | Selects test vs. live secret keys | `test` |
| `STRIPE_SECRET_KEY_TEST` / `STRIPE_SECRET_KEY_LIVE` | Platform-fallback + OAuth exchange | — |
| `STRIPE_WEBHOOK_SECRET_TEST` / `STRIPE_WEBHOOK_SECRET_LIVE` | Webhook signature verify | — |
| `STRIPE_CONNECT_CLIENT_ID` | OAuth authorize URL | — |
| `STRIPE_PLATFORM_FALLBACK_ENABLED` | Charge on platform key when tenant unconnected | `true` |
| `STRIPE_TESTMODE_MOCK_CONNECT` | Short-circuit connect-link for the pod (dev only) | `false` |
| `STRIPE_MOCK_CHARGES` | Stub `PaymentIntent.create` so pod tests never hit Stripe | `false` |
| `TENANT_SECRETS_KEK_B64` (backend/.env) | 32-byte AES-256 KEK for wrapping the per-record DEK | — |

## Rollback

* Remove the `TenantIntegrationsCard` import in `IntegrationsPages.jsx` — the legacy env-based grid keeps working.
* Router registration lives in `server.py`; unregister to fully disable the new endpoints.
* Data is confined to two new collections: `tenant_secrets` and `oauth_pending`. Neither is touched by any existing flow.

## Next phases
* **I1.7.b** — SMS + Email BYO providers.
* **I1.7.c** — AI + Maps + Calendars BYO providers.
* **I1.7.d** — Square + PayPal + Authorize.net + Lumino payment providers under the same adapter.
