# Iteration 71 — Phase 1 Offline Read Cache for Field Techs

## What was done

### A) Route Hydrator Service
- **`src/services/routeHydrator.ts`** — proactive cache engine
  - On foreground + online: fetches `GET /jobs?start=today&end=tomorrow&technician_id=userId`
  - For each job (batches of 4): parallel fetch job detail + service-report
  - Stores in SQLite `read_cache` via `writeCache()`
  - Pub-sub pattern for React subscribers
  - Functions: `hydrateToday()`, `isJobCached()`, `getCachedJobDetail()`, `getCachedJobBootstrap()`

### B) React Hooks
- **`src/hooks/useRouteHydration.ts`** — triggers hydration on mount + app foreground, exposes meta state
- **`src/hooks/useCachedJobIds.ts`** — given job IDs, returns Set of which are cached (for schedule pills)

### C) Offline-First Reads
- **Job detail** (`app/job/[id].tsx`): network → writeCache → on error → hydrator cache → AsyncStorage → schedule cache → clean empty state
- **Checklist** (`app/job/[id]/checklist.tsx`): network → writeCache → on 429: retry+cache → on offline: hydrator cache → AsyncStorage → clean "Not cached" state
- Both show amber "You're offline — showing cached copy" banner when serving from cache
- Both show clean "Not cached for offline" empty state instead of red error when no cache available

### D) UI Indicators
- **"Cached ✓" pill** per job row on schedule (green mint pill with checkmark)
- **Enhanced OfflineBadge**: "Offline — X of Y jobs cached • synced 7:42 AM"
- **Clean empty states**: "Not cached for offline. Connect to Wi-Fi or cellular once..." (no red errors)

### E) Diagnostics
- **`app/(app)/settings/offline-diagnostics.tsx`** — shows status, total/job cache entries, byte size, route stats, last hydration time
- "Rebuild cache" button (triggers hydration) + "Purge cache" button (clears all)

### F) Logout Purge
- Added `clearAllReadCache()` to auth logout flow — different users on shared devices can't see each other's cached routes

### G) ReadCache Enhancements
- Added `countCacheKeys(prefix?)` and `cacheByteSize()` to `readCache.ts` for diagnostics

## Files added (4)
- `src/services/routeHydrator.ts`
- `src/hooks/useRouteHydration.ts`
- `src/hooks/useCachedJobIds.ts`
- `app/(app)/settings/offline-diagnostics.tsx`

## Files modified (6)
- `app/job/[id].tsx` — offline-first reads + cached banner + empty state
- `app/job/[id]/checklist.tsx` — hydrator cache integration + "Not cached" state
- `app/(app)/schedule/calendar.tsx` — hydrator trigger + "Cached ✓" pills + OfflineBadge stats
- `src/components/OfflineBadge.tsx` — enhanced with cache stats
- `src/auth.tsx` — cache purge on logout
- `src/services/readCache.ts` — diagnostics helpers

## Tests
- 16 new tests in `__tests__/phase1-offline-read.test.tsx`
- 39 total tests across 5 suites — all passing, no regressions

## Known limitations
- Hydrator only caches today's route — past/future day jobs are not proactively cached
- SQLite not encrypted at rest (relies on device-level encryption)
- Write flows (mark complete, photo upload) NOT in scope — Phase 2
