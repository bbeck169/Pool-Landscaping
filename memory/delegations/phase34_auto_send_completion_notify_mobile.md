## Delegation Brief · Phase 34 · Task U — Auto-send on job completion (mobile)

**From:** Backend team · Feb 2026 · Task U
**To:** e1_expo_frontend_dev
**Priority:** P1
**Language:** English only.
**Status:** Backend shipped. Mobile parity outstanding.

---

### What changed on backend

When a technician marks a service report submitted (endpoint
`POST /api/jobs/{jid}/service-report/submit`), the customer-facing
"service completed" email AND SMS now fire **automatically** — no
opt-in checkbox, no prompt.

Details (see `/app/backend/routers/service_reports.py::submit_service_report`
tail block):

- Both channels fire via the guarded adapters (Task L) — preview
  dry-runs everyone except the Brian allow-list; production sends
  live once `APP_ENV=production` and the Resend key rotates.
- **Idempotent:** if the same job's service report is submitted
  twice (double-tap), the second submission observes
  `customer_notified.email_sent_at` already stamped and skips both
  channels. Log line: `[task-u] skipped_idempotent`.
- **Tenant opt-out:** `settings.notifications.auto_send_completion`
  boolean (defaults `true`). If a tenant sets it to `false` the
  auto-fire is bypassed but everything else still works.
- **Legacy opt-out flags are ignored.** The backend no longer honours
  `also_notify_customer=false`, `send_email=false`, or `send_sms=false`
  in the completion payload. A WARN is logged if any old client still
  sends them so ops can spot stale mobile builds:
  `[task-u] legacy opt-out flag ignored on job=… tenant=…`
- Every completion writes a `customer_notified` block on the
  service-report doc for auditability:
  ```
  {
    "email_status": "sent" | "queued" | "dry_run" | "mocked" | "failed" | "skipped_idempotent" | "tenant_disabled",
    "email_sent_at": iso | null,
    "sms_status":   "sent" | ... | "no_phone" | ...,
    "sms_sent_at":  iso | null,
    "auto_send_completion_setting": bool
  }
  ```

### What we need from mobile

`/app/mobile/app/(tech)/job/[id]/complete.tsx` (or the equivalent
completion screen in the Expo tech UI):

1. **Remove** the "Send notification to customer?" prompt / opt-in
   checkbox from the completion flow. The customer will always be
   notified — the tech has no way to skip.
2. **Stop sending** legacy opt-out flags on the completion payload.
   If the current POST body includes `also_notify_customer` /
   `send_email` / `send_sms`, delete those fields.
3. Add a passive confirmation on the completion success screen:
   *"We've let {customer_name} know their service is complete."*
4. Nothing else changes — the backend does all the work.
5. If a tenant admin has disabled `settings.notifications.auto_send_completion`
   (rare — future feature), the confirmation copy should read:
   *"Marked complete. Customer notifications are disabled for this
   tenant."* (Backend returns this in the completion response as
   `customer_notified.auto_send_completion_setting=false` so the app
   can key on it.)

### Guardrails

- English-only.
- Do NOT ship a "customer suppress" checkbox as a shortcut. If a
  tenant wants to disable notifications the admin flips the tenant
  setting — the tech never gets that lever.
- Do NOT double-fire notifications by ALSO calling any legacy
  `/api/notifications/send-completion` route from mobile. The
  backend does it automatically.

### Reference

- Backend: `/app/backend/routers/service_reports.py::submit_service_report`
  (search `[task-u]` for the audit block + logging).
- Backend logs: grep `[task-u] completion sms` after a completion
  to see the outcome.

### Deploy

- Mobile: OTA / EAS update. No native module changes.
