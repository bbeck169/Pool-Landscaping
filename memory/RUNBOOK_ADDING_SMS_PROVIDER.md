# Runbook · Adding an SMS Provider · Phase I1.7.b

Applies to tenant admins connecting Twilio, TextMagic, or RingCentral. Reference for on-call + support.

## Preconditions
* `TENANT_SECRETS_KEK_B64` populated in `backend/.env` (see I1.7.a runbook).
* `MESSAGING_PLATFORM_FALLBACK_ENABLED=true` while at least one tenant is still on the platform default RingCentral.

## Path
1. Sign in as `role ∈ {admin, super_admin}`.
2. Settings → Integrations.
3. In the **SMS provider** card, pick a provider from the dropdown:
   * **Twilio** — Account SID + Auth Token + From number (E.164). Optional: Messaging Service SID, delivery-status webhook URL.
   * **TextMagic** — username + API key + optional From number.
   * **RingCentral** — server URL, client id / secret, JWT, from number.
4. Fill the form and click **Save**. On success the card flips to **Connected · <provider>** with a masked account id.
5. Click **Test connection** — the backend runs a lightweight probe (Twilio `Account.retrieve`, TextMagic `user.get`, RingCentral `extension.get`).
6. All subsequent SMS through `services.messaging.dispatch_sms` now runs under the tenant's provider.

## Pod / dev path (no outbound SMS)
Set `SMS_TESTMODE_MOCK=true` in `backend/.env`. Every send + probe returns `SmsResult { id: "SM_test_...", status: "queued" }` without a network call.

## Rotation
Save with a new value on top of the existing row — `put_secret` overwrites atomically. The prior plaintext is unrecoverable.

## Disconnect
Admin clicks **Disconnect** → confirms → `DELETE /api/tenants/me/integrations/{provider_key}`. Row removed. Next `dispatch_sms` call routes to platform default (audited in `platform_messaging_fallback_log`).

## Failure modes
| Symptom | Cause | Fix |
| --- | --- | --- |
| Save returns 400 `missing required fields: X, Y` | Form has empty required fields | Fill fields listed in the error message |
| Save succeeds, Test connection returns `ok:false · Twilio probe HTTP 401` | Wrong Account SID + Auth Token pair | Rotate — re-enter the correct values from Twilio dashboard |
| Test connection returns `ok:false · Twilio probe HTTP 429` | Rate-limited | Wait and retry |
| Test connection returns `ok:false · Twilio probe failed: ConnectError` | Outbound network blocked in this pod | Flip `SMS_TESTMODE_MOCK=true` for dev; investigate networking for production |
| Send succeeds but no message arrives | From number not verified for MMS OR trial account with unverified destination | Verify From number in Twilio; upgrade from trial |

## Audit
* Every fallback dispatch → `platform_messaging_fallback_log` (`tenant_id`, `kind`, `reason`, `at`).
* Every non-2xx provider response → `tenant_secrets.error_log` (ring-buffered at 20 entries per row).

## Health check
```
$ curl -X PUT $API/api/tenants/me/integrations/twilio \
    -H "Authorization: Bearer $TOK" \
    -H "Content-Type: application/json" \
    -d '{"config": {"account_sid":"AC...","auth_token":"...","from_number":"+15551234567"}}'
$ curl -X POST $API/api/tenants/me/integrations/twilio/test -H "Authorization: Bearer $TOK"
```
