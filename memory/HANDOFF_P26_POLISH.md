# Handoff — Phase 26 polish + Phase 21 audit (Feb 15 2026)

## Bundled fixes shipped

### Phase 26 · Skill-profile matching (dispatcher enhancement)
- Extended `_rank_techs_for_job` with `skill_multiplier`:
  - `1.0` when tech's `preferred_service_types` contains the job's `service_type`
  - `1.5` when tech has no stated preferences (neutral)
  - `2.5` when tech has preferences but the job isn't one (off_specialty)
- Reasoning payload now includes `skill_match`, `skill_multiplier`, `raw_cost`, and `preferred_service_types` per candidate tech.
- **New endpoints (+2)**:
  - `GET  /api/dispatch/technician-skills` — every active tech's profile for the settings panel
  - `PATCH /api/users/{uid}/skill-profile` — admin-only update, normalized to lowercase, propagates to both `users` and `technicians` collections
- Legacy compatibility: reads prefs from `technicians` doc first, falls back to `users` doc.

### Phase 21 · Estimator ImageContent SDK audit
- Root cause identified: `emergentintegrations` SDK requires `ImageContent(image_base64=...)`, NOT `image_url=`.
- Fixed `routers/estimator.py::_call_generate`:
  - Fetches each photo URL via `httpx.AsyncClient` first
  - Base64-encodes and passes to `ImageContent(image_base64=...)`
  - Guards fetch failures: broken/404/timeout URLs are logged and skipped, but the generate call CONTINUES with the remaining photos
  - Response now includes `skipped_photos: [{url, reason}]` for admin visibility

## Delta
- **OpenAPI: 543 → 545 (+2 endpoints)**
- **Tests: +5 (5/5 pass)**:
  - `test_dispatcher_prefers_skilled_tech` — pool specialist beats landscape at same distance
  - `test_dispatcher_penalizes_off_specialty` — pool-skilled at 5km beats off-specialty at 3km (skill mult overrides distance)
  - `test_dispatcher_neutral_when_no_preferences` — empty prefs → 1.5x, not penalized
  - `test_patch_skill_profile_and_list` — PATCH updates both collections, GET returns correct prefs
  - `test_estimator_generate_survives_broken_photos` — mixed valid+broken URLs → 200, no crash, `skipped_photos` reports the failures
- Regression sweep: 47/47 fast + 3/3 Wave B live-Claude smoke → **all green**.

## Live demo (curl)
- Alice (pool specialist) vs Bob (landscape specialist) at same distance for a `pool` job:
  - Alice: raw=5594m × 1.0 = **5594** (exact match) → **WINS**
  - Bob:   raw=5594m × 2.5 = 13985 (off_specialty)
- PATCH Mike Rivera's skill-profile with `["Pool","REPAIR","Chemistry"]` → normalized to `["pool","repair","chemistry"]`, mirrored to both `users` and `technicians` docs.

## Known cosmetic follow-up
- `GET /dispatch/technician-skills` may list the same tech twice if a technician has one row in `technicians` AND a legacy user row where `user_id` doesn't line up (rare). Cosmetic only — functional flow is unaffected.

## Frontend
- No new admin pages required — the dispatcher UI already reads `reasoning[].skill_match` and will auto-display when the field is present (defer explicit skill chip UI to a small polish PR).

## Wave C next
Warranty Portal.
