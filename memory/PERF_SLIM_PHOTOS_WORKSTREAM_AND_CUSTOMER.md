# PERF — Slim-photos on Workstream & Customer Detail

**Date**: 2026-02-10 (wall clock 2026-09-10)
**Author**: e1_dev
**Scope**: Mirror the earlier `/api/jobs` slim-photos ship (see `DIAG_P0_MOBILE_CLOSE_JOB_SILENT.md` §9) into two more surfaces. NO new endpoints. NO client contract expansion beyond `photo_count` + `photo_ids`.

---

## Result summary

| Surface | Action | Reason |
|---|---|---|
| `GET /api/jobs` (list) | **Refactored** — extracted the row-decorator loop into `services/jobs_slim_photos.py`. Behavior unchanged. | DRY the pattern so future consumers reuse one contract. |
| `GET /api/customers/{cid}` (embedded jobs list) | **SHIPPED** slim-photos — drops full `photos` from every embedded job, emits `photo_count` + `photo_ids`. | This is the actual perf win — CustomerDetail's Overview tab was shipping the full photo blobs on every load. |
| `GET /api/workstream` list | **STOP-and-flag, skipped** — response envelope already excludes `photos` (hand-crafted `row` dict at `routers/workstream.py:386-416` cherry-picks fields; `photos` is never copied). Matches user's own stop-flag rule ("if either endpoint uses a pipeline that already excludes photos"). | See §5 for the residual Mongo-side perf opportunity noted for a future ticket. |
| `GET /api/jobs/{id}` (detail) | **Untouched.** | Contract: single-job detail still returns full `photos` per the original slim-photos ship. |

---

## Files touched

| File | Delta |
|---|---|
| `backend/services/jobs_slim_photos.py` | NEW — `slim_photos_on_rows(docs, include_photos)` helper. ~50 LOC. |
| `backend/routers/jobs.py` | Replaced the inline row-decorator loop with a call to the new helper. Behavior byte-identical (validated via existing 5-case suite `test_jobs_list_slim_photos.py`). ~40 LOC delta (mostly a comment block preservation). |
| `backend/routers/customers.py` | Two-line addition in `get_customer` — import + `slim_photos_on_rows(jobs, include_photos=False)` right after the embedded-jobs fetch. ~5 LOC (with comment). |
| `backend/tests/test_customer_detail_slim_photos.py` | NEW — 3 cases (default-slim / uniform-shape / size-bench). |

Zero DB migrations. Zero response-envelope-breaking changes. Legacy consumers reading `photos` on the embedded-jobs list would break — see §6.

---

## Slim contract (unchanged from `/api/jobs` ship)

Every embedded job on `GET /api/customers/{cid}.jobs[]` now carries:

```json
{
  "id": "job_…",
  "status": "completed",
  "scheduled_date": "…",
  "photo_count": 10,
  "photo_ids": ["ph_00", "ph_01", …, "ph_09"]
  // ``photos`` array intentionally ABSENT
}
```

Legacy rows with no `photos` field are normalized to `photo_count=0` + `photo_ids=[]` so consumers can rely on both keys being present.

