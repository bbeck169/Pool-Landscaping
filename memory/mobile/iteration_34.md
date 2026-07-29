## Iteration 34 — Phase G1: Complete GPS Ping Ingest (Backend + Mobile + Tests)

### What was implemented

**Backend — `/app/backend/routers/gps_ingest.py` (full rewrite)**
- `POST /api/gps/pings`: Role-gated (technician/admin/super_admin, 403 for customer/manager)
- Strict field validation via Pydantic: `source ∈ {foreground, background}`, `captured_at` within 24h, `lat ∈ [-90,90]`, `lon ∈ [-180,180]`, `accuracy_m ∈ [0,10000]` (required)
- Server-side gates: `gps_settings.enabled` must be true (409 `tracking_disabled`), user must have open `time_entries` row (409 `not_clocked_in`)
- Dedup on `(user_id, captured_at, source)` — skip insert if existing row matches
- Response: `{ inserted, dedup_count, clock_in_id }`
- Batch limit 60 → 413 `batch_too_large`
- Single-ping and batch `{ pings: [...] }` body shapes accepted
- `GET /api/gps/config`: Returns `{ enabled, ping_interval_foreground_s, ping_interval_background_s }` only. No internal fields exposed.

**Backend Tests — `/app/backend/tests/test_gps_ingest.py`**
11 cases:
1. 401 unauthenticated
2. 409 tracking_disabled
3. 409 not_clocked_in
4. 200 single ping (DB verification)
5. 200 batch of 3
6. 200 dedup (repost → inserted=0, dedup=3)
7. 413 batch too large (61)
8. 422 bad source
9. 422 stale captured_at (>24h)
10. 403 customer role
11. GET /api/gps/config — only 3 keys returned

**Mobile — `/app/mobile/src/services/gpsTracker.ts` (full rewrite)**
- `startTracking(userToken)`: fetches config, requests foreground + background perms, starts `Location.watchPositionAsync` + background task (`gps-background-tracker`)
- Buffer in AsyncStorage: flushes at 20 pings, every 2 min, on foreground return, on explicit call
- `flushBufferedPings()`: posts batches, 409 → stop+clear, 413 → split-and-retry
- `stopTracking()`: removes watch, unregisters background task, clears timers
- `isTracking()`, `onTrackingStopped(cb)`, `fetchGpsConfig()`

**Mobile — `/app/mobile/app/time-clock.tsx`**
- Clock-in → `startTracking(token)` → `gpsActive=true`
- Clock-out → `stopTracking()` + `flushBufferedPings()` → `gpsActive=false`
- Best-effort resume on mount with open shift
- Green "Location tracking on" pill with navigate icon (testID: `time-clock-gps-tracking-pill`)

**Mobile Tests — `/app/mobile/__tests__/GpsTracker.test.ts`**
7 cases: no-op on disabled, starts watch on enabled, denial returns false, flush posts batch, 409 stops, 413 splits, stop unregisters watch

**Permissions — `/app/mobile/app.json`**
- iOS NSLocationWhenInUseUsageDescription: updated with employer/shift compliance text
- iOS NSLocationAlwaysAndWhenInUseUsageDescription: updated with background compliance text
- expo-location plugin: updated rationale strings

### Test counts
- Backend pytest: 11/11 green (G1) + 12/12 green (G0 gps_settings) = 23 total GPS tests
- Mobile Jest: 118/118 (111 existing + 7 new G1), 0 regressions
- `tsc --noEmit`: clean for G1 files (pre-existing errors in other files unchanged)

### Live smoke evidence
1. POST ping with tracking disabled → 409 `{"detail":{"error":"tracking_disabled"}}`
2. POST ping with enabled + open shift → 200 `{"inserted":1,"dedup_count":0,"clock_in_id":"ff6daa14-..."}`
3. Repost same ping → 200 `{"inserted":0,"dedup_count":1,"clock_in_id":"ff6daa14-..."}`

### Dependencies
- No new dependencies installed (expo-location, expo-task-manager, AsyncStorage all pre-existing)

### Known issues
- Green GPS pill only visible when clocked in + gps_settings.enabled=true + GPS permission granted
- In Expo Web preview, actual GPS pings won't fire (browser geolocation + settings gating)
- Background tracking requires native build — foreground-only in Expo Web/Go
