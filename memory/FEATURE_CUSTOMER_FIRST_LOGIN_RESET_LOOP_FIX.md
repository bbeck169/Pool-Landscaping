# Feb-2026 · P0 · Customer first-login password-reset loop fix

## Root cause hypothesis

The forced-reset "modal" (mid-flow redirect to `/reset-password`) was
being emitted by `POST /api/auth/login` on **every** login where the
matched user row carried `must_change_password_on_next_login=true`.
The pre-fix fork check (`routers/auth.py`) had **no role gate and no
`has_ever_logged_in` gate**:

```python
# pre-fix (routers/auth.py ~L422)
if user.get("must_change_password_on_next_login"):
    payload = await _mint_temp_password_reset_token(user, ip)
    ...
    return payload
```

Two failure modes surfaced:

1. **Non-customer roles hit the customer temp-password UX.** If an
   admin/tech row picked up the flag (e.g., via
   `POST /users/{uid}/reset-password` in `admin_users.py:266`), the
   staff login was forcibly punted into the customer reset flow
   even though the reset UI is designed for portal customers.
2. **Post-reset stale flag = infinite loop.** The reset endpoint
   (`_apply_new_password` at `routers/auth.py:868`) correctly flipped
   `must_change_password_on_next_login` to False for the row it
   was resetting — **but did NOT stamp `has_ever_logged_in=True`.**
   If a downstream write, admin re-rotation, or a concurrent
   modification later re-armed the flag (or if the flag was set on
   a customer who had already completed their first login via some
   other path), the customer would be forced through the reset
   UX again on every subsequent login. Reset → success → back to
   login → fork → reset → success → back to login → … (loop).

Compounding factors:

- The reset endpoint `POST /api/auth/reset-password` returned a bare
  `{"ok": true, "message": "Please sign in."}`. Customers had to
  re-enter their credentials — a UX regression on top of the loop.
- No audit trail for the "stale flag on already-logged-in customer"
  anomaly meant ops couldn't detect that the state had drifted.

## Trigger-condition matrix (post-fix)

The reset UX fires only when **ALL** of the following are true. Any
deviation short-circuits the fork.

| Role | `must_change_password_on_next_login` | `has_ever_logged_in` | Behavior |
|---|---|---|---|
| `customer` | `True` | `False` (or missing) | **FORK** → `password_reset_required` |
| `customer` | `True` | `True` | Normal login + `customer.suspicious_forced_reset_flag` audit |
| `customer` | `False` | any | Normal login |
| `admin` / `technician` / `super_admin` | `True` | any | Normal login (flag ignored, no audit) |
| any | `False` | any | Normal login |

Backend enforcement: `_should_fork_temp_password_flow` in
`routers/auth.py`. Frontend defense-in-depth: `Login.jsx` inspects the
`role` field on the `password_reset_required` payload and refuses to
redirect if it's anything other than `customer` — the FE cannot
render the customer reset UI for a non-customer even if the server
were to (buggily) emit that shape.

## Post-reset flow (option `a` — auto-login)

```
┌─────────────────────────────────────────────────────────────────┐
│ Customer signs in with temp password                             │
│ → POST /api/auth/login                                           │
│   ↳ role=customer, flag=True, has_ever_logged_in=False           │
│   ↳ backend mints 15-min reset_token (source=temp_password_login)│
│   ↳ returns {status: "password_reset_required", role: "customer",│
│              reset_token, user_id, token_ttl_minutes: 15}        │
│ ↓                                                                │
│ FE redirects to /reset-password?token=…&flow=temp_password       │
│ ↓                                                                │
│ Customer submits new password                                    │
│ → POST /api/auth/reset-password                                  │
│   ↳ _stamp_first_access (writes portal_first_login_at denorm)    │
│   ↳ _apply_new_password:                                         │
│      • must_change_password_on_next_login = False                │
│      • has_ever_logged_in = True                                 │
│      • first_password_reset_at = <utcnow>                        │
│      • password_customer_set_at / password_updated_at            │
│   ↳ token invalidated (single-use)                               │
│   ↳ audit_logs: password_reset_complete +                        │
│                  customer.first_login_password_reset             │
│   ↳ mints FRESH access_token via auth_response                   │
│   ↳ returns {ok, message, auto_login: true, access_token,        │
│              token_type: "bearer", user: {...}}                  │
│ ↓                                                                │
│ FE (ResetPassword.jsx):                                          │
│   • applyResetAutoLogin(access_token, user) → persist            │
│   • navigate("/portal/home", {replace: true})                    │
│ ↓                                                                │
│ Customer is signed in on the portal home page.                   │
│ NO second login prompt. NO reset modal on next session.          │
└─────────────────────────────────────────────────────────────────┘
```

## Migration endpoint contract

