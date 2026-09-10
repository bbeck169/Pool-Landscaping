# FEATURE — Customer temp password + first-access tracking

**Date shipped**: Feb 10, 2026 · Preview
**Scope**: Backend + Web admin frontend. Mobile parity is a separate handoff to `e1_expo_frontend_dev`.
**Status**: ✅ SHIPPED to preview. Not yet in production (user redeploys.)

## What & Why

Admin-provisioned portal passwords are now real temp passwords: **no TTL expiry**, but the customer **must** replace them on first sign-in. First-access is stamped once and never overwritten so admins can chase customers who received an invite but never actually onboarded — a distinct signal from "chose their own password" (which is what the pre-existing Portal Status filter covers).

## API surface diff

### Modified — `POST /api/auth/login` & `POST /api/auth/login/select-account`
After password verification succeeds and the matched user carries `must_change_password_on_next_login=true`, the endpoint short-circuits BEFORE issuing an access token:

```json
HTTP 200
{
  "status": "password_reset_required",
  "reset_token": "<opaque 48-byte url-safe>",
  "user_id": "<uid>",
  "token_ttl_minutes": 15
}
```

- No `access_token` is issued.
- No portal-login denorms are stamped (`last_portal_login_at` / `portal_first_login_at` remain unset).
- A row is minted in `password_reset_tokens` with `source="temp_password_login"` and a 15-min expiry (see decisions below).
- Any prior unused tokens for the same user are invalidated.

### Unchanged — `POST /api/auth/reset-password` (Task-O primitive, reused verbatim)
Per the greenlit guidance ("Reuse existing password-reset primitive if one exists — do NOT invent a parallel flow"), the reset consummation goes through the existing `/auth/reset-password` endpoint. Its internal helper `_apply_new_password` already clears `must_change_password_on_next_login`, so the temp-flag flip is idempotent. **No new `/auth/complete-password-reset` endpoint was added** — that spec bullet was intentionally routed through the existing primitive.

### New — first-access denorms
- **`users` document**:
  - `has_ever_logged_in: bool` (default `false`)
  - `first_access_at: ISO string | null`
  - `first_access_ip: string | null`
  - `first_access_backfilled: bool` (set only by the migration endpoint)
- **`customers` document**:
  - `portal_first_login_at: ISO string | null` — stamped ONCE on the customer's first completed sign-in and never overwritten. (Distinct from `last_portal_login_at`, which the login path already overwrites on every sign-in.)

Both are stamped by a single idempotent helper `_stamp_first_access(user, ip)` at the end of both `login` and `login_select_account`.

### New query param — `GET /api/customers?first_access=never|any`
- `never` → `portal_first_login_at` is null/missing.
- `any` → `portal_first_login_at` is set.
- Unknown value → 400 `{detail: "invalid_first_access", ...}`.
- Composes as intersection with all existing filters (search, city, tag, data-quality, portal-status, tabs).
- Admin/manager/technician gate inherited from the list endpoint.

### New — `POST /api/admin/migrations/backfill-first-access`
- `super_admin` only. Idempotent. Dry-run default.
- Scans `users` where `has_ever_logged_in ≠ true`.
- Evidence hunt (in order):
  1. Earliest `audit_logs` row with `event="login" status="success"` OR `event="portal_login"`, matched by lowercased email.
  2. Fallback: `users.last_login_at` (used as a floor).
