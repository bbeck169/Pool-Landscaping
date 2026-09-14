# Feature: Technician Check-In flow — Backend

**Date**: Feb-2026
**Status**: Backend complete. Paired with parallel mobile work by
`e1_expo_frontend_dev` on the Job-Detail "Log Check-in" UI.

This memo captures the backend contracts that the mobile client
must adhere to. Also documents the fix for the long-standing bug
where approved public check-ins never appeared on the public map
(missing `lat_public` / `lng_public` on the moderation-queue row).

---

## 1. Endpoint contracts

### 1.1 `POST /api/files/upload` — photo pre-upload

Photos must be uploaded FIRST via the shared file-upload endpoint
before referencing them from `POST /api/checkins`.

| Multipart field | Required | Value |
| --------------- | -------- | ----- |
| `file` | yes | Image bytes. `image/*` content-type. |
| `purpose` | yes | `public_checkin` |
| `linked_entity_type` | yes | `public_checkin` |
| `linked_entity_id` | no | Optional — the check-in id, when known. Omitted for the pre-upload flow. |

Response (200):

```json
{
  "id": "file-abc",
  "storage": "s3",              // ← Feb-2026: explicit backing marker
  "storage_path": "aquaterra/…/photo.png",
  "content_type": "image/png",
  "size": 12345,
  "purpose": "public_checkin",
  "linked_entity_type": "public_checkin",
  "url": "https://.../api/files/file-abc/inline"
}
```

The endpoint is S3-only. If Emergent Object Storage isn't
configured for the tenant, it returns **503** — a successful 200
is therefore the guarantee that the row is S3-backed.
`storage='s3'` is written explicitly so downstream consumers
(public map, analytics) can query `db.files.find({storage: 's3'})`
without pattern-matching on `storage_path`.

### 1.2 `POST /api/checkins` — create draft check-in

Request body (Pydantic model `CheckinIn` in `backend/models.py`,
now strict as of Feb-2026):

| Field | Type | Constraint | Notes |
| ----- | ---- | ---------- | ----- |
| `job_id` | `str` | required, min_length=1 | The workorder/job this check-in belongs to. Must exist for the caller's tenant. |
| `latitude` | `float` | required, -90..90 | Tech's GPS capture. Legacy alias `lat` still accepted (via `AliasChoices`). |
| `longitude` | `float` | required, -180..180 | Same — legacy alias `lng` accepted. |
| `note` | `str` | required, 1..2000 chars | Free-text description. LLM rewrites this before the public feed. |
| `photo_file_ids` | `List[str]` | required, 1..5 items | Ids returned by `/api/files/upload`. |
| `address` | `str` | optional | Human-readable address for the dashboard row. |

RBAC: `technician`, `admin`, `super_admin` only. Customers → 403.
This check runs BEFORE the payload validator.

Photo-id gates (all return **422** with a structured `detail`):

| Failure | `detail.code` |
| ------- | ------------- |
| Same id appears twice in the array | `PHOTO_FILE_IDS_DUPLICATE` |
| An id doesn't exist for this tenant | `PHOTO_FILE_IDS_INVALID` (+ `missing[]`) |
| An id was uploaded with the wrong `purpose` | `PHOTO_FILE_IDS_WRONG_PURPOSE` (+ `wrong_purpose[]`) |

Response (200) — the full inserted document:

```json
{
  "id": "chk-xyz",
  "tenant_id": "…",
  "technician_id": "…",
  "technician_name": "Ana",
  "status": "draft",
  "job_id": "job-abc",
  "latitude": 33.7801,
  "longitude": -112.3428,
  "note": "Cleaned pump basket, balanced chemistry.",
  "photo_file_ids": ["file-abc"],
  "address": "",
  "created_at": "2026-02-14T15:30:00Z"
}
```

### 1.3 `POST /api/checkins/{id}/submit-public` — enqueue for review

Same shape as before (`PublicCheckinSubmitIn`). Body:

```json
{
  "publish_to_website": true,
  "photo_license_ack": true,
  "description": "SEO-friendly write-up (optional override)",
  "tags": []
}
```

Response (200):

```json
{"public_checkin_id": "pub-uvw", "state": "pending_review"}
```

**Feb-2026 fix** — every `public_checkins` row now carries the
map-pin fields the widget endpoint needs. Without these, the
`_row_is_pinnable` gate in `routers/public_checkins_map.py`
silently skipped the pin even after admin approval.

New fields on the row (all populated by `submit-public`):

