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

---

## §7 · Feb-2026 batch extension — schedule routers + jobs.py broader coverage

**Trigger**: User requested extending the slim-photos treatment to ALL list-shaped `db.jobs.find()` / `db.jobs.aggregate()` calls in:
- 9 schedule-page routers (Task 2).
- The rest of `backend/routers/jobs.py` beyond `GET /api/jobs` (Task 3 addendum).

**Global preconditions verified**:
- Grep for `photos.$size` across the entire backend → **zero hits**. No aggregation depends on server-side photos length; safe to project photos out anywhere the receiving code doesn't read it.
- Grep for `/api/jobs/{id}` detail path — **untouched by this pass** per user's constraint.

### 7.1 Ship classification (per user's own rule)

The user's ticket carried a mandatory rule: *"If the router's RESPONSE already hand-picks fields (like workstream.py did) and never emits `photos` on the wire → SKIP-AND-NOTE. Do NOT force a projection change."*

Every list-shaped call in the enumerated files was inspected. The result — **every one hits SKIP-AND-NOTE**:

| Router · line | List surface | Wire emits `photos`? | Verdict |
|---|---|---|---|
| `routers/schedule.py:160` | `GET /schedule/today` job list | ❌ No — cherry-picks `items[]` at L201-237 (no `photos` key ever set) | SKIP-AND-NOTE |
| `routers/dispatch_board.py:357` | `GET /dispatch-board` fallback jobs | ❌ No — projection `{id, customer_id, customer_name, title, service_type, address, status, route_index, scheduled_start, scheduled_date}` already excludes `photos` at Mongo boundary | SKIP-AND-NOTE (already Mongo-slim) |
| `routers/dispatch.py:169` | `POST /dispatch/rank` today's jobs | ❌ No — projection `{id, technician_id, scheduled_date, scheduled_start, site_lat, site_lng, lat, lng}` already excludes | SKIP-AND-NOTE (already Mongo-slim) |
| `routers/dispatch.py:417` | Weather-reschedule scan | ❌ No — response cherry-picks `event` dict (L456+); `photos` never copied | SKIP-AND-NOTE |
| `routers/schedule_reorder.py:155, 197, 284` | Reorder day-lists | ❌ No — all three explicitly project only `id`/`status`/`customer_id`/etc. | SKIP-AND-NOTE (already Mongo-slim) |
| `routers/instaschedule.py:297` | Available-slot conflict scan | ❌ No — projection `{scheduled_start}` only | SKIP-AND-NOTE (already Mongo-slim) |
| `routers/dispatch_route_insert.py:134` | Un-scheduled candidate list | ❌ No — projection `{id, title, address, ...}` explicit inclusive | SKIP-AND-NOTE (already Mongo-slim) |
| `routers/dispatch_route_insert.py:183, 232, 303` | Route-order reload | ❌ No — response builds `final[]` with `{job_id, address, lat, lon, sequence}` cherry-pick | SKIP-AND-NOTE |
| `routers/dispatch_route_optimize.py:170` | Route-optimize nearest-neighbor input | ❌ No — response is `ordered_jobs` tour with `{job_id, lat, lon, address}` cherry-pick | SKIP-AND-NOTE |
| `routers/jobs.py:588` | (inside the already-slim `GET /api/jobs` — same helper) | N/A | (already treated in earlier ship) |
| `routers/jobs.py:1490` | `GET /jobs/customer/{cid}/field-report` entries | ❌ No — cherry-picks `readings`/`chemicals`/`title`/`date`/... | SKIP-AND-NOTE |
| `routers/jobs.py:3171` | `GET /reports/timer` rows | ❌ No — cherry-picks `row` dict with 15 explicit fields | SKIP-AND-NOTE |
| `routers/jobs.py:3215` | `GET /reports/avg-job-time` | ❌ No — projection `{customer_id, timer_duration_seconds, timer_stopped_at, scheduled_date}` already excludes | SKIP-AND-NOTE (already Mongo-slim) |
| `routers/jobs.py:3333` | `GET /reports/job-margin-leaderboard` | ❌ No — cherry-picks `rows[]` with 9 explicit fields | SKIP-AND-NOTE |
| `routers/jobs.py:3408` | `GET /reports/least-profitable-services` | ❌ No — cherry-picks `agg` bucket per service_type | SKIP-AND-NOTE |
| `routers/jobs.py:3469` | Service-week bucketing report | ❌ No — projection `{technician_id, technician_name, status, scheduled_date}` already excludes | SKIP-AND-NOTE (already Mongo-slim) |

**Ship footprint on wire-shape: ZERO**. Every enumerated surface already had `photos` excluded from the response envelope either via cherry-pick or via a restrictive Mongo projection.

### 7.2 Residual perf opportunity (deferred — matches workstream note)

Six of the surfaces above still fetch the FULL job doc (`{"_id": 0}`) from Mongo and drop `photos` at the response-shape layer. This wastes Mongo→process wire traffic (base64 blobs are streamed but never read by the response builder). Same story as the workstream note in §5 of this memo.

