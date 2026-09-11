# Photos-in-S3 · base64-skip on the write path

**Status**: shipped (code) · flag still OFF on preview · Feb-2026

## Root cause

Phase-1 introduced dual-write on `POST /api/jobs/{jid}/photos`: every
upload writes the full base64 payload into `db.jobs.photos[].data` AND
best-effort uploads original + thumb + preview to S3. That was
correct for the migration ramp (nothing could break the DB path), but
once we flip `PHOTOS_S3_ENABLED=true` in production we'd be paying
2x storage (Mongo blob + S3 object) forever unless the write path
learns to skip the DB blob when S3 is authoritative.

## Behavior — three-way branch

The write path in `routers/jobs.py::add_job_photo` now branches on:

```
_s3_flag_on         = _is_configured(_cfg())   # bool
_s3_puts_succeeded  = ["original"?, "thumb"?, "preview"?]
_s3_puts_failed     = [...]
```

| Case | `_s3_flag_on` | succeeded | failed | Persisted shape | Audit row? |
|---|---|---|---|---|---|
| A · Flag OFF | `False` | — | — | `data` + embedded base64 `thumb`/`preview` (unchanged) | no |
| B · Flag ON, all OK | `True` | `{original, thumb, preview}` | `[]` | `s3_key` + `s3_thumb_key` + `s3_preview_key` + `s3_mime`, **`data` DROPPED** | no |
| C · Flag ON, partial fail | `True` | subset | non-empty | `data` retained + any `s3_*` keys that succeeded | **yes** — `photos.s3_upload_partial_failure` |
| D · Flag ON, total fail | `True` | `[]` | `{original, thumb, preview}` | `data` retained, no `s3_*` keys | **yes** |

## Rationale per case

- **A (Flag OFF)**: Preserves the pre-flip contract exactly. Legacy
  clients continue to read `photos[].data` verbatim.
- **B (Flag ON + all OK)**: The write path commits to S3 as the sole
  store of the payload. Mongo doc keeps only lightweight metadata +
  `s3_*` keys. Read path (unchanged) already prefers `s3_preview_key`
  → `s3_key` → `data`, so removing `data` is safe when the two S3
  derivatives are present.
- **C (Flag ON + partial fail)**: A single flaky S3 call must NEVER
  cause a photo to be lost. We keep `data` (durability) AND stamp
  whichever `s3_*` keys did succeed (observability). An audit row
  fires so ops can spot chronic flake without waiting on user
  complaints.
- **D (Flag ON + total fail)**: Identical durability guarantee as C.
  No `s3_*` keys are stamped since none succeeded; the row is
  functionally identical to the flag-off shape.

## Read path — UNCHANGED

`GET /api/public/job-photo/*` and `GET /api/jobs/{jid}` already
implement the correct fallback: prefer `s3_preview_key` → `s3_key` →
`data`. Phase-1 tests lock that behavior. No edits to the read path
in this ship.

## Test matrix

New file: `tests/test_photos_s3_base64_skip.py`

| # | Test | Case | Asserts |
|---|---|---|---|
| 1 | `test_upload_flag_off_writes_base64_unchanged` | A | `data` present, no `s3_*` keys, no audit row |
| 2 | `test_upload_flag_on_success_skips_base64` | B | `data` absent, all three `s3_*` keys present, no audit row |
| 3 | `test_upload_flag_on_partial_failure_falls_back_to_base64` | C | `data` present, `s3_key` + `s3_thumb_key` present, `s3_preview_key` absent, exactly one audit row with `preview` in `s3_puts_failed` and `original`+`thumb` in `s3_puts_succeeded` |
| 4 | `test_upload_flag_on_total_failure_falls_back_to_base64` | D | `data` present, no `s3_*` keys, audit row with all three keys in `s3_puts_failed` |
| 5 | `test_upload_flag_on_success_row_shape_still_readable` | B | row-shape smoke: identity fields present, `strip_s3_metadata_from_photos` still runs clean on the shrunk shape |

Updated file: `tests/test_photos_s3_phase1.py`
- `test_upload_stamps_s3_key_when_flag_on` — inverted the
  `data`-retention assertion to match the new contract. The suite's
  header docstring (invariant #2) was also updated.

## Follow-up

- **Phase-3 base64 purge migration**: After ~1-week soak on prod
  with the flag flipped and this ship live, run a one-shot
  admin migration that scans `db.jobs.photos[]` for rows with both
  `s3_key` AND `data` present, verifies the S3 object exists (HEAD),
  and `$unset`s `data`. Then delete the legacy base64 fallback
  branch in `services/aws_s3/photos.py::_serve_or_fallback`.

## Flag flip runbook (do NOT execute here — separate dispatch)

1. Append `PHOTOS_S3_ENABLED=true` to `/app/backend/.env`.
2. `sudo supervisorctl restart backend`.
3. Verify: `curl -H "Authorization: Bearer $TOKEN" $API/admin/s3/health`
   returns `enabled: true, status: "ok", self_test: {...ok...}`.
4. Sanity: upload one photo through the app UI, check that the new
   `db.jobs.photos[$0]` row on the resulting doc has `s3_key` /
   `s3_thumb_key` / `s3_preview_key` and NO `data` field.
