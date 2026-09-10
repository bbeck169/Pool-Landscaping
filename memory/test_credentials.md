# Test Credentials — Pool & Landscaping of Vistancia

> Reset to password123 by reset_demo_passwords_to_default.py on 2026-09-10T16:05:36.052474+00:00 (demo mode)

## Auth mechanism
- POST `/api/auth/login` with `{email, password}` returns `{access_token, user}`.
- Tokens are Bearer JWTs — send `Authorization: Bearer <token>` on every subsequent call.
- Demo mode: all seeded accounts share the plaintext `password123`. Rotate with `scripts/rotate_demo_passwords.py` for a security review.

## Accounts
- **super_admin** · `super@aquaterra.com` · `password123`
- **admin** · `admin@aquaterra.com` · `password123`
- **technician** · `mike@aquaterra.com` · `password123`
- **technician** · `carlos@aquaterra.com` · `password123`
- **customer** · `customer@aquaterra.com` · `password123`

## Notes
- Landscape techs carry `role: "technician"` + `department: "landscaping"` and are required to
  finalize their onboarding checklist before route assignment.
- Emergent LLM key, Resend API key, Stripe test/live keys are in `/app/backend/.env`.
- `SEED_DEMO_USERS` gate is unchanged — production still refuses to seed these demo users.