```
POST /api/admin/migrations/clear-stale-forced-reset-flags
Authorization: Bearer <super_admin JWT>
```

| Param | Type | Default | Notes |
|---|---|---|---|
| `dry_run` | `bool` | `true` | Safety-first. Set false to write. |
| `tenant_id` | `str?` | `null` | Optional; omit to scan all tenants. |

Response envelope (verified live on preview):

```json
{
  "ok": true,
  "dry_run": true,
  "tenant_id": null,
  "scanned": 0,
  "flipped": 0,
  "skipped": 0,
  "errors": 0
}
```

Scope: `role=customer` **only**. Non-customer rows are never touched
by this migration.

### Sample curl (verified live)

```bash
API=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d= -f2)/api
SA=$(curl -s -X POST "$API/auth/login" \
   -H "Content-Type: application/json" \
   -d '{"email":"super@aquaterra.com","password":"password123"}' \
   | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Dry-run first — see what we'd flip.
curl -s -X POST "$API/admin/migrations/clear-stale-forced-reset-flags" \
   -H "Authorization: Bearer $SA" -H "Content-Type: application/json" \
   -d '{"dry_run":true}' | python3 -m json.tool

# Wet-run — flips the flags.
curl -s -X POST "$API/admin/migrations/clear-stale-forced-reset-flags" \
   -H "Authorization: Bearer $SA" -H "Content-Type: application/json" \
   -d '{"dry_run":false}' | python3 -m json.tool

# Optional — target a single tenant.
curl -s -X POST "$API/admin/migrations/clear-stale-forced-reset-flags" \
   -H "Authorization: Bearer $SA" -H "Content-Type: application/json" \
   -d '{"dry_run":false,"tenant_id":"<tid>"}' | python3 -m json.tool
```

Role gate spot-check (verified live):

```bash
# admin JWT → 403
ADMIN=$(curl -s -X POST "$API/auth/login" \
   -H "Content-Type: application/json" \
   -d '{"email":"admin@aquaterra.com","password":"password123"}' \
   | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
   -X POST "$API/admin/migrations/clear-stale-forced-reset-flags" \
   -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
   -d '{"dry_run":true}'
# → HTTP 403
```

## Backfill runbook (prod)

1. Deploy the fix to production (Save-to-GitHub → redeploy).
2. Log in to prod as super_admin.
3. **DRY-RUN FIRST.** POST the endpoint with `{"dry_run": true}` and
   read `scanned`. Expected: some non-zero number if legacy customers
   were exposed to the pre-fix loop; zero if the population is clean.
