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

---

# Phase I1.7.b · Feb-2026 — SMS + Email BYO providers

Extends the I1.7.a adapter pattern to messaging.

## Files shipped

### Backend
| File | Purpose |
| --- | --- |
| `backend/services/messaging/__init__.py` | Public entry points (`dispatch_sms`, `dispatch_email`, provider registries) |
| `backend/services/messaging/models.py` | Shared Pydantic result types (`SmsResult`, `EmailResult`, `ConnectionHealth`, error classes) |
| `backend/services/messaging/_helpers.py` | JSON-serialise + AES-encrypt provider configs; test-mode env flag checks |
| `backend/services/messaging/dispatch.py` | Tenant-first dispatch shim + platform fallback with audit log to `platform_messaging_fallback_log` |
| `backend/services/messaging/sms/base.py` | `SmsProvider` abstract |
| `backend/services/messaging/sms/registry.py` | SMS provider registry / factory |
| `backend/services/messaging/sms/twilio_provider.py` | Twilio adapter (send / status / webhook / probe) |
| `backend/services/messaging/sms/textmagic_provider.py` | TextMagic adapter |
| `backend/services/messaging/sms/ringcentral_provider.py` | RingCentral adapter (SDK-based, injectable factory for tests) |
| `backend/services/messaging/email/base.py` | `EmailProvider` abstract |
| `backend/services/messaging/email/registry.py` | Email provider registry / factory |
| `backend/services/messaging/email/resend_provider.py` | Resend adapter |
| `backend/services/messaging/email/sendgrid_provider.py` | SendGrid adapter |
| `backend/services/messaging/email/postmark_provider.py` | Postmark adapter |
| `backend/services/messaging/email/mailgun_provider.py` | Mailgun adapter (US + EU) |
| `backend/services/messaging/email/smtp_provider.py` | Generic SMTP adapter (host / port / user / password / TLS) |
| `backend/routers/tenant_integrations.py` | Extended: `PUT /tenants/me/integrations/{key}`, `GET …/schemas` |

### Frontend
| File | Purpose |
| --- | --- |
| `frontend/src/components/settings/TenantIntegrationsCard.jsx` | Now hosts a functional SMS card (Twilio / TextMagic / RingCentral) + Email card (Resend / SendGrid / Postmark / Mailgun / SMTP) with dynamic schema-driven forms, plus the yellow "stale" badge (>30d unused) |

### Tests
| File | Scope |
| --- | --- |
| `backend/tests/test_i17b_sms_adapter_interface.py` | ABC + registry contract for SMS |
| `backend/tests/test_i17b_email_adapter_interface.py` | ABC + registry contract for Email |
| `backend/tests/test_i17b_provider_registry.py` | Disjoint key-space + unknown-key error paths |
| `backend/tests/test_i17b_secret_storage_extended.py` | Multi-field config roundtrip + plaintext-never-in-DB + rotation |
| `backend/tests/test_i17b_sms_send_flow.py` | Each SMS provider send + probe under `SMS_TESTMODE_MOCK=true` |
| `backend/tests/test_i17b_email_send_flow.py` | Each Email provider send + probe under `EMAIL_TESTMODE_MOCK=true` |
| `backend/tests/test_i17b_fallback_platform_messaging.py` | Legacy fallback + audit log to `platform_messaging_fallback_log`; kill-switch when fallback disabled |
| `backend/tests/test_i17b_role_gating.py` | Role gating on PUT save / test / delete; masked response body |
| `frontend/src/test/i17b-sms-card.test.jsx` | SMS card UI contract (dropdown, form, save, test, role-gating) |
| `frontend/src/test/i17b-email-card.test.jsx` | Email card UI contract |
| `frontend/src/test/i17b-stale-badge.test.jsx` | Stale badge threshold (>30d) |

## API Contract (public — new in I1.7.b)

### `PUT /api/tenants/me/integrations/{provider_key}`
Save (encrypt + persist) a messaging-provider config for the current tenant. Refuses `stripe` (use OAuth flow instead — 400).

