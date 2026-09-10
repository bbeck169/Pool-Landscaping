# Mobile Temp-Password + First-Access Parity

**Date**: 2026-04-16

---

## Backend Contracts Verified

```bash
# POST /api/auth/login → returns access_token for normal creds
# POST /api/auth/login → returns { status: "password_reset_required", reset_token, user_id, token_ttl_minutes }
#   for temp-password accounts

# POST /api/auth/reset-password { token, new_password } → { ok: true, message }
# Verified: 400 for invalid token, 400 for short password

# GET /api/auth/me → includes first_access_at, has_ever_logged_in
# Verified: returns "2026-09-10T15:49:54.566915+00:00" and True for mike@
```

---

## Files Touched

| File | Change |
|------|--------|
| `src/auth.tsx` | Added `password_reset_required` handling to `login()` and `finalizeAccountChoice()` return types |
| `app/login.tsx` | Handle `password_reset_required` result in `submit()` and `pickAccount()` — navigate to `/set-password` |
| `app/set-password.tsx` | **Created** — temp password reset screen with silent re-login |
| `app/(app)/customers.tsx` | Added "Never logged in" filter chip (`?first_access=never`) with count badge |

---

## Screens Added

### `/set-password` — SetPasswordScreen
- UX copy: "FIRST-TIME SETUP · Set your permanent password"
- Email chip showing which account is being set up
- New password + confirm password fields with visibility toggle
- Validation: min 6 chars, passwords must match, token required
- On success: silent re-login with email + new password → `/(app)` redirect
- On token expired: friendly Alert → "Back to sign in" button
- TTL notice: "This link is valid for 15 minutes"
- Test IDs: `set-password-screen`, `set-password-heading`, `set-password-input`, `set-password-confirm-input`, `set-password-submit`, `set-password-error`, `set-password-email-hint`, `set-password-back-to-login`

### Customers list — "Never logged in" filter
- Added to More Filters modal in admin customers list
- Sends `?first_access=never` query param to backend
- Count badge fetched via `?count_only=true&first_access=never`
- Test ID: `customers-filter-never-logged-in`

---

## Auth Flow Changes

### Login (`src/auth.tsx`)

`login()` return type extended:
```ts
type LoginResult =
  | { kind: "success" }
  | { kind: "choice"; email; choices; choice_token }
  | { kind: "password_reset_required"; reset_token; user_id; token_ttl_minutes; email }
```

`finalizeAccountChoice()` now returns `LoginResult` instead of `void` — handles the same fork after account selection.

### Login screen (`app/login.tsx`)

```
submit() → login(email, pw)
  ├── kind: "success" → router.replace("/(app)")
  ├── kind: "choice" → show account chooser
  └── kind: "password_reset_required" → router.push("/set-password", { reset_token, email, ttl })

pickAccount() → finalizeAccountChoice(token, accountId)
  ├── kind: "success" → router.replace("/(app)")
  └── kind: "password_reset_required" → router.push("/set-password", { ... })
```

---

## Test Tally

| Test File | Tests | Status |
|-----------|-------|--------|
| `login-temp-password-fork.test.tsx` | 3 | ✅ PASS |
| `login-temp-password-chooser-fork.test.tsx` | 2 | ✅ PASS |
| `reset-token-expired.test.tsx` | 5 | ✅ PASS |
| **All 14 suites** | **78** | **All pass** |

---

## Screenshots

- `/tmp/mobile-temp-password-reset.png` — Set Password screen showing "FIRST-TIME SETUP · Set your permanent password" with email chip, password fields, and "Set password & sign in" button.

---

## Admin Customers Filter

The mobile admin customers list at `app/(app)/customers.tsx` already existed. Added:
- "Never logged in" checkbox in More Filters modal
- Count badge fetched from `?count_only=true&first_access=never`
- Active filter label "Never logged in" in the filter summary
- Query param `?first_access=never` sent to backend on load
