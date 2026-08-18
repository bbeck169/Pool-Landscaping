# Known Issues (rolling)

## Tech-id fragmentation across `users` / `technicians` / job docs (Feb-2026)
When a user has both a row in `users` and `technicians` (or was seeded as
one and later imported as the other), the same person can carry three
different ids:
* `users._id` / `users.id`
* `technicians.id`
* `job.technician_id` (may point at either of the above depending on
  which import path created the job)

Downstream impact: client-side filters that key on a single id (e.g. the
legacy Routes tab's `x.technician_id === techId`) can silently miss the
tech's jobs. The new Routes tab wiring dodges this by delegating to
`GET /api/routes/{techId}/stops`, which does the union server-side.

Feb-2026 update — enrichment endpoint hardening:
* `GET /api/routes/{techId}/stops` now falls back to the `technicians`
  collection for `name` + `display_color_hex` when the users lookup
  misses (so passing the `technicians._id` form that `/api/technicians`
  serves still yields a populated `tech_name` / `tech_color_hex`).
* Same endpoint's job query now matches on either `scheduled_start`
  (post-optimizer datetime) OR the flat `scheduled_date` ISO string
  (legacy seeds + recurring-generator writes) — the enrichment path
  no longer silently drops non-optimized jobs.

Follow-up (owner: TBD): reconcile in a dedicated pass — one canonical
id per human, back-fill `job.technician_id` accordingly, and delete the
double-lookup once the store is consistent.

## `backend/.env.example` ships preview-posture defaults (Feb-2026)
`/app/backend/.env.example` — the tracked template — currently seeds
production deploys that follow the `cp .env.example .env` shortcut with
the following preview-only values:

* `SHOW_DEMO_LOGINS=true` (appears twice — duplicated seed sections).
* `APP_ENV=preview` (comms whitelist, Zillow guardrails, Lumino test
  gates all key off this — non-allowlisted recipients drop silently
  in preview mode).
* `STRIPE_MODE=test` (test-mode cards silently accepted).
* `CORS_ORIGINS=*` (too permissive for a customer domain).

This is the drift that caused the `app.plofv.com` demo-tiles leak on
Feb-2026. The client-side hostname gate now blocks the demo-tiles
render regardless, but every other flag above still needs an
independent audit before production.

Follow-up: create a companion `backend/.env.production.example` with
the safe-in-prod defaults inverted, and document a checklist for
promoting a preview deploy to production.


## `/api/payments/stripe/config` returns both `mode` and `stripe_mode` (Feb-2026)
FIX 4 of the Stripe reconciliation batch aligned the config key with
what newer callers expect. The endpoint now returns BOTH `mode`
(legacy) and `stripe_mode` (new canonical) for one release cycle so
existing customer-portal + admin-console builds keep working.

Deprecation: remove `mode` after the next mobile + web build is out
in prod (~Mar 2026). Search for `stripe_mode ||` in the JS/TSX
tree before dropping to catch stragglers.