| Field | Source | Notes |
| ----- | ------ | ----- |
| `lat_raw`, `lng_raw` | Check-in's own GPS → fallback: customer geocode | Admin-only. Never leaves the moderation UI. |
| `lat_public`, `lng_public` | `obfuscate_coords(lat_raw, lng_raw, seed=str(checkin_id))` | Public map pin. |
| `area_label` | `"City, ST"` from the customer address | Tooltip text. |
| `completed_at` | Job's `completed_at` / `closed_at` → fallback: check-in `checked_out_at` / `created_at` | Absolute ts for sorting. |
| `completed_at_month_year` | `"Month YYYY"` snapshot of `completed_at` | Never leaks specific day. |
| `source` | `"tech"` (always for this endpoint) | Distinguishes from `source="auto"` created by the on-job-complete enqueue. |

Also flips the source `checkins` row:
`status='draft'` → `status='submitted'`, with
`public_checkin_id` + `submitted_at` set. The mobile Job-Detail
screen can now render "Submitted for review" and gate the button.

### 1.4 Admin moderation queue

`GET /api/admin/moderation/public-checkins?state=pending_review`
returns the newly-submitted rows. No new route added — this
endpoint already existed and correctly surfaces the rows once
their state is `pending_review`.

`POST /api/admin/moderation/public-checkins/{id}/approve` flips
state to `approved`. After this, the row satisfies the public
feed inclusion criterion (see §3 below).

---

## 2. Coordinate obfuscation

Delegated to `services/coord_obfuscator.py::obfuscate_coords`.
The tech-submit path and the auto-enqueue path both call this
helper so the pin lands at the same public coordinates regardless
of which surface enqueued the check-in.

Algorithm (recap — no change in this phase):

1. Round raw coords to **3 decimal places** (~111 m grid).
2. Apply a deterministic ±0.001° jitter derived from
   `hashlib.blake2b(seed).digest()[0:8]` where the seed is the
   check-in id. Same `(lat, lng, seed)` → same `(lat_public,
   lng_public)` every time — so a scrape-twice-and-average
   attack can't reveal the raw coord.
3. Round the jittered result to 6 decimal places.

Test coverage:

* `test_submit_public_persists_public_coords` — asserts the row
  carries non-null public coords within ±0.001° of the raw pair.
* `test_submit_public_is_deterministic_per_checkin` — asserts
  a second call for the same check-in id produces identical
  public coords.

---

## 3. Public feed inclusion criterion

Defined in `routers/public_checkins_map.py::_row_is_pinnable`
(pre-existing, verified by test).

A row appears on the widget map **iff ALL of**:

* `state == "approved"`
* `lat_public is not None`
* `lng_public is not None`

`test_public_feed_excludes_rows_without_public_coords` guards
this — a hand-crafted `state='approved'` row with `lat_public=None`
is rejected, and a `state='pending_review'` row with coords is
also rejected. Only the approved-AND-coord'd row is pinnable.

---

## 4. Moderation state machine

```
                       ┌───────────────────────────┐
POST /api/checkins ──▶ │ checkins.status = draft   │
                       └────────────┬──────────────┘
                                    │
              POST /api/checkins/{id}/submit-public
                                    ▼
              ┌─────────────────────────────────────────┐
              │ public_checkins.state = pending_review  │
              │ checkins.status       = submitted       │
              │ + lat_public / lng_public populated     │
              └──────────────┬──────────────────────────┘
                             │
          POST /api/admin/moderation/public-checkins/{id}/approve
                             ▼
              ┌─────────────────────────────────────────┐
              │ public_checkins.state = approved        │
              │ row appears on widget map               │
              └─────────────────────────────────────────┘

  POST /api/admin/moderation/public-checkins/{id}/reject
                             ▼
              ┌─────────────────────────────────────────┐
              │ public_checkins.state = rejected        │
              │ never appears on widget map             │
              └─────────────────────────────────────────┘

  POST /api/admin/moderation/public-checkins/{id}/unpublish
                (from any state after approval)
                             ▼
              ┌─────────────────────────────────────────┐
              │ public_checkins.state = unpublished     │
              │ (soft-hidden, keeps audit trail)        │
              └─────────────────────────────────────────┘
```

Only `state == "approved"` is pinnable on the widget map. Every
other terminal state is hidden.

---

## 5. Curl recipes

Full end-to-end flow. Substitute `$T` with a fresh Bearer token
for a technician / admin / super_admin.

