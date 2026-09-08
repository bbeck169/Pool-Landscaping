## Iteration 72 — Phase 2: Offline Write Queue + Auto-Sync

### What was implemented
1. **Sync Center Screen** (`app/settings/sync-center.tsx`)
   - Full management UI for pending/failed/synced operations
   - Summary card with Online/Offline status, 4 count boxes (Pending, In Flight, Failed, Done)
   - "Sync Now" manual trigger button
   - Per-entry rows with op type labels, timestamps, error messages
   - Retry individual failed items, retry-all for stalled photos/videos
   - Clear done items
   - Empty state: "All synced!"

2. **Global SyncBadge** (`src/components/SyncBadge.tsx`)
   - Tappable pill in schedule header: "⤴ X waiting" / "Syncing…" / "X failed"
   - Uses `useSyncStatus()` for reactive counts
   - Navigates to `/settings/sync-center` on tap
   - Hidden when queue is empty (correct behavior)
   - Added to schedule calendar header next to OfflineBadge

3. **Per-item PendingSyncPill** (`src/components/PendingSyncPill.tsx`)
   - Small amber pill "⤴ Pending sync" on job cards with queued writes
   - Added to JobRow in schedule grid

4. **usePendingOps Hook** (`src/hooks/usePendingOps.ts`)
   - `usePendingOps(entityId)` — count of pending ops for a specific entity
   - `usePendingEntityIds()` — Set of all entity IDs with pending ops
   - Reactive via queue subscription

5. **Video Worker** (`src/services/sync/videoWorker.ts`)
   - Mirrors photoWorker pattern for video attachments
   - 30-second cap enforced (VIDEO_MAX_DURATION_SEC = 30)
   - Stage to `documentDirectory/videos/pending/`
   - Upload via `POST /jobs/{jid}/videos` with idempotency key
   - Auto-upload on reconnect via `wireVideoAutoUpload()`
   - Retry stalled, cleanup uploaded, orphan purge

6. **DB Migration v2** (`src/services/sync/db.ts`)
   - Added `videos_pending` table with status tracking
   - TARGET_VERSION bumped to 2
   - Fully idempotent migration

7. **Concurrency Limiter** (`src/services/sync/queue.ts`)
   - Max 3 concurrent entity syncs (was unlimited)
   - Worker pool pattern using semaphore
   - FIFO per entity preserved

8. **OnMyWay Offline** (`src/components/schedule/OnMyWayButton.tsx`)
   - Wired through `offlineWrite()` wrapper
   - Shows "Queued offline" alert when offline
   - Falls back to queue on network errors mid-request

9. **Cache Invalidation** (`src/services/cacheInvalidation.ts`)
   - Added: `video.upload`, `checklist.answer`, `checklist.update`, `job.complete`, `on_my_way`

10. **Barrel Export** (`src/services/sync/index.ts`)
    - Added all videoWorker exports

### Web-to-mobile mapping decisions
- Sync Center is at `/settings/sync-center` (admin access gate by settings layout)
- SyncBadge is header-level (schedule), not tab-bar level
- Video 30s cap enforced at worker level (expo-image-picker `videoMaxDuration` for capture)
- Tech-wins conflict rule: queue.ts already has 409 conflict detection; server-side enforcement expected

### Known issues / deferred items
- Backend must support `POST /jobs/{jid}/videos` endpoint for video uploads
- Backend must support `X-Idempotency-Key` header for tech-wins conflict resolution
- Checklist answer and job.complete mutations need specific screen-level wiring (the queue infrastructure is ready, the specific screens like checklist.tsx need to call `offlineWrite()`)
- Foreground sync trigger (AppState change) — deferred to later iteration

### Dependencies installed
- None new (all functionality uses existing packages)
