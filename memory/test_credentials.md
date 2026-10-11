# Test Credentials — Pool & Landscaping of Vistancia

> Reset to password123 by reset_demo_passwords_to_default.py on 2026-09-10T16:05:36.052474+00:00 (demo mode)
> Last end-to-end verified (`POST /api/auth/login` → 200 + token) on 2026-02-15 against the preview DB. **6/6 accounts authenticate.** The missing `customer@aquaterra.com` users row was restored by the new idempotent `seed_demo_primary_customer` boot step (anchored to customer_id `573affb3-5cae-4970-8be1-8922ab7034ee` in the aquaterra tenant).

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

## Feb-2026 · P0 · Lead form address autofill (Google Places)
- Use `admin@aquaterra.com` / `password123` to drive the admin
  Marketing Forms builder (`/admin/marketing/forms`) — the
  `address_google` field type renders a live `AddressAutocomplete`
  preview so admins can validate the visitor experience.
- Public widget flow needs NO credentials — hit
  `GET /api/public/places/autocomplete?input=…` and
  `GET /api/public/places/details?place_id=…` anonymously. Both
  routes are rate-limited to **30 req/min/IP**.
- The two routes are visible on `/api/openapi.json` (total paths
  now **1751**, up from 1749).

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
