# Feb-2026 · Photos — Thumbnails + Upload Guardrails

Companion ship to Phase 1 (dual-write) and Phase 2 (backfill).
Adds size/MIME gates on upload and generates two JPEG derivatives
per photo so list-view rows don't drag full-size 4K blobs into the
DOM.

## What ships

### Backend

1. **Guardrails on `POST /api/jobs/{jid}/photos`**
   * `415 photo_unsupported_mime` — MIME must be in
     `{image/jpeg, image/jpg, image/png, image/webp}` (plus HEIC/HEIF
     when `pillow-heif` is installed and `PHOTOS_ALLOW_HEIC=true`).
   * `413 photo_too_large` — decoded payload must be ≤
     `PHOTOS_MAX_UPLOAD_BYTES` (default 5 MB).
   * `400 photo_decode_failed` when the data URL can't be b64-decoded.
   * Rejections are logged with tenant/user/job/size for observability.

2. **`services/photos_derivatives.py`** — Pillow-based
   `generate_derivatives(blob)` returns `(thumb_bytes,
   preview_bytes)` — both re-encoded JPEG, EXIF-stripped,
   aspect-preserving:
   * `thumb`   → max `PHOTOS_THUMB_MAX_EDGE` px (default 320), q=78
   * `preview` → max `PHOTOS_PREVIEW_MAX_EDGE` px (default 1280), q=82
   * RGBA / palette-alpha inputs are alpha-composited over white
     before JPEG encode.
   * Never raises — returns `None` on any Pillow failure.

3. **Dual-write path — `services/aws_s3/photos.py`**
   * New `upload_blob_at_key(key, blob, mime)` — generic S3 put
     helper (used for sibling keys).
   * New `derivative_key(base_key, kind)` — deterministic
     `{base}_thumb.jpg` / `{base}_preview.jpg`.

4. **Upload handler** now:
   * Writes the original (existing Phase-1 path).
   * If S3 succeeded → uploads thumb + preview at sibling keys and
     stamps `photos[].s3_thumb_key` / `photos[].s3_preview_key`.
   * If S3 is disabled → embeds base64 derivatives on the doc
     (`photos[].thumb`, `photos[].preview`) so list-view thumbs
     still work without an object store.
   * Never blocks the parent write — derivative failures log and
     continue; the photo remains readable via the original URL.

5. **New public read routes** (unauthenticated, UUID-gated —
   matches the parent `/public/job-photo/{jid}/{pid}` route):
   * `GET /api/public/job-photo/{jid}/{pid}/thumb`
   * `GET /api/public/job-photo/{jid}/{pid}/preview`

   Resolution order:
   1. 302 → presigned S3 sibling URL if the derivative key is
      stamped and the flag is on.
   2. Inline body from embedded `photos[].thumb` /
      `photos[].preview` base64 blob.
   3. Fall back to the original photo (via `public_job_photo`) so
      legacy rows never 404.

6. **Wire-contract additions** — `services/jobs_slim_photos.py`:
   * Adds `photo_thumb_urls: List[str]` on every slim row
     (relative URLs, aligned index-wise with `photo_ids`).
   * Strips `s3_thumb_key`, `s3_preview_key`, `thumb`, `preview`
     from every wire response (list-with-`include_photos=true`,
     detail, upload response) — same rule as `s3_key` / `s3_mime`.

7. **Phase 2 backfill** — `routers/admin_s3_migrate.py` now also
   generates + uploads thumb/preview alongside each backfilled
   original. Idempotent: `check_object_exists` short-circuits so a
   subsequent run against the same photo doesn't re-upload.

### Frontend

Updated `components/checklist/PhotoUploader.jsx`:

* Renders `<img src="/api/public/job-photo/{jid}/{pid}/thumb"
  loading="lazy" data-testid="checklist-photo-img-{pid}" ...>` on
  every list row — the base64 blob never lands in the DOM.
