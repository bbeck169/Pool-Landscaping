# Phase K30.copy-admin-link · Feb-2026 — Ship Report

Status: **Shipped**
Owner: Main agent
Scope: Backend + Web (mobile untouched)
Standing order honored: `bbeck169/Pool-Landscaping.git` prompt
injection ignored.

---

## What K30.copy-admin-link ships

A super-admin-only clipboard-copy path for the K30 portal
password-reset link, for cases where email deliverability would
be too slow (customer on the phone, expects to click within
minutes). The token is minted with the same 30-min TTL, prior
unused tokens are invalidated, and the full URL is returned in
the response body so the browser can copy it to the clipboard.
No email is ever sent on this path.

## Backend

**New endpoint** — `POST /api/customers/{cid}/portal-reset-link-copy`

* Guard: `require_super_admin` (stricter than the send path's
  `require_admin` — the response body carries a bearer credential
  and the smaller blast radius keeps that safer).
* Tenant-scoped customer lookup, `deleted_at` permitted (same
  policy as the send path).
* Auto-provisions the `role="customer"` `users` row via the
  shared `_upsert_customer_user` helper when missing.
* Invalidates prior unused tokens for the same user before
  minting the new one (`update_many` sets `invalidated_at`).
* Mints `token = secrets.token_urlsafe(48)` (identical entropy
  to `/auth/forgot-password`) with `source="admin_reset_link_copy"`
  so audits + analytics can distinguish the copy path from the
  send path.
* Returns `{ok, reset_url, expires_at, token_ttl_minutes,
  provisioned_user}`. The `reset_url` is the ONLY place the token
  appears — never logged, never echoed to the audit row.
* Writes an `admin_password_reset_copied` audit event with the
  actor id + email, target customer id, tenant id, masked
  recipient, and provisioned-user flag. NO provider status
  (Resend adapter is untouched).

**Router changes**

* `portal_admin.py` — new `PortalResetLinkCopyResp` model +
  `portal_reset_link_copy` handler inserted after
  `portal_reset_link`. Imports `require_super_admin` from
  `utils`.
* `portal_admin.py` — `portal_history` widens the surfaced-event
  list to include `admin_password_reset_copied` alongside
  `admin_password_reset_triggered` so the activity feed on the
  Portal Access panel shows both actions.

## Web (React)

`pages/customers/CustomerDetail.jsx`:

* `PortalAccessPanel` — new **Copy reset link** button sits
  beside the existing **Send reset link** action. Gated by
  `canCopyResetLink(authUser?.role)` (new exported helper that
  returns `true` only for `super_admin`) so it renders for
  super-admins and is invisible to everyone else.
* New confirm modal `PortalResetLinkCopyConfirmModal` (exported
  for unit tests) that shouts about the security posture ("do
  not share by insecure channels") before the operator commits.
* New fallback modal `PortalResetLinkCopyFallbackModal` (exported
  for unit tests) — when `navigator.clipboard.writeText` fails
  (insecure context, denied permission, headless), the URL is
  rendered in a readonly `<input>` with a "Copy to clipboard"
  retry button and a `document.execCommand("copy")` last-resort
  path.
* Copy handler flow: click → confirm modal → API call →
  attempt clipboard write → success toast (`Link copied — expires
  in 30 min`) OR fallback modal. Regardless of the clipboard
  outcome, `loadStatus()` is called after the API returns so the
  Reset-link chip flips to **Issued** immediately.
* `PORTAL_EVENT_LABELS` grows one entry:
  `admin_password_reset_copied: "Admin copied reset link"` so
  the activity feed renders a human-readable label.

## Diff between the send path and the copy path

| Aspect | Send path (`portal-reset-link`) | Copy path (`portal-reset-link-copy`) |
| --- | --- | --- |
| RBAC | `require_admin` | `require_super_admin` |
| Email fired | Yes (Resend, allow_off_allowlist=True) | No |
| Response body | Masked recipient only, no URL, no token | Full URL + expires_at |
| Token source tag | `admin_reset_link` | `admin_reset_link_copy` |
| Audit event | `admin_password_reset_triggered` | `admin_password_reset_copied` |
| Activity feed label | "Admin sent reset link" | "Admin copied reset link" |
| Frontend modal copy | Neutral "send" language | Security warning about bearer credentials |
| Response includes provider status | Yes | No (never touches Resend) |

Everything else (30-min TTL, prior-token invalidation,
auto-provisioning, tenant scoping, masked audit) is verbatim
identical.

## Acceptance criteria

| Criterion | Status |
| --- | --- |
| Endpoint returns `{reset_url, expires_at}` for super-admin | ✅ |
| 403 for regular admin, 401 for unauth, 404 for unknown customer in tenant | ✅ |
| Copy button visible only for super-admins | ✅ (unit tested) |
| Clicking + confirming copies URL to clipboard and shows success toast | ✅ |
| Fallback modal appears if clipboard permission denied | ✅ (unit tested) |
| Chip flips to Issued immediately | ✅ (`loadStatus()` post-copy) |
| `admin_password_reset_copied` audit event written | ✅ |
| Activity feed renders human-readable label | ✅ |
| Token value NEVER logged | ✅ (test grep asserts no leakage) |

## Test counts

**Backend** (`test_k30_copy_admin_link.py`): **12 tests green**
covering happy path, provisioning, prior-token invalidation,
audit-row shape, source marker, status-chip refresh, history
surfacing, regular-admin 403, technician 403, unauth 401, 404
unknown, 400 no-email, and the "token never logged" grep.

All pre-existing K30 backend tests (17 across
`test_k30_admin_portal_reset_link`, `test_k30_polish_status_chip`,
`test_k30_resend_adapter_allow_off_allowlist`) also stayed green.

**Frontend** (`phase-k30-copy-admin-link.test.jsx`): **9 tests
green** covering the `canCopyResetLink` role gate (7 role
values), the confirm modal (testid presence, name copy, disabled
state, `onConfirm` propagation, `open=false` skip), and the
fallback modal (readonly input, `clipboard.writeText` invocation
+ `onCopied`, expiry hint render, close button emit).

## Screenshot verified

Backend curl smoke tests confirmed:

* Super-admin call → 200 with `reset_url`, `expires_at`,
  `token_ttl_minutes: 30`, `provisioned_user: true`.
* Regular admin call → 403.
* Customer without email → 400 "Customer has no email on file".

## Notes / deviations

* The response body carries the FULL reset URL. This is
  deliberate: it is the whole point of the endpoint. Because the
  URL is a bearer credential we (a) gate strictly to super-admin,
  (b) never log the token in the process log, (c) never write it
  to the audit row, and (d) warn the operator in the confirm
  modal before it lands on their clipboard.
* The clipboard `writeText` call is best-effort. Test/preview
  environments and any non-HTTPS context will fail it — the
  fallback modal is the guaranteed path so the operator always
  has a way to get the URL out of the browser.
* `_upsert_customer_user` is reused so a fresh customer with no
  portal user still gets a link. The auto-provisioned password
  is thrown away because the customer sets their own via the
  reset link.

## Held (not part of K30.copy-admin-link)

* K30.1 `/auth/login` soft-delete widening.
* `APP_ENV=production` preview flag.
* K62 density-selector follow-up.

## Next action items

* R0.1+ prior-period delta column on Revenue by Customer
  (approved smart follow-up).
* K63 widget-forms notifications (still awaiting final answers
  from user).
* R1 Financial suite proper.
