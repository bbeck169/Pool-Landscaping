# Feb-2026 · Photos-in-S3 · Phase 2 — Backfill Migration

## What ships

New admin-only endpoint that walks legacy job photos (base64 in
Mongo, no `s3_key`) and dual-writes them into S3, stamping
`photos[].s3_key` + `photos[].s3_mime` on the doc so the read path
(from Phase 1) serves presigned URLs.

**`POST /api/admin/migrations/migrate-photos-to-s3`**

| Param                  | Default | Notes                                                        |
|------------------------|---------|--------------------------------------------------------------|
| `dry_run`              | **`true`** | No S3 writes, no DB writes. Emits the size tally only.    |
| `limit`                | `500`   | Per invocation, `1..2000`. Enables paged sweeps.             |
| `tenant_id`            | `null`  | Scope to one tenant. Null = all tenants.                     |
| `purge_base64`         | **`false`** | When true (and only after S3 upload verifies), unset `photos[].data`. Deliberately opt-in so rollback stays trivial. |
| `resume_after_job_id`  | `null`  | Cursor for resumable batches. Jobs sorted by `id` ASC.       |
| `rate_limit_qps`       | `10`    | Semaphore-bounded S3 concurrency, `1..64`.                   |

Auth: `admin` / `super_admin` / `owner` only. Non-admin → `403`.
Flag off (`PHOTOS_S3_ENABLED=false` or S3 client unavailable) →
`409 s3_disabled` — no partial migration state.

### Response envelope
```json
{
  "dry_run": true,
  "purge_base64": false,
  "scope": {"tenant_id": "...", "limit": 500},
  "scanned_jobs": 42,
  "candidate_photos": 71,
  "would_upload_bytes": 1234567,
  "uploaded":         [{"job_id":"...","photo_id":"...","s3_key":"...","bytes":N}],
  "already_migrated": [{"job_id":"...","photo_id":"...","s3_key":"..."}],
  "failed":           [{"job_id":"...","photo_id":"...","error":"..."}],
  "next_resume_after_job_id": "abc123" | null,
  "elapsed_ms": 539
}
```

`next_resume_after_job_id` is `null` when the returned page is
smaller than `limit` — i.e. no more work in scope. Otherwise the
caller loops with that value as `resume_after_job_id` until it
comes back null.

## Lifecycle

### Pre-migration invariant
Legacy row: `photos[i] = {id, data, label, created_at}` — no
`s3_key`, no `s3_mime`. Read path serves the base64 blob directly.

### Post-migration invariants
- **After wet-run without purge**: `photos[i] = {id, data,
  s3_key, s3_mime, label, created_at}`. Read path serves a 302 to
  the presigned URL (Phase 1 behavior). Base64 remains as a
  belt-and-braces fallback for rollback.
- **After wet-run WITH purge**: same as above but `data` unset.
  Only recommended AFTER all tenants report `100%` migrated in a
  parallel dry-run + you've confirmed S3 read parity.

### Runbook (operator)
```bash
BASE="https://<preview-or-prod-host>/api"
TOKEN="<admin JWT>"

# 1) Dry-run whole cluster (all tenants). Prints candidate counts.
curl -s -X POST "$BASE/admin/migrations/migrate-photos-to-s3?dry_run=true&limit=500" \
  -H "Authorization: Bearer $TOKEN" | jq

# 2) Wet-run one tenant at a time, NO purge (safer rollback posture).
#    Loop until next_resume_after_job_id is null.
NEXT=""
while :; do
  R=$(curl -s -X POST "$BASE/admin/migrations/migrate-photos-to-s3?dry_run=false&purge_base64=false&limit=500&tenant_id=<tid>&resume_after_job_id=$NEXT" \
       -H "Authorization: Bearer $TOKEN")
  echo "$R" | jq '{scanned:.scanned_jobs, done:(.uploaded|length),
                   fail:(.failed|length), already:(.already_migrated|length),
                   next:.next_resume_after_job_id}'
  NEXT=$(echo "$R" | jq -r '.next_resume_after_job_id // ""')
  [ -z "$NEXT" ] && break
done

# 3) Sanity: photo reads still serve 302 -> presigned URL. Sample a few.
curl -sI "$BASE/public/job-photo/<jid>/<pid>" | head

# 4) (Later — after Phase 3 sign-off) wet-run WITH purge to reclaim Mongo.
#    Same loop as (2) but with purge_base64=true.
```