```bash
API="$REACT_APP_BACKEND_URL/api"

# 1. Login → grab a Bearer token
T=$(curl -sX POST "$API/auth/login" \
       -H 'Content-Type: application/json' \
       -d '{"email":"super@aquaterra.com","password":"password123"}' \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# 2. Upload a photo (repeat 1..5 times for multi-photo check-ins)
FID=$(curl -sX POST "$API/files/upload" \
       -H "Authorization: Bearer $T" \
       -F "file=@/tmp/checkin.png;type=image/png" \
       -F "purpose=public_checkin" \
       -F "linked_entity_type=public_checkin" \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

# 3. Create the draft check-in
CID=$(curl -sX POST "$API/checkins" \
       -H "Authorization: Bearer $T" \
       -H 'Content-Type: application/json' \
       -d "{\"job_id\":\"job-abc\",\"latitude\":33.7801,\"longitude\":-112.3428,\"note\":\"Cleaned pump basket.\",\"photo_file_ids\":[\"$FID\"]}" \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

# 4. Submit for public review — this is the step that now writes
#    lat_public / lng_public onto the moderation row.
PID=$(curl -sX POST "$API/checkins/$CID/submit-public" \
       -H "Authorization: Bearer $T" \
       -H 'Content-Type: application/json' \
       -d '{"publish_to_website":true,"photo_license_ack":true}' \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["public_checkin_id"])')

# 5. Admin approves → row becomes pinnable on the widget map.
curl -sX POST "$API/admin/moderation/public-checkins/$PID/approve" \
     -H "Authorization: Bearer $T" \
     -H 'Content-Type: application/json' \
     -d '{"reviewer_notes":"LGTM"}'

# 6. Widget map pins (public — no auth) — the just-approved row
#    should appear here.
TENANT_SLUG="aquaterra"
curl -s "$API/public/checkins/$TENANT_SLUG/pins?window_days=90"
```

---

## 6. Files touched

| File | Change |
| ---- | ------ |
| `backend/models.py` | Tightened `CheckinIn` — required fields, coord bounds, note length, photo_file_ids 1..5, `AliasChoices` for legacy `lat`/`lng`. |
| `backend/routers/marketing.py` | `create_checkin` now validates each photo id (existence, uniqueness, purpose), persists `status='draft'`, uses `model_dump()` instead of Pydantic-v1 `dict()`. |
| `backend/routers/public_checkins.py` | `submit_public_checkin` now resolves `lat_raw`/`lng_raw` (check-in GPS → customer fallback), calls `obfuscate_coords`, writes `lat_public` / `lng_public` / `area_label` / `completed_at` / `completed_at_month_year` / `source='tech'` on the row, and flips the source `checkins.status` to `submitted`. |
| `backend/routers/files.py` | Every uploaded file record now carries `storage='s3'` for queryability. |
| `backend/tests/test_iteration8_phase5_6_marketing_ai.py` | Legacy check-in tests updated to reflect the tightened contract (422 for legacy shape; RBAC still 403 for customers). |
| `backend/tests/test_tech_checkin_flow.py` | **NEW** — 15 tests covering create validation × 8, happy path × 4, feed criterion × 1, storage marker × 1, moderation queue × 1. |
| `memory/FEATURE_TECH_CHECKIN_BACKEND.md` | This memo. |

---

## 7. Test status

* **Backend targeted sweep** (this phase + adjacent):
  `pytest tests/test_tech_checkin_flow.py tests/test_public_checkins.py tests/test_iteration8_phase5_6_marketing_ai.py tests/test_public_checkins_auto_enqueue_on_completion.py tests/test_public_checkins_auto_enqueue_no_index_collision.py tests/test_public_checkins_source_field.py tests/test_portal_chat_attachments.py tests/test_file_storage.py tests/test_public_quote_attachments.py`
  → **78 passed, 34 skipped, 0 failed**.
* `test_user_profile_photo.py` has 2 pre-existing failures on
  admin cross-tenant PATCH — verified with `git stash` that they
  reproduce on the baseline. Unrelated to this phase.
* **OpenAPI paths**: **1738** (unchanged — no new routes added,
  existing endpoints tightened in-place).
* Legacy pre-existing pytest failures in `test_service_report*`
  and `test_chemistry_required_readings_gate.py` remain deferred
  per prior direction (untouched here).

---

## 8. Out of scope (this phase)

* Any mobile-side change (mobile team handles in parallel).
* JSON-LD SEO on the public feed (separate queued phase).
* AI description button (separate queued phase).
* Photo thumbnail generation server-side (public map still uses
  the full-resolution S3 URL with `loading="lazy"`).
* Any A–F backlog items.
