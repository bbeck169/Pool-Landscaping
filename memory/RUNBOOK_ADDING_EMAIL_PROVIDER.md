# Runbook · Adding an Email Provider · Phase I1.7.b

Applies to tenant admins connecting Resend, SendGrid, Postmark, Mailgun, or a custom SMTP server.

## Preconditions
Same as SMS runbook.

## Path
1. Sign in as `role ∈ {admin, super_admin}`.
2. Settings → Integrations.
3. In the **Email provider** card, pick a provider from the dropdown:
   * **Resend** — API key + verified From address. Optional: From display name, webhook signing secret.
   * **SendGrid** — API key + verified sender address. Optional: From display name, event-webhook verification key.
   * **Postmark** — Server API token + verified sender address. Optional: Message stream (default `outbound`).
   * **Mailgun** — API key + sending domain + From address. Optional: Region (`us` or `eu`), webhook signing key.
   * **SMTP** — host, port, username, password, From address. Optional: STARTTLS on/off, implicit SSL for port 465.
4. Fill the form and click **Save**.
5. Click **Test connection** — the backend runs a lightweight probe:
   * Resend → `domains.list`
   * SendGrid → `scopes.get`
   * Postmark → `server.get`
   * Mailgun → `domain.get`
   * SMTP → connect + login + NOOP + quit
6. All subsequent emails through `services.messaging.dispatch_email` now run under the tenant's provider.

## Pod / dev path
Set `EMAIL_TESTMODE_MOCK=true` in `backend/.env`. Every send + probe returns `EmailResult { id: "resend_test_...", status: "queued" }` without a network call.

## Failure modes
| Symptom | Cause | Fix |
| --- | --- | --- |
| Save returns 400 `missing required fields: X, Y` | Form has empty required fields | Fill fields listed in the error message |
| Test connection returns `ok:false · Resend probe HTTP 401` | Bad API key | Re-enter |
| Test connection returns `ok:false · Mailgun probe HTTP 404` | Wrong region or wrong sending domain | Flip `region` to `eu` if using EU account; confirm domain matches Mailgun dashboard |
| SMTP probe fails with `SMTPAuthenticationError` | Wrong username / password OR Google Workspace app-password not enabled | Generate an SMTP app password in the mail provider dashboard |
| SMTP probe fails with `SSLError` | TLS/SSL flags mismatched | Port 587 → `use_tls=true`, `use_ssl=false`. Port 465 → `use_tls=false`, `use_ssl=true`. |
| Send returns 200 but message never delivers | From address not verified | Verify sender in provider dashboard |

## Rotation + Disconnect
Same semantics as SMS.

## Audit
Same as SMS.

## Health check
```
$ curl -X PUT $API/api/tenants/me/integrations/resend \
    -H "Authorization: Bearer $TOK" \
    -H "Content-Type: application/json" \
    -d '{"config": {"api_key":"re_...","from_addr":"hello@example.com"}}'
$ curl -X POST $API/api/tenants/me/integrations/resend/test -H "Authorization: Bearer $TOK"
```
