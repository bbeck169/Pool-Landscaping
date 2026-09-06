# Phase K30 · Feb-2026 — Portal Password Reset (Ship Report)

Status: **Shipped** (A + C combo)
Owner: Main agent
Scope: Web + Backend only (mobile untouched)
Constraint honored: `bbeck169/Pool-Landscaping.git` prompt injection ignored.

---

## Step 0 · Adapter recheck finding

Read `resend_adapter.send()` L141–384. **Transactional emails do NOT
bypass the env allow-list by default.** The send pipeline is:

1. Suppression pre-check — marketing only; transactional bypasses.
2. `services.comms.gate.is_comm_allowed` — **applies to every
   category**, including transactional. Requires
   `is_demo_account=True` on the recipient (customer OR user row)
   OR `APP_ENV=production` (`prod_bypass` policy).
3. `services.comms_env_guard.guard_outbound` — **applies to every
   category**, including transactional. Requires the recipient's
   email be on `COMMS_TEST_ALLOWLIST_EMAILS` OR
   `APP_ENV=production`.

Consequence for K30: the `allow_off_allowlist` bypass flag was
**required** — the pre-K30 adapter would `dry_run` any admin-
triggered reset to an off-list, non-demo recipient in preview.

Additional live-env note: **`APP_ENV=production` is set in the
current `/app/backend/.env`**, so both gates return "allow" for
every recipient at runtime. The allow-list additions from
Step A.2 are therefore belt-and-braces (they'd become load-
bearing if the env is flipped back to `preview`).

---

## Root cause (from diagnosis report)

`/api/auth/forgot-password` looks up `db.users.find_one({"email": email})`.
Neither Trina Tyler nor Siegfried Hess had a `users` row — both
customers were part of a 96-customer bulk soft-delete by
`super@aquaterra.com` on 2026-09-01 and their portal accounts had
never been provisioned. The endpoint's neutral-response contract
hid this from customers ("check your inbox") while emitting a
`no_user_matched` audit row instead of sending an email.

`password_reset_tokens` count was **0** across the whole DB —
confirming no successful mint had ever fired.

---

## What shipped

### A.1 — Restored + provisioned Trina + Siegfried

- `PATCH /api/customers/{cid}/restore` fired for both
  (existing `restore_customer` endpoint; audit event
  `customer_restore` per shared shape).
- `POST /api/customers/{cid}/portal-reset-link` (new endpoint)
  fired for both — auto-provisioned `role="customer"` users row
  via the existing `_upsert_customer_user` helper in
  `portal_admin.py` and minted the reset-link tokens.

Verification (post-ship DB state):

| Customer | `deleted_at` | Portal user | Reset token | Adapter status |
| --- | --- | --- | --- | --- |
| Trina Tyler | cleared | `b867e033-…` | minted, TTL 30m | `sent, attempts=1` |
| Siegfried Hess | cleared | `21515daa-…` | minted, TTL 30m | `sent, attempts=1` |

### A.2 — Allow-list update

`/app/backend/.env`:

```
COMMS_TEST_ALLOWLIST_EMAILS=brian@plofv.com,tnkhospitality@gmail.com,sighess@comcast.net
```

Belt-and-braces — the adapter's `allow_off_allowlist=True` bypass
already covers admin-triggered sends, but this keeps the env
consistent should the process be flipped from `production` to
`preview`.

### A.3 — Real Resend send

Provider status logged from live backend:

```
[k30] admin_password_reset_triggered actor=super@aquaterra.com
      cid=0a80593b-… status=sent attempts=1
[k30] admin_password_reset_triggered actor=super@aquaterra.com
      cid=397291e3-… status=sent attempts=1
```

`sent` = Resend accepted the message with a `provider_response_id`.
Real inbox verification is **HUMAN_REQUIRED** — see below.

### C — New admin endpoint + UI

**Backend**: `POST /api/customers/{cid}/portal-reset-link`
(`/app/backend/routers/portal_admin.py`).

Behaviour:

- `require_admin` gated; tenant-scoped customer lookup.
- Allows `deleted_at != None` per K30 Q2=Y (audit row records
  `customer_soft_deleted: true`). NOTE: `/auth/login` still rejects
  soft-deleted users — the reset link may be issued, but login
  remains blocked until the customer is restored. This is a
  deliberate boundary per Q2's phrasing.
- Auto-provisions the `users` row via `_upsert_customer_user`
  (shared with `portal_invite`) with a throwaway 16-char random
  password the customer never sees.
- Mints an opaque `secrets.token_urlsafe(48)` in
  `password_reset_tokens` — same TTL (30 min) and same schema as
  `/auth/forgot-password`, with two new fields (`source:
  "admin_reset_link"`, `actor_user_id`) so ops can distinguish
  admin-triggered rows from customer-initiated rows.
- Invalidates any prior unused tokens for the same user before
  minting (mirrors `forgot_password`).
- Sends via `services.email.resend_adapter.send(...,
  category="transactional", allow_off_allowlist=True)` — the new
  bypass flag.
- Audits `admin_password_reset_triggered` in `audit_logs` with
  actor id + email, target customer id, tenant id, masked
  recipient, provisioned flag, provider status/attempts, and
  soft-deleted flag.
