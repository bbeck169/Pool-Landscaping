# FEATURE — Photos-in-S3 · Phase 1 (dual-write + presigned reads)

**Date**: 2026-02-10 (wall clock 2026-09-10)
**Author**: e1_dev
**Scope**: Move job photo blobs from Mongo (`photos[].data` base64) to S3 — feature-flagged, dual-write, presigned-URL reads. Phase 1 only. **Zero production impact until an operator sets `PHOTOS_S3_ENABLED=true` + populates real AWS creds.**

---

## TL;DR

- New `PHOTOS_S3_ENABLED` flag, OFF by default. When off, ZERO behavior change on any surface.
- New service module `backend/services/aws_s3/photos.py` — every function is a safe no-op when config is missing, NEVER raises.
- Photo upload dual-writes: DB blob unchanged + best-effort S3 put with SSE-S3.
- Public read redirects (302) to short-TTL presigned URL when `s3_key` exists + flag on.
- Photo delete removes the DB entry AND the S3 object (best-effort).
- Admin health endpoint at `GET /api/admin/s3/health`.
- **`s3_key` NEVER leaks over the wire** — stripped from upload response, detail response, and `include_photos=true` list.
- 11/11 new tests + 13/13 slim-photos regression = **24/24 green**.

---

## Files touched

| File | Delta |
|---|---|
| `backend/.env` | Added 7 env vars (all placeholders except `PHOTOS_S3_ENABLED=false` and `AWS_REGION=us-east-1` + prefix + TTL defaults). |
| `backend/services/aws_s3/__init__.py` | NEW — package init. |
| `backend/services/aws_s3/photos.py` | NEW — ~250 LOC. `upload_photo`, `generate_signed_url`, `delete_photo`, `check_object_exists`, `health_check`, `build_key`, `decode_data_url`. Safe-fallback semantics on every function. |
| `backend/routers/admin_s3_health.py` | NEW — admin-gated `GET /api/admin/s3/health`. |
| `backend/routers/jobs.py` | ~55 LOC delta across 3 sites: photo upload dual-write, public-read presigned redirect, photo-delete dual-delete + wire-strip on detail + upload responses. |
| `backend/services/jobs_slim_photos.py` | +1 helper `strip_s3_metadata_from_photos` + `include_photos=True` branch strips `s3_key`/`s3_mime`. |
| `backend/server.py` | +2 LOC: `include_router(admin_s3_health.router)`. |
| `backend/tests/test_photos_s3_phase1.py` | NEW — 11 test cases. |

**Zero DB schema change.** `photos[]` array carries an optional `s3_key` + `s3_mime` on freshly-uploaded photos when the flag is on. Legacy photos have neither and work unchanged.

---

## Secrets contract (`backend/.env`)

Added block (leave all blanks until operator adds real values):

```env
PHOTOS_S3_ENABLED=false               # Master feature flag — set to `true` after AWS is wired.
AWS_ACCESS_KEY_ID=                    # From IAM user with the policy below
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-1
AWS_S3_BUCKET=                        # e.g. `plofv-job-photos-prod`
AWS_S3_PREFIX=job-photos/             # Key prefix inside the bucket
AWS_S3_SIGNED_URL_TTL=3600            # Seconds; clamped to [60, 86400]
```

**Env-based creds, not per-tenant BYO.** The current backend has BYO patterns for Stripe/Resend/RingCentral (per-tenant keys stamped on `tenants` collection) — S3 does NOT follow that pattern in Phase 1 because photos are a platform-wide storage concern rather than a tenant-billed integration. Follow-up ticket §Rollback logs `S3-BYO-PER-TENANT` for future consideration.

---

## Recommended AWS setup

### IAM policy (least privilege)

