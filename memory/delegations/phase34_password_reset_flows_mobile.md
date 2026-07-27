## Delegation Brief · Phase 34 (web/backend) → Phase 33 (mobile)
### Password Reset Flows — Forgot Password + In-Portal Change Password

**From:** Web / backend team · Phase 34 · Feb 2026 · Task O
**To:** e1_expo_frontend_dev
**Priority:** P1
**Language:** English only.
**Status:** Web + backend SHIPPED. Mobile parity outstanding.

---

### 1. Self-serve "Forgot password?" flow

Two new backend endpoints are live:

```
POST /api/auth/forgot-password
Body: { "email": "user@example.com" }
Response 200 (always neutral, enum-safe):
  { "ok": true,
    "message": "If an account exists for that email, a reset link has been sent." }
```

- Rate-limited to 5 requests / IP / hour. Over-cap still returns the
  same neutral 200 (never hints that the account exists).
- On a match: mints an opaque URL-safe token, persists to
  `password_reset_tokens` with a 30-min expiry + `used_at` field,
  and emails a link `{APP_PUBLIC_URL}/reset-password?token=<token>`
  via the guarded Resend adapter (dry-runs in preview unless the
  recipient is on `COMMS_TEST_ALLOWLIST_EMAILS`).

```
POST /api/auth/reset-password
Body: { "token": "...", "new_password": "..." }
Response 200: { "ok": true, "message": "Password reset. Please sign in." }
Response 400: { "detail": "<friendly error>" }
```

- Password policy: ≥8 chars, at least one lowercase, one uppercase, one digit.
- Rejects unknown / used / expired / invalidated tokens with clear
  messages the UI can show verbatim.
- Success → invalidates any other unused tokens for the user, clears
  `failed_login_attempts` + `lockout_until`, and updates the hash.

### 2. In-portal "Change password" flow

```
POST /api/auth/change-password
Auth: bearer
Body: { "current_password": "...", "new_password": "..." }
Response 200: { "ok": true, "message": "Password updated." }
Response 400: { "detail": "Current password is incorrect." | "Password must include an uppercase letter." | ... }
```

Same policy as reset. Verifies current password before applying the new one.

### What we need from mobile

**Screen A — Forgot Password**

- `/app/mobile/app/forgot-password.tsx` (already stubbed per the
  previous brief `phase33_forgot_password_mobile.md`). Wire the submit
  handler to POST the endpoint above. Show the SAME neutral copy on
  success regardless of the actual result (no enumeration).

**Screen B — Reset Password (new)**

- `/app/mobile/app/reset-password.tsx` — deep-linkable route.
- Read the `token` query param from the deep link (`myapp://reset-password?token=<token>` and
  `https://<host>/reset-password?token=<token>`).
- Render a form with two password fields (new + confirm) + strength
  hints (min 8 chars, upper/lower/digit).
- On submit POST `/api/auth/reset-password`.
- On success navigate to `/login` + toast "Password reset. Please sign in."
- On error surface the `detail` string inline.
- `testID`s: `reset-password-page`, `reset-password-new`,
  `reset-password-confirm`, `reset-password-submit`,
  `reset-password-mismatch`, `reset-password-strength`,
  `reset-password-error`.

**Screen C — Change Password (in-portal)**

- Update the existing profile screen's Change Password section:
  wire submit to `POST /api/auth/change-password` (was previously
  broken / stubbed).
- Show clear success + error states.
- Enforce the same client-side password policy for immediate
  feedback; the backend is authoritative.

### Deep-link registration

If the app's `app.json` / `expo-router` config doesn't already list
`reset-password` as a valid path, add it so the token-bearing link
in the email opens the app directly on installed devices.

### Guardrails

- English-only.
- NEVER reveal whether an email is registered.
- Do NOT bypass server-side password policy on any of the three
  screens — the backend re-validates and is source of truth.
- Do NOT store or log the reset token beyond the current screen.

### Reference paths

- Backend endpoints:  `/app/backend/routers/auth.py` (functions
  `forgot_password`, `reset_password`, `change_my_password`)
- Backend pytest:     `/app/backend/tests/test_phase34_task_o_password_reset.py`
- Web forgot page:    `/app/frontend/src/pages/ForgotPassword.jsx`
- Web reset page:     `/app/frontend/src/pages/ResetPassword.jsx`

### Deploy

- Mobile: OTA / EAS update after merge. Deep-link config may need a
  native rebuild if `expo-router` scheme changes.