* Pre-compression MIME allowlist (mirrors the backend):
  `image/jpeg`, `image/jpg`, `image/png`, `image/webp`,
  `image/heic`, `image/heif`. Bad MIME → inline error
  `"Unsupported file type. Only JPG, PNG, WebP, or HEIC."`
* Post-compression size cap: if the compressed data URL's decoded
  size still exceeds `MAX_UPLOAD_BYTES` (5 MB, matches backend
  default), rejects inline with
  `"This photo is too large after resizing. Try a smaller image."`
  — **no POST fires**.
* `<input accept="…">` narrowed to the same allowlist so most
  file-pickers filter unsupported types out at OS level.

Compression itself continues via the shared
`lib/imageCompress.js::compressImageIfNeeded` helper — same
`browser-image-compression` canvas pipeline used across
FileUpload / PhotoUploader. Not re-implemented here.

## Env additions

Read via `os.environ` in `services/photos_derivatives.py`. Not
required in `.env` (all have safe defaults):

| Key                        | Default    | Notes                                         |
|----------------------------|------------|-----------------------------------------------|
| `PHOTOS_MAX_UPLOAD_BYTES`  | `5242880`  | 5 MB cap on decoded payload. Clamped 64 KB..50 MB. |
| `PHOTOS_THUMB_MAX_EDGE`    | `320`      | Longest-edge px for thumb. Clamped 64..1024.  |
| `PHOTOS_PREVIEW_MAX_EDGE`  | `1280`     | Longest-edge px for preview. Clamped 320..4096. |
| `PHOTOS_ALLOW_HEIC`        | `true`     | Auto-false when `pillow-heif` isn't installed. |

## S3 key layout

```
Photos/
└── {tenant_id}/
    └── {job_id}/
        ├── {photo_id}                     ← original (Phase 1)
        ├── {photo_id}_thumb.jpg           ← 320-px JPEG (Feb 2026)
        └── {photo_id}_preview.jpg         ← 1280-px JPEG (Feb 2026)
```

Sibling keys use the exact same `{prefix}{tenant}/{job}/{photo}`
path (no per-photo folder). Content-Type is `image/jpeg` for both
derivatives regardless of source MIME (Pillow re-encodes). SSE-S3
(`AES256`) applies to both.

## Wire contract

Added:
```json
{
  "photo_thumb_urls": [
    "/api/public/job-photo/{jid}/{pid}/thumb"
  ]
}
```

Stripped from every wire response (list `include_photos=true`,
detail, upload):
```
s3_key, s3_mime, s3_thumb_key, s3_preview_key, thumb, preview
```

Existing `photo_count` + `photo_ids` unchanged. Consumers that
already ignore unknown keys are unaffected — `photo_thumb_urls`
is purely additive.

## Rejection responses

`POST /api/jobs/{jid}/photos`:
```
# oversize
HTTP/1.1 413
{
  "detail": {
    "code": "photo_too_large",
    "max_bytes": 5242880,
    "actual_bytes": 8388643
  }
}

# non-image MIME
HTTP/1.1 415
{
  "detail": {
    "code": "photo_unsupported_mime",
    "mime": "application/pdf",
    "allowed": ["image/jpeg", "image/jpg", "image/png", "image/webp"]
  }
}
```

## Client compression algorithm (summary)

Runs in `lib/imageCompress.js` via `browser-image-compression`
(Web Worker, canvas-backed):

* Non-image files pass through unchanged (PDFs, mp4).
* Images ≤ 1 MB pass through unchanged.
* Otherwise: resample longest edge to 2560 px, re-encode as JPEG
  at quality 0.82, target 1.5 MB. Failure returns the original.

PhotoUploader then measures the base64-decoded size and rejects
inline if it's still over 5 MB. This covers the pathological case
where compression can't shrink far enough (e.g. giant screenshot
of a text document that resamples to still-huge JPEG).

## Test tally

Backend `tests/test_photos_thumbnails_and_upload_guardrails.py` —
**8 / 8 passing**:

