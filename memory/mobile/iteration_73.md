## Iteration 73 — Phase 2 Follow-up: Three Missing Wire-ups

### What was implemented

1. **Checklist autosave → `offlineWrite()` integration complete**
   - `flushSave()` at line 410 now destructures `{ data, queued }` from `offlineWrite()`
   - When `offlineWrite` falls back to queue mid-request, returns `{ ok: true, queued: true }`
   - Autosave pill shows "Saved — will sync when online" when `!online` instead of just "Saved"
   - Close-job offline alert title changed to "Saved — will sync when online"

2. **Mark Job Complete → `offlineWrite()` with `job.complete` op_type**
   - `setStatus("completed")` in `[id].tsx` now uses op_type `"job.complete"` (not generic `"job.status"`) when status is "completed"
   - Added `Alert.alert("Saved — will sync when online")` toast on queued writes
   - Optimistic UI fires immediately: `setJob({ ...job, status })` + `cacheJob(optimistic)` before any network response
   - Added `Alert` import to `react-native` import line

3. **AppState foreground trigger → sync engine**
   - Added `AppState.addEventListener("change")` in `_layout.tsx`
   - On `inactive/background → active` transition: triggers `flushSyncQueue()`, `flushPhotos()`, `flushVideos()`
   - Uses static imports (no `require()`) for `flush`, `flushPhotos`, `flushVideos` from sync barrel
   - Also wired `wireVideoAutoUpload()` in the boot sequence

4. **Test updates**
   - Updated `sync-db.test.ts` to expect `user_version = 2` (was 1, now accounts for v2 migration)
   - Updated test description to mention Phase 2 tables
   - Verified `videos_pending` table is created in the test assertion

### Files changed
- `app/job/[id]/checklist.tsx` — offlineWrite queued handling + pill text
- `app/job/[id].tsx` — job.complete op_type + Alert import + queued toast
- `app/_layout.tsx` — AppState foreground trigger + wireVideoAutoUpload
- `__tests__/sync-db.test.ts` — updated to match v2 migration

### Test results
- 9 suites, 77 tests — ALL PASSING
- 0 regressions