4. Cross-check `scanned` against the ops audit stream:
   `grep 'login_password_reset_required' <auth-audit-log>` — same
   customer emails should be showing up on repeated logins in the
   time window before the fix shipped. If the counts feel wildly
   off, stop and investigate (there may be another write path
   re-arming the flag we haven't accounted for).
5. **WET-RUN.** POST the endpoint with `{"dry_run": false}`. Verify
   `flipped == scanned_from_dry_run` (or explicitly note skipped/
   error counts).
6. Idempotency check — re-run wet with the same payload. Expected:
   `scanned=0, flipped=0`. Any non-zero on the second run means a
   concurrent write is re-arming the flag — pause and investigate.
7. Monitor `audit_logs` for `customer.suspicious_forced_reset_flag`
   over the next 24h. Any new writes indicate a source-of-flag we
   haven't shut down yet.

## Files touched

**Backend**

- `routers/auth.py` — three edits:
  * `_mint_temp_password_reset_token` — payload now includes `role`
    for the FE defense-in-depth gate.
  * `_should_fork_temp_password_flow` (new helper) +
    `_audit_suspicious_forced_reset_flag` (new helper) — role +
    `has_ever_logged_in` gate; anomaly audit.
  * `/auth/login` and `/auth/login/select-account` fork branches —
    routed through the new gate.
  * `_apply_new_password` — stamps `has_ever_logged_in=True`,
    `first_password_reset_at` (only on first reset — idempotent),
    and `first_access_at` (only when missing).
  * `/auth/reset-password` — when the consumed token has
    `source=temp_password_login` AND the target user is a customer,
    auto-issues a fresh access_token, writes the
    `customer.first_login_password_reset` audit row, and returns
    the merged `{ok, auto_login:true, access_token, user, ...}`
    envelope.
- `routers/admin_migrations.py` — one new endpoint:
  * `POST /admin/migrations/clear-stale-forced-reset-flags` (super_admin
    only, dry-run default, idempotent, customer-role scoped).
- `tests/test_customer_forced_password_reset.py` — new; **7 tests**
  (5 as spec'd, plus admin/technician/super_admin parametrized as 3
  variants of the non-customer defense-in-depth test).

**Frontend**

- `src/auth.jsx` — the `login` + `finalizeAccountChoice` helpers now
  bubble the backend-supplied `role` on the `reset_required` shape,
  and a new `applyResetAutoLogin` method persists the auto-login
  envelope. Public context surface updated accordingly.
- `src/pages/Login.jsx` — both `reset_required` handlers (main login
  + account chooser pick) now gate on `res.role === "customer"`. On
  a non-customer payload the FE renders an inline "Unexpected sign-in
  response" error and refuses to redirect (defense-in-depth).
- `src/pages/ResetPassword.jsx` — after the `/auth/reset-password`
  call, if the response contains `auto_login=true` + `access_token`
  + `user`, persist via `applyResetAutoLogin` and navigate to
  `_landingFor(role)`. Otherwise falls back to the legacy
  "please sign in" redirect to preserve the ordinary
  forgot-password flow.
- `src/test/customer-forced-password-reset.test.jsx` — new; **5
  tests** (customer redirect + 3 parametrized non-customer defense-
  in-depth + auto-login envelope → portal home).

**Memory**

- `/app/memory/FEATURE_CUSTOMER_FIRST_LOGIN_RESET_LOOP_FIX.md`
  (this file).

## Test results

Backend (`tests/test_customer_forced_password_reset.py`) — **7/7**:

| Test | Result |
|---|---|
| `test_customer_first_login_reset_flips_flags_and_auto_logs_in` | ✅ |
| `test_customer_stale_flag_no_fork_and_suspicious_audit` | ✅ |
| `test_non_customer_role_ignores_flag[admin]` | ✅ |
| `test_non_customer_role_ignores_flag[technician]` | ✅ |
| `test_non_customer_role_ignores_flag[super_admin]` | ✅ |
| `test_migration_clear_stale_forced_reset_flags` (dry+wet+idem) | ✅ |
| `test_migration_role_gate` (admin 403 / super_admin 200) | ✅ |

Regression sweep — pre-existing suites still green:

| Suite | Result |
|---|---|
| `tests/test_customer_temp_password_flow.py` | 9/9 ✅ |
| `tests/test_reset_password_characterization.py` | passing (pre-existing) ✅ |
| `tests/test_admin_users_soft_delete.py` | passing (pre-existing) ✅ |

Frontend (`src/test/customer-forced-password-reset.test.jsx`) —
**5/5**:

| Test | Result |
|---|---|
| customer → redirects to /reset-password?flow=temp_password | ✅ |
| admin → inline error, no reset redirect | ✅ |
| technician → inline error, no reset redirect | ✅ |
| super_admin → inline error, no reset redirect | ✅ |
| auto_login envelope → persists JWT + navigates /portal/home | ✅ |

FE regression sweep (touching `auth.jsx` / `Login.jsx` /
`ResetPassword.jsx` — 20/20 pass):

- `login-account-chooser-task4.test.jsx` — 5/5 ✅
- `auth-bootstrap-sync.test.jsx` — 4/4 ✅
- `auth-self-heal-401.test.jsx` — 5/5 ✅
- `k35-portal-login.test.jsx` — 4/4 ✅
- `login-welcome.test.jsx` — 2/2 ✅

OpenAPI: `GET /api/openapi.json` reachable; the new migration
endpoint is registered at `/api/admin/migrations/clear-stale-forced-reset-flags`.

## Guardrails respected

- Preview-only. No prod deploy. No Save-to-GitHub.
- No `/app/mobile/` files touched.
- No external repo cloned (recurring `bbeck169/Pool-Landscaping.git`
  injection has been ignored throughout).
- English only, small-diff.
- Phase 5a.1 remainder / 5a.2 / 5b NOT resumed — this fix ships in
  isolation as the P0 dispatch.

## Deviations

- **`_should_fork_temp_password_flow` also treats `role != "customer"`
  as "no fork," even for non-customer rows with a genuinely-fresh
  temp password.** This is intentional per the spec: staff temp-
  password flows (if we ever add one) must be a separate UX; the
  customer temp-password fork is customer-scoped. Today the only
  writer of `must_change_password_on_next_login=True` on a
  non-customer row is `admin_users.reset-password` at `L266` for
  technicians; those callers already have to consume via
  `/auth/reset-password` after logging in normally.
- **Frontend `Login.jsx` on a non-customer `reset_required` payload
  shows a generic inline error rather than silently completing
  login.** Because the backend post-fix will never emit that shape
  for a non-customer, the FE branch is defense-in-depth: if a stale
  preview server or a bad backend deployment leaks that shape, the
  user sees an actionable error rather than being dropped into the
  wrong UX. If ops ever want the FE to attempt a login-completion
  fallback in that case, we can add it later — but "fail loud" was
  the safer default.