### Rollback plan
If S3 blows up mid-migration and reads start 502ing:

1. Read fallback: while `photos[].data` is still populated, the
   Phase 1 read path falls back to serving base64 whenever the
   presign returns `None`. No rollback needed for reads.
2. Full rollback (wipe `s3_key` so nothing tries to presign):
   ```js
   // mongosh, all tenants
   db.jobs.updateMany(
     {"photos.s3_key": {"$exists": true}},
     {"$unset": {"photos.$[].s3_key": "", "photos.$[].s3_mime": ""}}
   );
   ```
   Objects in the bucket are harmless (the reader ignores them
   without a key on the doc). A re-run of the migration will
   short-circuit on `check_object_exists` and just re-stamp.
3. Do **NOT** run rollback after a `purge_base64=true` sweep —
   there's no base64 to fall back to. That's why Phase 2 keeps
   `purge_base64=false` as default and treats the `true` flip as
   a Phase-3-adjacent decision.

### Failure isolation
Individual photo errors (decode, `upload_photo` returning `None`,
DB stamp failing) are collected in `failed[]` — the migration
continues past them. The retry semantics are:

- Decode failure → data was corrupt; hand-inspect the doc.
- Upload returned `None` → transient S3 error; re-run picks up
  the same photo (still no `s3_key`).
- Post-upload DB stamp failure → S3 object exists but doc unset;
  re-run short-circuits via `check_object_exists` and stamps.

## Tests

`tests/test_photos_s3_phase2_migration.py` — 8 cases, all mocked
S3 via `_S3Stub`, DB uses the shared `_f7_loop_fixture.run_test`
helper:

| # | Test                                                    | Status |
|---|---------------------------------------------------------|--------|
| 1 | dry-run touches nothing (no S3 puts, no DB writes)      | ✅ |
| 2 | wet-run w/o purge → stamps `s3_key`, keeps `data`       | ✅ |
| 3 | wet-run WITH purge → stamps + unsets `data`             | ✅ |
| 4 | idempotency — 2nd run reports `already_migrated`        | ✅ |
| 5 | resumable — `limit=1` + cursor covers two jobs          | ✅ |
| 6 | failure isolation — bad photo goes to `failed[]`        | ✅ |
| 7 | auth gate — tech token → `403` (HTTP)                   | ✅ |
| 8 | flag off — patched → `409 s3_disabled`                  | ✅ |

Regression: 9/9 Phase-1 wire-contract tests (`test_photos_s3_phase1.py`)
still pass. Two Phase-1 tests (`test_upload_does_NOT_stamp_s3_key_when_flag_off`,
`test_admin_s3_health_reports_disabled_by_default`) are now
environmental-drift failures because the user activated
`PHOTOS_S3_ENABLED=true` in `.env`. These tests were authored
assuming the flag stays off; not caused by Phase 2 and left alone
per the "small reviewable diff" constraint.

Live smoke-test executed against real S3 in preview (bucket
`emergant`, region `us-east-2`) — full lifecycle validated:

- Seeded 1 legacy photo (67-byte PNG, no `s3_key`).
- Wet-run migrated: `uploaded[0]` stamped, HEAD on S3 confirms
  67 bytes / `image/png` / `AES256`.
- Mongo doc carries `s3_key` + `s3_mime`, `data` intact
  (`purge_base64=false`).
- Second wet-run: `uploaded_this_job=[]` — idempotent.
- Elapsed 539 ms for one photo.
- Test artifact cleaned up (S3 key + Mongo doc).

## Phase 3 (future ticket)

Cutover: once every tenant reports 100% migrated via a fleet-wide
dry-run and read parity is confirmed, run the wet-run with
`purge_base64=true` to reclaim Mongo storage. After that, delete
the base64 fallback branch in `services/aws_s3/photos.py` /
`routers/jobs.py::public_job_photo` and treat `s3_key` as the sole
source of truth. That's Phase 3 — separate ticket, not shipped
here.

## Files touched
- **New** `backend/routers/admin_s3_migrate.py`
- **New** `backend/tests/test_photos_s3_phase2_migration.py`
- **Updated** `backend/server.py` — 4 lines: include the new
  router next to the Phase-1 health router registration.

No mobile changes. No `.env` writes. No frontend changes. No
Save-to-GitHub (per user directive — preview only).
