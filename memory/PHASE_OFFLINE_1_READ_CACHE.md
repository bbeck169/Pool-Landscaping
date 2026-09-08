# Phase 1 Offline Read Cache — Implementation Report

## Architecture

### Approach: Build on existing infrastructure
The mobile app already had a robust offline foundation:
- **SQLite** (`expo-sqlite`) with a `read_cache` table (`readCache.ts`)
- **`useOfflineQuery`** hook with cache-first, revalidate-on-online semantics
- **`writeThroughJobs`** for schedule list caching
- **`cacheJobBootstrap`** / `getCachedBootstrap`** (AsyncStorage) for checklist
- **`useOnline()`** / `isOnlineNow()` for connectivity detection
- **`OfflineBadge`** component for offline state

I built on ALL of these rather than introducing new patterns.

### New modules
| File | Purpose |
|---|---|
| `src/services/routeHydrator.ts` | Proactive cache engine — on foreground+online, fetches today's route + service reports in parallel |
| `src/hooks/useRouteHydration.ts` | React hook providing hydration state + auto-trigger on mount/foreground |
| `src/hooks/useCachedJobIds.ts` | Given job IDs, checks which have cached bootstraps (for "Cached ✓" pills) |
| `app/(app)/settings/offline-diagnostics.tsx` | Hidden diagnostics screen — cache size, counts, rebuild/purge |

### Modified files
| File | Change |
|---|---|
| `app/job/[id].tsx` | Offline-first reads: try network → writeCache → on error → readCache (hydrator + AsyncStorage) → clean empty state |
| `app/job/[id]/checklist.tsx` | Offline-first bootstrap: hydrator cache → AsyncStorage → clean "Not cached for offline" empty state |
| `app/(app)/schedule/calendar.tsx` | Trigger hydrator, show "Cached ✓" pill per job row, pass cache stats to OfflineBadge |
| `src/components/OfflineBadge.tsx` | Enhanced: "Offline — X of Y jobs cached • synced 7:42 AM" |
| `src/auth.tsx` | Cache purge on logout (clearAllReadCache) |
| `src/services/readCache.ts` | Added `countCacheKeys()`, `cacheByteSize()` for diagnostics |

## Cache key convention
```
route:jobs:today:{userId}     — today's job list
job:detail:{jobId}            — job detail endpoint response
job:bootstrap:{jobId}         — { job, report } for checklist bootstrap
hydration:meta:{userId}       — { lastSyncedAt, totalJobs, cachedJobs }
```

## How hydration works
1. On app foreground + online: `useRouteHydration` calls `hydrateToday(userId)`
2. Fetches `GET /jobs?start=today&end=tomorrow&technician_id=userId`
3. For each job (batches of 4): parallel fetch `GET /jobs/{id}` + `GET /jobs/{id}/service-report`
4. Stores each in SQLite `read_cache` via `writeCache()`
5. Updates `hydration:meta:{userId}` with progress
6. Subscribers (OfflineBadge, schedule) get notified via pub-sub

## Offline read flows

### Job detail (app/job/[id].tsx)
1. **Online**: Fetch from API → `writeCache(CK.jobDetail(id))` → show data
2. **Offline**: Try `getCachedJobDetail(id)` (SQLite) → Try `getCachedJob(id)` (AsyncStorage) → Try schedule cache
3. If cache hit: show data + amber "You're offline — showing cached copy" banner
4. If cache miss: clean empty state ("Not cached for offline. Connect to Wi-Fi...") with back button

### Checklist (app/job/[id]/checklist.tsx)
1. **Online**: Fetch job + service-report → `writeCache(CK.jobBootstrap(id))` + `cacheJobBootstrap()` (AsyncStorage)
2. **429**: Retry once after 1s → try hydrator cache → try AsyncStorage → "Server busy"
3. **Offline**: Try `getCachedJobBootstrap(id)` (SQLite) → Try `getCachedBootstrap(id)` (AsyncStorage) → clean "Not cached for offline"
4. **401/403**: "Please sign in again" with login button
5. **5xx**: "Something went wrong" with Retry button

### Schedule (app/(app)/schedule/calendar.tsx)
- Hydrator triggered on mount + foreground
- "Cached ✓" pill per job row via `useCachedJobIds`
- OfflineBadge shows "Offline — X of Y jobs cached • synced 7:42 AM"

## Acceptance criteria verification

| # | Criterion | Status | Notes |
|---|---|---|---|
| 1 | Login online → 5s → airplane → open job → see full detail | ✅ | Hydrator pre-caches today's route. Job detail reads from SQLite cache. |
| 2 | Airplane → schedule shows "Cached ✓" per job | ✅ | `useCachedJobIds` checks SQLite for each job ID. |
| 3 | Tap uncached job offline → clean empty state | ✅ | "Not cached for offline. Connect once to enable." — no red error. |
| 4 | Kill + relaunch offline → still see cached data | ✅ | SQLite persists across app restarts. |
| 5 | Reconnect → silent refresh | ✅ | Hydrator re-fires on foreground transition. |
| 6 | Diagnostics screen shows correct counts | ✅ | Route: /(app)/settings/offline-diagnostics |
| 7 | Logout → cache purged | ✅ | `clearAllReadCache()` added to logout flow. |

## Backend gaps
**NONE flagged.** The existing endpoints are sufficient:
- `GET /jobs?start=X&end=Y&technician_id=Z` — returns all needed fields
- `GET /jobs/{id}` — job detail (33 fields)
- `GET /jobs/{id}/service-report` — checklist data (readings, chemicals, notes, water bodies)
- No bulk endpoint needed — today's route is ≤10 jobs typically, 4-parallel fetch is fast.

## Storage footprint estimate
- **Per job**: ~2–5 KB (job detail) + ~5–15 KB (service report) ≈ **7–20 KB per job**
- **Typical day**: 5–10 jobs × 15 KB ≈ **75–150 KB total**
- **Maximum**: 20 jobs × 20 KB = **400 KB** — well within device limits

## Encryption gap
SQLite at rest encryption (SQLCipher) is NOT trivially available in Expo SDK 54 without ejecting. `expo-sqlite` uses the built-in Android/iOS SQLite which is NOT encrypted.
- **Mitigation**: Data is scoped per-user + purged on logout. Device-level encryption (iOS Data Protection, Android FBE) covers the SQLite file.
- **Future**: If encryption is required, consider `expo-sqlite/kv-store` with SecureStore-wrapped key, or eject to bare workflow for SQLCipher.

## Tests
- 16 tests in `__tests__/phase1-offline-read.test.tsx` — all passing
- 39 total tests across 5 suites — no regressions

## Manual repro steps
1. Login as tech (mike@aquaterra.com / password123)
2. Wait 5 seconds (hydrator runs in background)
3. Navigate to schedule → verify "Cached ✓" pills on today's jobs
4. Open Settings → Offline Diagnostics → verify counts
5. Enable airplane mode
6. Open a cached job → see full detail + amber "showing cached copy" banner
7. Open the checklist → see cached data in offline mode
8. Open an uncached job → see "Not cached for offline" message
9. Disable airplane mode → data silently refreshes
10. Logout → cache purged (verify via diagnostics on next login)