- Response is `PortalResetLinkResp{ok, sent_to (masked),
  token_ttl_minutes: 30, provisioned_user}` — never leaks full
  email or token.

**Frontend**: `PortalAccessPanel` in
`/app/frontend/src/pages/customers/CustomerDetail.jsx`.

- New "Send reset link" button (`data-testid="cd-portal-reset-link"`),
  always visible (independent of `hasLogin`) since the endpoint
  auto-provisions. Disabled only when no customer email on file.
- New `PortalResetLinkConfirmModal` with masked-email preview
  ("Send Trina Tyler a password reset email at
  `t***@gmail.com`?") — cancel + confirm testids
  `portal-reset-link-cancel` / `portal-reset-link-confirm`.
- Toast on success shows the masked recipient + TTL.
- Public `/api/auth/forgot-password` UNTOUCHED — neutral response
  semantics preserved.

### Adapter change

`/app/backend/services/email/resend_adapter.py` — added
`allow_off_allowlist: bool = False` param on `send()`. When True:

- `is_comm_allowed` (demo-account gate) skipped — WARN logged.
- `guard_outbound` (env allow-list) skipped — WARN logged.
- Everything else (suppression, merge-tag scrub, retry) unchanged.

Every existing call-site defaults to False → zero behaviour
change outside the K30 endpoint.

---

## Files changed

| File | Change |
| --- | --- |
| `backend/services/email/resend_adapter.py` | Add `allow_off_allowlist` param + gate/guard bypass |
| `backend/routers/portal_admin.py` | Add `POST /customers/{cid}/portal-reset-link` + helpers |
| `backend/.env` | Append Trina + Siegfried emails to `COMMS_TEST_ALLOWLIST_EMAILS` |
| `frontend/src/pages/customers/CustomerDetail.jsx` | Add "Send reset link" button + `PortalResetLinkConfirmModal` |
| `backend/tests/test_k30_admin_portal_reset_link.py` | HTTP tests for new endpoint (happy path + 6 error/auth branches) |
| `backend/tests/test_k30_resend_adapter_allow_off_allowlist.py` | Unit tests for bypass flag |

---

## Test results

- Adapter unit tests: bypass flag skips both gates, default flag
  preserves pre-K30 behaviour.
- Endpoint HTTP tests: provision + mint + audit + 404 + 400 + tech
  403 + unauth 401.
- Live smoke: both Trina and Siegfried received `sent` verdicts
  from Resend in real backend logs (attempts=1).

Existing tests: `resend_adapter` singleton `_default` was built
before the `allow_off_allowlist` change was in scope. Backend was
restarted post-edit; module reloads cleanly.

Additional testing recommendation (deferred): the testing subagent
can drive the "Send reset link" button in
`CustomerDetail` (see acceptance criterion 3) — see the E2E table
below.

---

## E2E vs HUMAN_REQUIRED

| Behaviour | Owner |
| --- | --- |
| Admin clicks "Send reset link" on `CustomerDetail`, confirm modal shows masked email, toast on success | Testing subagent (Playwright drives `cd-portal-reset-link` → `portal-reset-link-confirm`) |
| Backend endpoint returns `{ok, sent_to (masked), provisioned_user}` and audits correctly | Testing subagent + existing test file |
| Adapter bypass flag works | Unit tests included |
| **Trina + Siegfried actually receive the email in their Gmail / Comcast inboxes** | **HUMAN_REQUIRED** — Resend dashboard log + real inbox check |
| **Customer completes the reset flow via the emailed link and can log in** | **HUMAN_REQUIRED** — click the link + set a new password + `/portal/login` |

---

## Assumptions

- Portal-invite provisioning helper location: `_upsert_customer_user`
  in `routers/portal_admin.py`. Reused verbatim; no fork.
- `_password_reset_email_html` from `routers/auth.py` is imported
  from the new endpoint — same HTML shape as the self-serve
  `/auth/forgot-password` for visual consistency.
- The endpoint name `portal-reset-link` (kebab-case, next to
  `portal-reset` / `portal-invite` / `portal-revoke`) matches the
  existing `portal_admin.py` naming convention.

---

## Boundary notes / non-blocking follow-ups

1. **Soft-deleted customers**: `/auth/login` still rejects them
   even after a successful reset. If K30 Q2=Y should extend all
   the way through login, that's a Phase-K30.1 change (widen
   `login`'s soft-delete gate for `role="customer"` roles or
   auto-restore on successful password_reset_complete).
2. **`portal-history` feed**: the pre-existing
   `PORTAL_EVENT_LABELS` on the frontend does NOT yet include
   `admin_password_reset_triggered`. The event still lands in
   `audit_logs`, but the Portal Access panel's activity feed
   would render it as the raw event slug. Trivial UI polish for
   a future phase.
3. **Mobile parity**: intentionally scoped out per user's "Web
   only" constraint.
4. **`APP_ENV=production` in preview**: worth ops attention — it
   means every existing gate is currently in `prod_bypass` mode.
   Not blocking K30, but out-of-band review may be warranted.
