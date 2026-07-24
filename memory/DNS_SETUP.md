# DNS Setup Checklist — Pool & Landscaping of Vistancia

Post-rebrand cutover to `app.plofv.com` + `plofv.com`. All items below
require platform-level action outside `/app`. This document is a
handoff for the human operator; the agent does NOT touch DNS.

---

## 1. Custom subdomain (app hosting)

The React SPA + FastAPI backend currently run at:

```
https://poolscape-audit.preview.emergentagent.com
```

**Action**: point `app.plofv.com` at the platform ingress.

| Type   | Host           | Value                                                     | TTL  |
| ------ | -------------- | --------------------------------------------------------- | ---- |
| CNAME  | app.plofv.com  | `<TODO: platform ingress host to be filled by operator>`  | 300  |

After the CNAME resolves, add the same origin to:
- `backend/.env::ALLOWED_ORIGINS` (comma-separated)
- Backend CORS allowlist (auto-picks up from env; **already includes**
  `https://app.plofv.com` and `https://plofv.com` in the boot-time
  defaults — see `server.py::_origins` block)
- Resend webhook allowlist / signing config, if applicable.

---

## 2. Resend — verify `plofv.com`

**Action**: log in to Resend → Domains → **Add Domain** → `plofv.com`.

Once Resend issues the DNS record values, add them at the DNS
provider:

| Type   | Host              | Value                                                     | Notes                       |
| ------ | ----------------- | --------------------------------------------------------- | --------------------------- |
| TXT    | plofv.com         | `v=spf1 include:_spf.resend.com ~all`                     | SPF                         |
| TXT    | `<selector>._domainkey.plofv.com` | `<DKIM public key from Resend>`           | DKIM (Resend gives selector)|
| TXT    | _dmarc.plofv.com  | `v=DMARC1; p=none; rua=mailto:brian@plofv.com; ruf=mailto:brian@plofv.com; fo=1` | DMARC (monitor mode) |

Until Resend confirms `plofv.com` is verified, the app will:

* Attempt to send from `noreply@plofv.com` (the value written into
  `tenant.settings.email_sender.from_email` by the Phase 21 migration).
* Detect the domain is NOT in `RESEND_VERIFIED_DOMAINS` env
  (currently unset or `resend.dev`) and log a WARNING.
* **Fall back** to the currently-verified sender (`RESEND_FROM_ADDRESS`
  env / `onboarding@resend.dev`) so emails still deliver.

Once Resend confirms verification, set:

```
RESEND_VERIFIED_DOMAINS=plofv.com,resend.dev
```

in `backend/.env` and restart the backend — the WARN goes away and
emails will send from `noreply@plofv.com` immediately.

---

## 3. RingCentral webhook URLs

RingCentral push subscriptions currently target the emergentagent
preview host. Post-DNS cutover:

* Sign in to the RingCentral developer console.
* For each active subscription (call events, SMS events), update the
  `deliveryMode.address` to the new custom domain — likely:
  * `https://app.plofv.com/api/ringcentral/webhook/calls`
  * `https://app.plofv.com/api/ringcentral/webhook/sms`
* Confirm the subscription reflects the new URL and resumes delivering
  events.

If subscription URLs are not updated, RC will keep pushing events to
the old preview host until it becomes unreachable (which is fine — the
platform ingress will 502 and RC will retry from its own queue).

---

## 4. Google Business Profile

**Unchanged**. The GBP `place_id` remains the same. No DNS or URL
changes required.

---

## 5. Custom domain field (`tenants.custom_domain`)

After `app.plofv.com` is live and verified in the browser:

* Sign in as `super@aquaterra.com`.
* PATCH `/api/tenants/mine/brand` (or use the Settings UI) to set
  `custom_domain = "app.plofv.com"`.
* Set `settings.primary_app_domain = "https://app.plofv.com"` so
  outbound absolute-URL builders (invoice pay link, review request,
  magic login, unsubscribe) start using the new host.

The URL builder (`services/tenant_urls.py::resolve_primary_app_domain`)
picks up the change on the next request — no restart needed.

---

## 6. Verification checklist

- [ ] `app.plofv.com` resolves and serves the SPA.
- [ ] `curl -I https://app.plofv.com/api/health` returns 200.
- [ ] Login page at `https://app.plofv.com/login` accepts existing
      credentials.
- [ ] `plofv.com` domain shows **Verified** in Resend dashboard.
- [ ] Test-send from `noreply@plofv.com` lands in inbox (not spam).
- [ ] Backend log no longer shows the
      `[resend] plofv.com not verified — falling back to onboarding@resend.dev`
      warning.
- [ ] RingCentral subscription list points to `app.plofv.com` URLs.
- [ ] `tenants.custom_domain` = `app.plofv.com` in the DB.
