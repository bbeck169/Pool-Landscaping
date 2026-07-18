# Iteration 2 — Offline Draft Support

## What was implemented

### New file: `mobile/src/utils/offlineTemplateDrafts.ts`
Complete offline-draft module with:
- **Snapshot CRUD**: `writeSnapshot`, `readSnapshot`, `clearSnapshot` — per-instance local snapshots stored at `template_draft:{id}`
- **Pending queue CRUD**: `getPendingQueue`, `enqueuePending`, `removePending`, `hasPendingForInstance`, `pendingCount` — FIFO queue at `template_drafts_pending`
- **Flush routine**: `flushPendingTemplateDrafts()` — processes FIFO, PATCH each entry, removes on success, stops on `ApiNetworkError`, drops on 4xx/5xx
- **Merge logic**: `mergeLocalOverServer(serverInstance)` — compares `dirty_since` vs `updated_at`, merges local values over server if local is newer
- **Global listeners**: `registerOfflineTemplateDraftListeners()` — registers `NetInfo.addEventListener` + `AppState.addEventListener("change")` to auto-flush on reconnect/foreground

### Modified file: `mobile/app/(app)/templates/[id].tsx`
- Imports `ApiNetworkError` from api + all offline functions
- Uses `useOnline()` hook from `@/src/offline`
- **Autosave path**: calls `writeSnapshot()` BEFORE the PATCH call
- **Queue-on-failure**: catches `ApiNetworkError` → calls `enqueuePending()` → sets `saveState = "offline_queued"`
- **Merge-on-load**: calls `mergeLocalOverServer()` after fetching server data → shows yellow banner if local edits were merged
- **Finalize block**: calls `hasPendingForInstance()` before finalize → shows "Unsynced Changes" alert if pending
- **Online-transition effect**: when `online` flips true and `hasPending`, calls `flushPendingTemplateDrafts()` then reloads
- **UI indicators**: offline pill in header ("Offline — will sync"), "Saved locally" in SaveIndicator, "Loaded unsynced local edits" dismissible banner

### Modified file: `mobile/app/_layout.tsx`
- Imports and calls `registerOfflineTemplateDraftListeners()` in a `useEffect` in the root layout
- Cleanup function returned for proper teardown

### Updated: `memory/PRD.md`
- Added full Phase 3 documentation section with offline-draft behavior, constraints, and file lists

## Storage primitive choice
**AsyncStorage** (raw, via `@react-native-async-storage/async-storage`) — same primitive used by:
- `src/offline.ts` (jobs cache, pending photos, pending mutations)
- `src/services/writeQueue.ts` (checklist write queue)
- `src/services/offlineCache.ts` (job bootstrap cache)

The typed `storage` singleton from `@/src/utils/storage` restricts values to `StorageItemValue = string | number | boolean | null`. Draft objects are nested JSON with `values: Record<string, any>` — not compatible. Using raw AsyncStorage with JSON.stringify/parse is the established pattern.

## Dependencies
No new dependencies installed. All already present:
- `@react-native-async-storage/async-storage` (existing)
- `@react-native-community/netinfo` (existing)
- `ApiNetworkError` class from `@/src/api` (existing)
- `useOnline()` hook from `@/src/offline` (existing)

## Constraints documented
- Fully-offline instance CREATION is NOT supported (POST requires online)
- Only editing existing drafts is offline-tolerant
- Finalize is blocked while pending sync entries exist
