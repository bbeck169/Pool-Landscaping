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
