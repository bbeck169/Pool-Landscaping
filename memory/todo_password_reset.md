# TODO — Self-serve Password Reset Backend

**Status:** BLOCKED — frontend stub exists at `/app/frontend/src/pages/ForgotPassword.jsx` and is routed at `/forgot-password`. It always shows the neutral "If an account exists..." confirmation on submit — no actual reset email is sent.

## What's missing

### 1. Backend endpoint — `POST /api/auth/forgot-password`
- Accepts `{"email": "..."}`.
- **Always returns `200 OK`** with a neutral message — never leak whether the email exists (prevents user enumeration).
- If the email matches an active, non-soft-deleted user row:
  - Generate a single-use, time-boxed reset token (JWT with `purpose=password_reset`, 30-min expiry, embed `user_id`).
  - Persist the token id in a `password_reset_tokens` collection with `{token_id, user_id, expires_at, used_at, ip, ua}` so we can revoke on use.
  - Fire an email via Resend to that user with a link back to `{APP_PUBLIC_URL}/reset-password?token=<jwt>`.
- Rate-limit by IP: max 5 requests / hour to prevent enumeration + spam.

### 2. Email template — `password_reset_self_serve`
- Add to `/app/backend/comms_seed/system_data.py::SYSTEM_EMAIL_TEMPLATES`.
- Subject: `Reset your {{tenant.name}} password`.
- Body: brand-headed HTML with a single "Reset password" CTA button linking to `{APP_PUBLIC_URL}/reset-password?token=...`. Also include the plaintext URL below the button for accessibility. Expiry copy: "This link expires in 30 minutes."
- Guardrail: NEVER include the user's current password (obvious) or any customer PII.

### 3. Backend endpoint — `POST /api/auth/reset-password`
- Accepts `{"token": "...", "new_password": "..."}`.
- Validates the JWT signature + `purpose` claim + expiry.
- Looks up the `password_reset_tokens` row → refuses if already `used_at` set (single-use enforcement).
- Rehashes and stores the new password on the user (bcrypt via the same helper `/backend/utils.py::hash_password` uses).
- Sets `used_at` on the token row.
- Rotates the JWT signing key claim so any lingering active sessions for that user become invalid (increment `jwt_generation` on the user row and gate `get_current_user` on it).

### 4. Frontend swap-in
- In `/app/frontend/src/pages/ForgotPassword.jsx`, replace the `TODO` line with `await api.post('/auth/forgot-password', {email})`.
- Create `/app/frontend/src/pages/ResetPassword.jsx` — reads `?token=` from the URL, shows new password + confirm inputs, POSTs to `/auth/reset-password`. On 200, redirects to `/login` with a success toast.
- Route both under `/forgot-password` and `/reset-password` in `App.js`. `/forgot-password` route is already wired.

### 5. Tests
- pytest: `POST /auth/forgot-password` returns 200 for both existing + non-existing emails (no enumeration).
- pytest: token TTL enforced.
- pytest: single-use enforcement.
- pytest: rate limit fires after 5 requests.
- vitest: `ResetPassword.jsx` validates confirm-match and shows an error toast on 400.

### 6. Delegation
- Once backend ships, delegate mobile parity to `e1_expo_frontend_dev` via a Phase-34-follow-up brief. Same UX: "Forgot password?" link under the password field on mobile login, opens a modal with an email input, POSTs to the same endpoint.

## Priority
P1 — customer-facing gap. Currently the ONLY reset path is the admin-triggered `POST /api/users/{id}/reset-password` (admin scope only), which means customers who forget their password have no self-serve recovery.

## Estimated effort
- Backend: ~2 hours (endpoints + template + rate limit + tests)
- Frontend: ~30 min (ResetPassword page + wire the stub)
- QA: ~30 min

## Guardrails when implementing
- Never leak account existence (return 200 in both branches).
- Never log the reset token to server logs.
- Rate-limit by IP AND by email (5/hour each).
- Rotate `jwt_generation` on successful reset so old sessions become invalid.