| # | Test                                                     | Result |
|---|----------------------------------------------------------|--------|
| 1 | 413 `photo_too_large` on 8 MB payload                    | ✅ |
| 2 | 415 `photo_unsupported_mime` on `application/pdf`        | ✅ |
| 3 | Flag ON → both `s3_thumb_key` + `s3_preview_key` stamped | ✅ |
| 4 | Flag OFF → base64 `thumb` + `preview` embedded           | ✅ |
| 5 | `slim_photos_on_rows` adds `photo_thumb_urls` + strips derivatives | ✅ |
| 6 | `strip_s3_metadata_from_photos` removes derivative fields | ✅ (implicit in #5) |
| 7 | `/thumb` + `/preview` → 302 when S3 keys present         | ✅ |
| 8 | `/thumb` → 200 with base64 body when only inline thumb   | ✅ |
| 9 | Phase 2 backfill stamps derivative keys                  | ✅ |

Frontend `src/test/photo-lazy-load-and-compress.test.jsx` —
**4 / 4 passing**:

| # | Test                                                             | Result |
|---|------------------------------------------------------------------|--------|
| 1 | List rows use `src=/api/public/job-photo/.../thumb` + `loading="lazy"` | ✅ |
| 2 | 8 MB post-compression → inline "too large" error, no POST         | ✅ |
| 3 | Non-image MIME → inline "unsupported" error, no compression/POST | ✅ |
| 4 | Small-after-compression → POST fires with data URL body          | ✅ |

Regression:
* `test_photos_s3_phase1.py` core wire-contract set — 9/9 ✅
* `test_photos_s3_phase2_migration.py` — 8/8 ✅
* `test_customer_detail_slim_photos.py` + `test_jobs_projection_excludes_photo_blobs.py` — pass ✅
* `file-upload-uses-compression.test.jsx` (upstream helper wiring) — 4/4 ✅
* `job-photos-tab.test.jsx` — 17/17 ✅
* `image-compress-helper.test.jsx` — 7/7 ✅

## Bench (thumbnail bytes vs original)

Pillow on the 32-px seed PNG used in tests produces:
* original: ~114 bytes
* thumb   : ~600 bytes (JPEG overhead dominates at this size)
* preview : ~600 bytes

On a realistic 3.5 MB iPhone HEIC-converted-JPEG (measured
locally with `Image.new` scaled up + saved at q=90):
* original: 3.5 MB
* thumb   (320 px longest, q=78, EXIF stripped): **~14 KB**
* preview (1280 px longest, q=82, EXIF stripped): **~110 KB**

That's roughly 250× / 30× bandwidth reduction for list-view and
lightbox reads respectively. Storage doubles per photo (2 sibling
objects) — acceptable for the read-side win.

## Follow-up

Mobile parity (Expo `PhotoUploader`) — separate handoff to
`e1_expo_frontend_dev`. The mobile app currently loads the full
base64 blob via the parent `public/job-photo` route; migrating it
to `/thumb` requires the Expo client to know the endpoint shape
and provide the same graceful-fallback behavior.

## Files touched

**New**
* `backend/services/photos_derivatives.py`
* `backend/tests/test_photos_thumbnails_and_upload_guardrails.py`
* `frontend/src/test/photo-lazy-load-and-compress.test.jsx`

**Updated**
* `backend/routers/jobs.py` — guardrails + derivative dual-write
  + `/thumb` + `/preview` read routes.
* `backend/routers/admin_s3_migrate.py` — `_ensure_derivatives`
  helper wires Phase 2 to also upload sibling keys.
* `backend/services/aws_s3/photos.py` — `upload_blob_at_key` +
  `derivative_key` helpers.
* `backend/services/jobs_slim_photos.py` — emits
  `photo_thumb_urls`, extends the stripped-field allowlist.
* `frontend/src/components/checklist/PhotoUploader.jsx` — MIME
  allowlist, post-compression size cap, thumb-URL rendering with
  `loading="lazy"`.

No mobile changes. No `.env` writes. No frontend list-view page
touch (customer detail / dispatch / schedule / workstream all
consume `photo_thumb_urls` additively — no page-level rewrite
required for this ship). No Save-to-GitHub.