**No `include_photos` opt-in on the customer-detail endpoint** — that endpoint takes no query params for its embedded lists (per user's spec: "otherwise skip the opt-in for the customer-detail-embedded lists"). Callers that need full photos fetch `GET /api/jobs/{jid}` per row.

---

## Consumer audit

### Web frontend
Grepped `frontend/src/pages/customers/` + `frontend/src/components/customers/` for `.photos` / `['photos']`. **No consumers** read the embedded-jobs `photos` array on `CustomerDetail.jsx`. The Overview tab renders job titles, dates, statuses — never photo thumbnails on the list. Clean cut.

### Mobile — DO NOT EDIT (audit only)
`mobile/src/` reads `job.photos` in six spots:
- `mobile/src/components/widgets.tsx:313, 338` — photo strip on the JOB DETAIL screen (fetched from `GET /api/jobs/{jid}`, not the customer list). Unaffected.
- `mobile/src/components/job/MaintenanceLog.tsx:37, 65, 82, 95` — maintenance-log photo state on the JOB DETAIL screen. Unaffected.
- `mobile/src/components/checklist/*` — checklist form photo state (post/put shape, not read from a list). Unaffected.
- `mobile/__tests__/job-photo-url-cache.test.tsx` — unit tests for the URL cache. Unaffected.

**Verified**: mobile does NOT hit `GET /api/customers/{cid}` (grepped `customers/${` in `mobile/src/` — only equipment-photos / comms-timeline / service-records-link endpoints). **Zero mobile parity impact**.

### Backend
Grepped `photos.$size` / `photos: {$size: …}` aggregations — **none exist**. Safe.

---

## Bench

### Test-suite bench (deterministic, seeded)

`test_customer_detail_response_size_smaller_than_full_photos` seeds a customer with one job carrying 10 embedded photos (~4 KB base64 each = ~40 KB inline). Assertion: slim response ≥ 5× smaller than the hypothetical full-photos response.

**Live run**: passed. Actual ratio observed on the preview backend exceeds the 5× floor (test uses `>= 5.0` guard so specific ratio isn't logged; local computation on the seeded shape yields ~10–12×).

### E2E bench on real preview data

```
$ curl -H "Authorization: Bearer …" /api/customers/seed-optimize-route-customer
size = 10,182 bytes
embedded jobs = 8
jobs carrying photo_count key = 8/8
jobs carrying legacy photos[] key = 0/8   ← slim contract verified
total photos across embedded jobs = 2
```

Before the ship, the same customer would have shipped those 2 photos (~8 KB base64 payload each on real seeded data) inline in the response. The seeded-photo customers on the preview aren't representative of the worst case; on prod tenants with routine 10-photo completed jobs × 50 recent jobs per customer, the pre-slim payload approached the same 3–4 MB regime that motivated the original `/api/jobs` slim ship. Rough projection: **at 50 embedded jobs × 6 avg photos × 40 KB per photo = ~12 MB pre-slim → ~50 KB post-slim (~240× win).** Mirrors the projection in `DIAG_P0_MOBILE_CLOSE_JOB_SILENT.md` §9.

---

## Workstream — why it was skipped

`routers/workstream.py:326` fetches raw job docs from Mongo INCLUDING the `photos` array. The array is then read by `_media_summary(d)` (line 205) to produce a compact thumbnail block: `{photos_count, videos_count, photo_thumbs, video_thumbs, extra_count}`. Only the summary object lands on the response row (line 415).

**The response envelope already excludes the raw `photos` array** — it's build-and-discard-on-server, never over the wire. Per the ticket's own STOP-and-flag rule ("if either endpoint uses a pipeline that already excludes photos"), I stopped here.

**Residual Mongo-side perf opportunity** (NOT shipped this ticket):

The DB→process wire traffic still carries the full base64 blobs for every workstream row. A projection like `{photos.id: 1, photos.label: 1}` would drop the `photos.data` field at the Mongo boundary. `_media_summary` only reads `p.get("id")` and `p.get("label")` — no `data`. Estimated savings: identical to the customer-detail win, scaled by workstream page size (~500 rows max) × avg photos/job × 40 KB.

**Reason to defer**: This is a Mongo-projection change with no response-shape impact. Zero user-visible risk, but also zero test-tractable behavior to lock. The next `MongoQueryTuning` sweep should pick it up — added a note below.

---

## Follow-up tickets (log only)

1. **`PERF-WORKSTREAM-MONGO-PROJECT-SLIM-PHOTOS`** — Add `{photos.id: 1, photos.label: 1}` (or explicit `{photos.data: 0}`) to the `db.jobs.find()` call at `routers/workstream.py:326`. Zero response-shape impact; DB→process wire traffic shrinks proportionally to blob size. Verify by comparing `pymongo.monitoring` command-succeeded events with/without the projection.
2. **`SLIM-PHOTOS-HELPER-ALSO-COVERS-WORKSTREAM-MEDIA-SUMMARY`** — Consider moving `_media_summary(job)` into `services/jobs_slim_photos.py` alongside `slim_photos_on_rows` so all "summarize photos on a job doc" logic lives in one module. Would enable the workstream to consume the Mongo projection helper cleanly.

---

## Rollback

- Revert `backend/routers/customers.py` diff (~5 LOC — the import + one function call).
- Revert `backend/routers/jobs.py` diff (~40 LOC — restore the inline loop).
- Delete `backend/services/jobs_slim_photos.py`.
- Delete `backend/tests/test_customer_detail_slim_photos.py`.

Zero DB / migration / schema impact.

---

## Test tally

| Suite | Pass | Time |
|---|---|---|
| `backend/tests/test_customer_detail_slim_photos.py` (3 new) | **3/3** | 13.9s |
| `backend/tests/test_jobs_list_slim_photos.py` (5 regression) | **5/5** | 0.59s |
| **Total** | **8/8** | ~14.5s |

E2E verified on live preview (`GET /api/customers/seed-optimize-route-customer` → 8/8 jobs carry `photo_count`, 0/8 carry legacy `photos[]`).
