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

## Feb-2026 · TD-67 · Portal media verification seed
- **Portal customer with media** · `preview-portal0161@preview.local` · `password123`
  - `customer_id = 8910bfde-3ba0-4b18-b54f-6ac5657af13d`
  - `tenant_id   = affdfbfa-88b9-4baa-ae45-2ef78531b6e4`
  - 7 photos surface on `GET /api/portal/photos` (BE emits `{photos, total}` — FE now reads `.photos`).
  - 15 service reports available on `GET /api/customers/me/service-reports` (several with embedded photos/videos).
  - Known SR with 1 visitor photo + 1 job photo:
    `GET /api/customers/me/service-reports/e5f54d08-2d19-40e1-aa1f-c81ee91d9d8e`
  - Known job-attached photo URL (requires `?auth=<token>` or `Authorization: Bearer`):
    `/api/customers/me/jobs/08af77d0-38d7-4307-81b2-f121a758547d/photos/d85a0599-7689-48c0-900c-160169534592`

- **Second-customer isolation guard (different cid, same tenant)** · `customer@aquaterra.com` · `password123`
  - `customer_id = 1c6c0072-8f51-4325-ba18-1c50d5ecab63`
  - Use to verify cross-customer 403 on the stream endpoint:
    `curl "$API/api/customers/me/jobs/<0161-jid>/photos/<0161-pid>?auth=<customer@aquaterra-token>"` → **403 not_your_job**