Attach to the IAM user whose keys you paste into `.env`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PhotosBucketReadWrite",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:HeadObject"
      ],
      "Resource": "arn:aws:s3:::YOUR_BUCKET_NAME/job-photos/*"
    }
  ]
}
```

No `s3:ListBucket` needed — the health endpoint uses `HeadObject` on a sentinel key it writes/deletes, not a `ListObjects` scan.

### Bucket config

1. **Block Public Access = ON** (all four toggles). Reads are signed-URL-only; the bucket itself stays private.
2. **Default encryption = SSE-S3 (AES256)** — the module ALSO sends `ServerSideEncryption: AES256` on every `PutObject` as belt-and-braces.
3. **Versioning = OFF** — Phase 1 doesn't need it; adds cost + surface area.
4. **Lifecycle rule** (optional, not required for Phase 1): expire objects under `job-photos/_healthcheck/` after 1 day so probe artifacts self-clean.

Region is arbitrary (env-driven). Default `us-east-1`.

---

## Feature-flag behavior matrix

| Flag | Bucket / creds | Upload path | Read path | Delete path | Health endpoint |
|---|---|---|---|---|---|
| `false` (default) | any | DB blob only, `s3_key` NOT stamped | serves base64 as `Response` | pulls from DB only | `status: "disabled"` |
| `true` | missing | DB blob only, `s3_key` NOT stamped, warning logged | serves base64 | pulls from DB only | `status: "misconfigured"` |
| `true` | set + boto3 raises | DB blob stamped, `s3_key` NOT stamped, warning logged | serves base64 | pulls from DB only | `status: "unhealthy"` (self-test failed) |
| `true` | set + boto3 OK | DB blob AND `s3_key` stamped | 302 → presigned URL | S3 delete + DB pull | `status: "healthy"` with `roundtrip_ms` |

**Key property**: photo saves are NEVER blocked by S3 failures. The DB blob is the source of truth in Phase 1.

---

## Wire-contract preservation

`s3_key` and `s3_mime` are stamped ONLY on the DB doc. They NEVER ship over the wire on any endpoint:

- Upload response (`POST /api/jobs/{jid}/photos`) — `strip_s3_metadata_from_photos` runs before return.
- Detail response (`GET /api/jobs/{jid}`) — same strip.
- List with `include_photos=true` — `slim_photos_on_rows` filters out both keys per photo.
- Slim list (default) — `photos` array is dropped entirely; `photo_count` + `photo_ids` computed from `id` + `len` (survives the projection sweep).

The public photo endpoint (`GET /api/public/job-photo/{jid}/{pid}`) returns EITHER a 302 to a presigned URL OR the base64 payload directly — the S3 key is used as a lookup only, never exposed.

Locked by three tests: `test_strip_s3_metadata_from_photos_removes_s3_keys`, `test_detail_endpoint_strips_s3_key_from_wire`, `test_upload_stamps_s3_key_when_flag_on` (upload response assertion).

---

## Test tally

| Suite | Cases | Pass |
|---|---|---|
| `test_photos_s3_phase1.py` (NEW) | 11 | **11/11** |
| `test_jobs_list_slim_photos.py` (regression) | 5 | **5/5** |
| `test_customer_detail_slim_photos.py` (regression) | 3 | **3/3** |
| `test_jobs_projection_excludes_photo_blobs.py` (regression) | 5 | **5/5** |
| **Total** | | **24/24** in 9.46s |

Coverage:
- S3 module: key format + SSE + ContentType, path-traversal rejection, graceful failure on every boto3 exception, 4-branch health self-test.
- Upload path: dual-write with flag on (in-process direct-handler test), dual-write with flag off (live HTTP), wire-strip on response.
- Read path: 302 redirect with flag on + `s3_key` (direct-handler with patched `generate_signed_url`), base64 fallback without `s3_key` (live HTTP).
- Delete path: covered by inclusion in the upload/insert cleanup teardowns; explicit delete-with-s3 assertion deferred to Phase 2 when we exercise real S3 through the migration.
- Admin health endpoint: disabled-by-default state, non-admin 403.

---

## Rollback plan

**Instant** — flip `PHOTOS_S3_ENABLED=false` in `.env` and `supervisorctl restart backend`. Immediately:
- New uploads stop stamping `s3_key`. DB blobs continue as before.
- Public read serves base64 fallback (existing photos with `s3_key` from the enabled window still redirect if the flag is later re-enabled).
- Delete stops trying to remove S3 objects. Any orphaned S3 objects can be swept later.

**Full revert** — revert the two search_replace hunks in `routers/jobs.py`, the `services/jobs_slim_photos.py` strip helper, the `admin_s3_health` router import in `server.py`, and delete `services/aws_s3/`. ~130 LOC total. No DB migration needed; `s3_key` on existing photos becomes dead weight but doesn't break anything.

---

## Follow-up tickets (log only — NOT built this ticket)

1. **`PHOTOS-S3-PHASE-2-MIGRATION`** — Idempotent backfill migration that iterates `photos[]` on every job, uploads `data` to S3 with the canonical key format, stamps `s3_key`, verifies via `check_object_exists`, and reports scanned/uploaded/skipped/failed. Dry-run first. Rate-limited to avoid S3 API throttling. Runs from a super-admin endpoint OR CLI.
2. **`PHOTOS-S3-PHASE-3-REMOVE-BASE64`** — Once Phase 2 backfill is 100% clean AND all consumers (web + mobile) have switched to the public-photo URL exclusively, strip `photos[].data` from the DB and add a `photos.data` inclusion projection guard on the detail endpoint so old clients can still fetch base64 via a compatibility shim if needed. Timeline: after mobile TestFlight rolls the URL-based photo strip build.
3. **`S3-BYO-PER-TENANT`** — Consider promoting S3 to a per-tenant BYO integration (like Stripe/Resend/RingCentral) so multi-tenant deployments can bill their own AWS. Low priority — the single platform-wide bucket + prefix-by-tenant-id key layout is fine for the current single-tenant Vistancia install.
4. **`S3-HEALTH-DASHBOARD-TILE`** — Surface the `/api/admin/s3/health` result in an admin UI tile (green/yellow/red pill + roundtrip_ms + last-check timestamp). Low priority — CLI/curl is fine for Phase 1 ops.

---

## Constraints honored

- No prod endpoints touched.
- No `Save-to-GitHub`.
- No `/app/mobile/` edits.
- `photo_count` / `photo_ids` wire contract preserved (Mongo dot-notation `photos.data` projection unchanged; new `s3_key` field is a superset that never ships to wire).
- `photos.data` projection sweep from §8 preserved — the S3 module reads photos via the same DB path that already excludes `data`; only the upload path fetches full docs (needed to read the base64 blob for S3 upload).
- Flag OFF by default — operator explicitly opts in after populating creds.
- Small, reviewable diff — one new service module, one new health router, three surgical hunks in `jobs.py`, one helper in `jobs_slim_photos.py`.
- STOP-and-flag rule honored: photo upload primitive was NOT deeply coupled to `photos[].data` — dual-write was a clean addition. No refactor needed. No Phase 0 required.
- No `bbeck169/Pool-Landscaping.git` shenanigans.

---

## One-line orchestrator summary

> Photos-in-S3 Phase 1 shipped: feature-flagged (`PHOTOS_S3_ENABLED=false` by default), dual-write on upload, 302-redirect reads via presigned URL, dual-delete, admin health endpoint at `GET /api/admin/s3/health`. `s3_key` never leaks over the wire. 24/24 tests green. Operator flips the flag + adds AWS creds + restarts backend to activate — zero prod impact until then.

---
## Activation follow-up (Feb 2026)

**Fix**: `services/aws_s3/photos.py::_client()` now builds boto3 with
`Config(signature_version="s3v4", s3={"addressing_style": "virtual"})`.

**Why**: Without this, boto3 emits presigned URLs against the legacy
global host `<bucket>.s3.amazonaws.com`. S3 responds with a 307
PermanentRedirect to the region-specific vhost, but following the
redirect changes the `Host` header — breaking the SigV4 signature
and returning 403 SignatureDoesNotMatch. Forcing virtual-host
addressing makes boto3 emit the region-specific vhost
(`<bucket>.s3.<region>.amazonaws.com`) directly.

**Verified live on preview**:
- `/api/admin/s3/health` → `status: healthy`, roundtrip 322ms.
- 67-byte PNG uploaded via `POST /api/jobs/{jid}/photos`.
- Mongo photo doc carries `s3_key` + `s3_mime` (stripped from wire).
- Object landed in `s3://emergant/Photos/{tenant}/{jid}/{pid}`,
  ContentType=image/png, SSE=AES256.
- `GET /api/public/job-photo/{jid}/{pid}` → 302 → signed URL on
  `emergant.s3.us-east-2.amazonaws.com`.
- Signed URL fetch → HTTP 200, 67 bytes, sha1 matches uploaded.

**IAM policy attached to user `Emergant`** grants:
- `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` on
  `arn:aws:s3:::emergant/Photos/*`.
- `s3:ListBucket`, `s3:GetBucketLocation` on `arn:aws:s3:::emergant`.
- (`HeadObject` intentionally omitted per user — health check
  uses PutObject → HeadObject → DeleteObject. HeadObject uses
  `s3:GetObject` permission at the API level, so it still works.)