- On evidence: stamps `has_ever_logged_in=true`, `first_access_at=<earliest evidence>`, `first_access_backfilled=true`; if the user is role=customer with a `customer_id`, mirrors `portal_first_login_at` to the customer doc (only when the customer doc doesn't already have it stamped).
- No evidence → row is left untouched — counted in `no_evidence` bucket. **This is the intended behavior**: those customers WILL surface in the "Never logged in" chip, which is what the admin wants to see.

**Response shape**:
```json
{
  "ok": true, "dry_run": true, "tenant_id": "<tid>",
  "users_scanned": 42, "users_already_stamped": 5,
  "users_stamped": 30, "customers_denormed": 22, "no_evidence": 7
}
```

## Files touched

**Backend (4)**
- `backend/routers/portal_admin.py` — `_upsert_customer_user` stamps `must_change_password_on_next_login=True` + `temp_password_issued_at`.
- `backend/routers/auth.py` — Temp-password login fork + `_stamp_first_access` + `_mint_temp_password_reset_token` + `_TEMP_PASSWORD_RESET_TTL_MINUTES=15` constant. Wired into both `login` and `login_select_account`.
- `backend/routers/customers.py` — New `first_access: Optional[str]` query param + filter body + `portal_first_login_at` exposed on `CustomerListItem`.
- `backend/routers/admin_migrations.py` — New `POST /admin/migrations/backfill-first-access` endpoint + `BackfillFirstAccessBody` model.

**Frontend (4)**
- `frontend/src/auth.jsx` — `login()` + `finalizeAccountChoice()` return `{kind: "reset_required", reset_token, user_id, token_ttl_minutes}` when the backend forks.
- `frontend/src/pages/Login.jsx` — On `kind === "reset_required"`, navigates to `/reset-password?token=<t>&flow=temp_password` (both the direct login and post-chooser paths).
- `frontend/src/pages/ResetPassword.jsx` — Title/copy branches on `flow=temp_password`, adds a "First-time sign-in" info banner.
- `frontend/src/pages/customers/CustomersList.jsx` — New `neverLoggedIn` state + URL sync (`first_access=never`) + "First-time sign-in" filter group + standalone count-fetch + wired into the load-effect deps + active-filter counter + summary bit.

**Tests + docs (3)**
- `backend/tests/test_customer_temp_password_flow.py` — 8 pytest cases (all green).
- `frontend/src/test/customer-first-access-filter.test.jsx` — 13 vitest cases (all green).
- `memory/FEATURE_CUSTOMER_TEMP_PASSWORD_FIRSTACCESS.md` — this file.
- `memory/screenshots/customers_never_logged_in.jpeg` — admin filter with `(28)` count badge.

## Decisions locked in

1. **Login response shape** — HTTP 200 + `{status: "password_reset_required", ...}`. Mirrors the existing `multi_account_choice_required` pattern. Payload contains only `reset_token`, `user_id`, `token_ttl_minutes` — no email, no role.
2. **Reset token TTL = 15 min**. The **temp password itself has no expiry** — if the mid-flow token lapses, a re-login with the same temp password mints a fresh one and invalidates the prior one. Verified by `test_temp_password_never_expires_relogin_mints_fresh_token`.
3. **Backfill leaves truly-never-logged-in customers at defaults.** The `no_evidence` bucket is intentional so the "Never logged in" filter surfaces them. `first_access_at` for pre-feature rows that only survive with a bare `last_login_at` is an **upper bound**, not a precise stamp — documented here so ops knows.
4. **Temp password generator unchanged** — same `_random_password(12)`. Out of scope.
5. **Reuse of the Task-O reset primitive** — no new `/auth/complete-password-reset` endpoint was added. `/auth/reset-password` already handles the token consumption, password policy validation, and flag flip. Only the token minting side is new (`_mint_temp_password_reset_token` with `source="temp_password_login"`).

## Test tally

| Suite | Cases | Result |
|---|---|---|
| `backend/tests/test_customer_temp_password_flow.py` | 8 | ✅ |
| `backend/tests/test_auth_option_a_account_chooser_task4.py` | 10 | ✅ (no regression) |
| `backend/tests/test_jobs_list_slim_photos.py` | (existing) | ✅ |
| Customer suites (mute / muted-exclusivity / detail-tabs / merge×2) | 74 | ✅ (2 pre-existing failures on `test_customer_detail_additions` — confirmed on `main` without changes) |
| `frontend/src/test/customer-first-access-filter.test.jsx` | 13 | ✅ |
| Customers-list filter regression sweep (portal / waitlist / active / P43c / K49 / filter-bar) | 66 | ✅ |
| Auth/reset flow adjacent (api-401-interceptor / team-admin-actions / K30 copy-admin-link) | 30 | ✅ |

**Pre-existing flakes deliberately not chased** (per standing user instruction):
- `backend/tests/test_pb3_profit_report.py::test_sent_status_is_excluded`
- `backend/tests/test_customer_delete_ux.py::test_hard_delete_does_not_cascade_and_orphan_jobs_still_read_ok`
- `backend/tests/test_customer_detail_additions.py::test_third_mobile_rejected_with_400` / `test_fourth_email_rejected_with_400`

All four were verified to fail on `main` without this feature branch's changes (git stash + rerun).

## E2E smoke on preview

```
$ curl /api/auth/login (admin) → HTTP 200, has_token=True, role=super_admin
$ curl /api/customers?count_only=true&first_access=never → {"count": 28}
$ curl /api/customers?count_only=true&first_access=any    → {"count": 0}
$ curl /api/customers?first_access=bogus                  → HTTP 400 invalid_first_access
```

Web admin: the "First-time sign-in → Never logged in (28)" chip renders and toggles the URL to `?first_access=never`. Screenshot: `memory/screenshots/customers_never_logged_in.jpeg`.

## Follow-ups (out-of-scope handoff)

- **Mobile parity** → `e1_expo_frontend_dev`: mirror the `password_reset_required` fork in `/app/mobile/`. Same response shape; native deep-link into the reset screen. (Main agent MUST NOT touch `/app/mobile/`.)
- **Migration execution**: user drives `POST /admin/migrations/backfill-first-access` with `dry_run=false` from the deployed app once they're comfortable with the dry-run counts.
- **Portal Status vs First-time sign-in** — the two filters are intentionally distinct. If the admin conflates them in QA, consider a docs tooltip; do NOT merge the signals server-side.