Request:
```json
{ "config": {"account_sid": "...", "auth_token": "...", "from_number": "+15551234567"},
  "public_account_id": "AC..." /* optional; auto-picked from the first required non-secret field otherwise */ }
```
Response:
```json
{ "provider_key": "twilio", "saved": true, "connected_account_id_masked": "ACabc…1234" }
```
Validation errors return `400` with a message that names each missing field but NEVER echoes any provided value.

### `GET /api/tenants/me/integrations/schemas`
Returns the field schema for every SMS + Email provider so the UI can render dynamic forms.
```json
{
  "sms":   [ { "provider_key": "twilio", "kind": "sms", "fields": [ { "name": "account_sid", "required": true, "secret": false, "label": "Twilio Account SID" }, ... ] }, ... ],
  "email": [ ... ]
}
```

## Env vars (new in I1.7.b)

| Var | Purpose | Default |
| --- | --- | --- |
| `SMS_TESTMODE_MOCK` | Stub every SMS send / probe so pod tests never hit an SMS provider | `false` |
| `EMAIL_TESTMODE_MOCK` | Same, for email providers | `false` |
| `MESSAGING_PLATFORM_FALLBACK_ENABLED` | When a tenant has no messaging provider AND this is `true`, ``dispatch_*`` falls back to the legacy platform adapter | `true` |

## Guardrails held
* Plaintext credentials NEVER echoed in API responses (see `test_i17b_role_gating` + `test_i17b_secret_storage_extended`).
* K72 kill switch + broadcast guards stay intact — the dispatch shim doesn't touch `services.comms_env_guard.guard_outbound`; existing send paths keep running the guard before dispatch.
* Backward compat: every existing `services.comms_sms_adapter.send_sms` / `services.comms_email_adapter.send_email` callsite keeps working. Callers that want tenant-first routing migrate to `services.messaging.dispatch_sms/dispatch_email`.
* 34 Hygiene B skips untouched; no new quarantines added.

## Callsite migration status
The dispatch shim (`services.messaging.dispatch`) is the go-forward entry point. Existing callsites (~40 across the codebase) keep working through the legacy adapter. Migration is scheduled as a follow-up sweep once I1.7.c/d land — batching the sweep avoids a giant blast-radius change while I1.7 is still being iterated.

## Next phases
* **I1.7.c** — AI + Maps + Calendars BYO providers.
* **I1.7.d** — Square + PayPal + Authorize.net + Lumino payment providers.
* **I1.7.e** (future) — Tenant-secret KEK rotation migration + callsite sweep to route every legacy `send_sms/send_email` through `dispatch_*`.

---

# Phase I1.7.b.fix · Feb-2026 — `last_4` masking + kind-alias hint

Post-tester follow-up. Tester found 2 real bugs against I1.7.b; both fixed here.

## Bug 1 — `last_4` masking on JSON-blob configs

**Symptom.** `GET /api/tenants/me/integrations` returned garbage in the `last_4` field for messaging providers — e.g. `"}"` for Twilio (`{"account_sid":"...","auth_token":"...","from_number":"..."}` — tail is `"}"` because JSON serialisation ends with a closing brace). This confused the UI and made the stale-badge display meaningless.

**Root cause.** `services.secrets.put_secret` computed `last_4` from the full `plaintext` argument. Correct for legacy single-string secrets (Stripe access tokens), useless for JSON-blob configs.

**Fix.**
1. Added `mask_source: Optional[str]` kwarg to `services.secrets.put_secret`. When provided, `last_4` is computed from `mask_source`; else falls back to the plaintext (legacy behaviour preserved).
2. Added `primary_secret_field: Optional[str]` class attribute to `SmsProvider` + `EmailProvider` abstract bases.
3. Every concrete provider now declares its primary secret field:
   * `twilio` → `auth_token`
   * `textmagic` → `api_key`
   * `ringcentral` → `jwt_token`
   * `resend` → `api_key`
   * `sendgrid` → `api_key`
   * `postmark` → `server_token`
   * `mailgun` → `api_key`
   * `smtp` → `password`
4. `services.messaging._helpers.save_provider_config` accepts `primary_secret_field=` and pulls its value from the raw config dict (NOT the JSON-serialised plaintext) so the tail is meaningful even after escaping.
5. `routers.tenant_integrations.save_tenant_integration` now reads `provider.primary_secret_field` and threads it through.