Deferred surfaces:
- `routers/schedule.py:160`
- `routers/dispatch.py:417`
- `routers/dispatch_route_insert.py:183, 232, 303`
- `routers/dispatch_route_optimize.py:170`
- `routers/jobs.py:1490, 3171, 3333, 3408`

Fix pattern (for a future ticket): replace `{"_id": 0}` with `{"_id": 0, "photos": 0}` (Mongo exclusion — 3 characters + 3 = 6 characters per call site). No test-observable behavior change; DB→process bandwidth shrinks proportionally to blob size. Zero risk.

**Not shipped this ticket** because:
1. The user's rule explicitly said SKIP-AND-NOTE when the response already excludes `photos`. This is exactly that scenario.
2. It's a Mongo-side change with no test-tractable behavior surface — the wire is already clean, so no automated regression exists to guard the change.
3. A dedicated `PERF-MONGO-PROJECT-EXCLUDE-PHOTOS-ON-JOBS-READS` ticket would sweep all 10 residual sites in one pass with a `pymongo.monitoring` bench comparison — cleaner than piecemeal.

Follow-up ticket definition preserved in §7.4.

### 7.3 Consumer audit

**Web frontend**: Grepped all schedule/dispatch pages for `job.photos` / `['photos']` on list contexts:
- `frontend/src/pages/schedule/ScheduleMap.jsx` — reads `customers.service_lat/service_lng` for pins, never `job.photos`.
- `frontend/src/pages/dispatch/DispatchBoard.jsx` — reads `job.title`, `job.status`, `job.address`, `job.customer_name`, never `photos`.
- `frontend/src/pages/schedule/*` — no `photos` reads on list rows.

**Zero web consumer breakage** — all schedule/dispatch UI consumers were already reading the cherry-picked fields.

**Mobile (audit only)**: `mobile/src/screens/schedule/*` and `mobile/src/screens/dispatch/*` — read the same cherry-picked fields from the schedule endpoints. No `photos` reads on list rows. **Zero mobile handoff needed** for this batch.

### 7.4 Follow-up tickets (log only — NOT built this ticket)

1. **`PERF-MONGO-PROJECT-EXCLUDE-PHOTOS-ON-JOBS-READS`** — Sweep the 10 residual sites listed in §7.2 with `{"photos": 0}` Mongo exclusions. Zero response-shape impact; DB→process wire traffic shrinks. Bench via `pymongo.monitoring` command-succeeded events before/after.
2. **`SLIM-PHOTOS-HELPER-COVER-WORKSTREAM-MEDIA-SUMMARY`** — Rolled forward from §5; unchanged.
3. **`CHASE-VS-H1-MODAL-CONSOLIDATION`** — Two similarly-shaped bulk-invite modals (Chase for the tile CTA, Phase H1 for CustomersList) now coexist. Consider extracting a shared shell after both flows have stabilized in prod. Small refactor, low priority.

### 7.5 Combined slim-photos test tally (all surfaces)

| Suite | Cases | Pass |
|---|---|---|
| `test_jobs_list_slim_photos.py` (original `/api/jobs` ship) | 5 | ✅ |
| `test_customer_detail_slim_photos.py` (this batch, ship #1) | 3 | ✅ |
| **Total slim-photos** | **8** | **8/8** |

No new tests added in §7 — zero code was shipped there per the rule-driven triage.

### 7.6 Bench recap

- `/api/jobs` list ship (original): ~94.8% payload reduction observed on high-photo tenants.
- `/api/customers/{cid}` embedded jobs (this batch): asserted ≥ 5× ratio in `test_customer_detail_response_size_smaller_than_full_photos`; e2e-observed on real preview data — clean cut (0/8 jobs carry legacy `photos[]` field, all 8 carry `photo_count`).
- Workstream: no wire-shape change (envelope already excluded photos); residual Mongo-side projection opportunity noted.
- Schedule + jobs.py broader coverage: no wire-shape change (all SKIP-AND-NOTE per §7.1); residual Mongo-side projection opportunity noted in §7.2.

### 7.7 Constraints honored

- No prod endpoints touched.
- No `Save-to-GitHub`.
- No `/app/mobile/` edits.
- `/api/jobs/{id}` detail response shape untouched.
- Shared helper `services/jobs_slim_photos.py` was the only pattern used across the shipped surfaces.
- STOP-and-flag rule for `photos.$size` observed (none exist).
- No `bbeck169/Pool-Landscaping.git` shenanigans.

### 7.8 One-line orchestrator summary

> Schedule-router + jobs.py broader slim-photos triage complete: 16 list-shaped surfaces inspected, **all 16 SKIP-AND-NOTE per user's own rule** — every one already cherry-picks response fields or uses a restrictive Mongo projection. Ship footprint on the wire: zero. Residual DB→process bandwidth win deferred to a dedicated `PERF-MONGO-PROJECT-EXCLUDE-PHOTOS-ON-JOBS-READS` ticket. `/api/jobs` list + customer-detail embedded jobs remain the only surfaces that actually needed a response-shape change; both green (8/8 tests).

