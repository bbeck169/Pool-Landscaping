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
- **customer (secondary)** · `customer2@aquaterra.com` · `password123` — Feb-2026 seeded via `seed_demo_second_customer()` (idempotent, boot-time). Anchored to the Robert Blake customer record so it is a distinct `customer_id` from `customer@aquaterra.com`. Use this account to verify wrong-customer 403 branches (e.g. `GET /api/customers/me/jobs/{jid}/photos/{photo_id}`).

## Notes
- Landscape techs carry `role: "technician"` + `department: "landscaping"` and are required to
  finalize their onboarding checklist before route assignment.
- Emergent LLM key, Resend API key, Stripe test/live keys are in `/app/backend/.env`.
- `SEED_DEMO_USERS` gate is unchanged — production still refuses to seed these demo users.

## Feb-2026 · Multi-Contact Phase 1 · new gated routes
- `PATCH /api/customers/{cid}/mute-automations` — **admin / super_admin only** (403 otherwise).
  Body: `{"muted": bool, "reason": str?, "channel": "all"|"email"|"sms"?}`.
- `POST /api/admin/migrations/customer-contacts-to-arrays` — **super_admin only** (admin returns 403).
  Query: `dry_run: bool = True`, `tenant_id: str?`.

For local curl testing use `super@aquaterra.com` for the migration endpoint;
`admin@aquaterra.com` works for the mute PATCH.