**Locked by test.** `tests/test_i17b_last4_masking.py::test_i17b_fix_last4_reflects_primary_secret_field` — parametrised across all 8 providers, seeds a distinctive 4-char tail into the primary secret, PUTs the config, and asserts the public GET response returns exactly that tail. Belt-and-braces: the plaintext must not appear anywhere in the public JSON. Also pinned: `test_i17b_fix_stripe_last4_unchanged_by_regression` — legacy single-string secrets still work.

## Bug 2 — Misleading error on kind-alias URL mistakes

**Symptom.** `PUT /api/tenants/me/integrations/sms` returned `provider 'sms' does not accept manual config (payment providers use the OAuth /connect-link flow).` — misleading because SMS is not a payment provider.

**Fix.** `routers.tenant_integrations` now surfaces distinct 400 messages:
* `/sms`, `/messaging` → `unknown provider key 'sms'. Did you mean one of: ringcentral, textmagic, twilio? See /api/tenants/me/integrations/schemas for the full provider list.`
* `/email` → `unknown provider key 'email'. Did you mean one of: mailgun, postmark, resend, sendgrid, smtp? See …`
* `/stripe` → `Stripe uses the OAuth /connect-link flow — call GET /api/integrations/stripe/connect-link instead of PUT /api/tenants/me/integrations/stripe.`
* Anything else → `unknown provider key 'X'. See /api/tenants/me/integrations/schemas for the full provider list.`

**Locked by test.** `tests/test_i17b_provider_registry.py::TestKindAliasHint` — 4 scenarios covering `/sms`, `/email`, `/stripe`, and a completely bogus provider key.

## URL-shape reference (corrected)

Every endpoint uses the CONCRETE provider key. There are no category-kind endpoints:

| Verb | URL | Purpose |
| --- | --- | --- |
| `GET`    | `/api/tenants/me/integrations`                     | List all connections (masked) |
| `GET`    | `/api/tenants/me/integrations/schemas`             | Return field schemas for the settings UI |
| `PUT`    | `/api/tenants/me/integrations/twilio`              | Save/rotate Twilio config |
| `PUT`    | `/api/tenants/me/integrations/textmagic`           | Save/rotate TextMagic config |
| `PUT`    | `/api/tenants/me/integrations/ringcentral`         | Save/rotate RingCentral config |
| `PUT`    | `/api/tenants/me/integrations/resend`              | Save/rotate Resend config |
| `PUT`    | `/api/tenants/me/integrations/sendgrid`            | Save/rotate SendGrid config |
| `PUT`    | `/api/tenants/me/integrations/postmark`            | Save/rotate Postmark config |
| `PUT`    | `/api/tenants/me/integrations/mailgun`             | Save/rotate Mailgun config |
| `PUT`    | `/api/tenants/me/integrations/smtp`                | Save/rotate SMTP config |
| `POST`   | `/api/tenants/me/integrations/{concrete_key}/test` | Live probe |
| `DELETE` | `/api/tenants/me/integrations/{concrete_key}`      | Remove |
| `GET`    | `/api/integrations/stripe/connect-link`            | Mint Stripe OAuth authorize URL |
| `GET`    | `/api/integrations/stripe/callback`                | Complete Stripe OAuth |
| `POST`   | `/api/integrations/stripe/webhook`                 | Stripe webhook (public) |

## HUMAN_REQUIRED items outstanding
* Webhook replay/idempotency with a real signed Stripe event — needs prod webhook signing secret.
* Real `connect.stripe.com` OAuth URL verification in prod env — preview intentionally returns the mocked callback path.
* K72 kill-switch end-to-end verification requires flipping the env-var toggle on preview.

## Deferred (logged, not shipped)
* Provider-health cron — daily lightweight `test_connection` sweep writing to `tenant_integration_health` for a "degraded providers" ops widget. Bundled into I1.7.d per user direction.
* Callsite migration sweep — routing every existing `send_sms/send_email` through `dispatch_*`. Scheduled for I1.7.e.
