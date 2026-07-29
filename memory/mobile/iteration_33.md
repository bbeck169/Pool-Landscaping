## Iteration 33 — Phase G1: GPS Tracker Service + Time Clock Integration

### What was implemented
- **Backend fix**: Fixed double-nested `HTTPException` detail in `gps_ingest.py` (changed `{"detail": {"error": ...}}` to `{"error": ...}`)
- **GPS Tracker Service** (`/app/mobile/src/services/gpsTracker.ts`):
  - Wraps `expo-location` for foreground tracking
  - Fetches config from `GET /api/gps/config` to get ping interval
  - Buffers pings in AsyncStorage (`gps_ping_queue_g1` key, max 60)
  - Batch flushes via `POST /api/gps/pings`
  - On 409 → auto-stops tracking, discards buffer, invokes callback
  - Exports: `startTracking()`, `stopTracking()`, `flushPings()`, `isTracking()`, `fetchGpsConfig()`, `onTrackingStopped(cb)`
- **Time Clock UI** (`/app/mobile/app/time-clock.tsx`):
  - Auto-starts GPS tracking on clock-in success
  - Stops tracking + flushes pings on clock-out (before sending clock-out API call)
  - Best-effort resume: if screen mounts with open shift, resumes tracking
  - Green "Location tracking on" pill visible when `gpsActive` state is true
  - `onTrackingStopped` callback clears `gpsActive` on server 409

### Web-to-mobile mapping
- `POST /api/gps/pings` — same endpoint as backend
- `GET /api/gps/config` — same endpoint as backend
- GPS Tracker uses raw `fetch()` (not `api.post()`) to detect 409 status codes directly

### Permissions
- `app.json` already had all required iOS/Android location permissions (from Phase 16A)
- No changes needed

### Dependencies
- No new dependencies installed (expo-location and AsyncStorage already available)

### Known issues / deferred items
- Background GPS tracking (app closed) requires native build — not possible in Expo Web preview
- The green pill only shows in Expo Web when GPS permissions are granted AND `gps_settings.enabled=true` in the tenant's DB record
- In web smoke test, GPS tracking won't actually start because browser geolocation may not be available or `gps_settings.enabled` defaults to false

### Tests
- Backend: 6/6 pytest tests passing for GPS ingest
- Mobile: Lint clean (only pre-existing warnings)
